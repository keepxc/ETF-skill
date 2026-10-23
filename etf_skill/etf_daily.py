"""纳指 100 场内 ETF 定投日报（多标的比价 + 固定月投）

溢率 = 现价 ÷ 基金净值 − 1，两个口径并列输出：
  券商口径：用最新已公布净值（与券商 App / 腾讯行情一致）
  修正口径：把滞后净值按纳指涨跌折算到最新美股收盘日 —— 决策用这个
QDII 净值通常滞后 1~2 个交易日，滞后期间溢率会被指数涨跌污染：指数隔夜下跌而净值
尚未更新时，券商口径会**低估**真实溢率（2026-10-23 实测券商 +6.43%、真实 +9.60%）。
"""
import sys, json, re, time, datetime, urllib.request
from pathlib import Path

import etf_signals

HERE        = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "dca_config.json"
STATE_PATH  = HERE / "dca_state.json"
FEE_CACHE   = HERE / "fee_cache.json"
PREM_LOG    = HERE / "premium_log.json"
POS_PATH    = HERE / "position.json"
RUN_STATE   = HERE / "run_state.json"

ANN_URL     = "https://api.fund.eastmoney.com/f10/JJGG?fundcode={c}&pageIndex=1&pageSize=10&type=0"

WEEKDAY_CN  = ["周一","周二","周三","周四","周五","周六","周日"]
NDX_PE_URL  = "https://historyofmarket.com/api/ndx/forward-pe.json"
MKG_URL     = "https://www.marketgrep.com/api/summary"
UA          = "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36"


def _get(url, encoding="utf-8", referer=None, timeout=15):
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="replace")


def _mkt(code):
    return "sh" if code.startswith("5") else "sz"


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 数据获取 ──────────────────────────────────────────────

def fetch_quotes(codes):
    """腾讯行情批量取价。返回 {code: {name, price, prev_close, ts}}"""
    raw = _get("https://qt.gtimg.cn/q=" + ",".join(_mkt(c) + c for c in codes), encoding="gbk")
    out = {}
    for line in raw.strip().split(";"):
        f = line.split("~")
        if len(f) < 40:
            continue
        try:
            out[f[2]] = {
                "name": f[1],
                "price": float(f[3]) if f[3] else None,
                "prev_close": float(f[4]) if f[4] else None,
                "vol": float(f[6]) if f[6] else 0.0,
                "ts": datetime.datetime.strptime(f[30], "%Y%m%d%H%M%S"),
            }
        except (ValueError, IndexError):
            continue
    return out


def fetch_kline(code, n=30):
    """日 K（不复权）。返回 [(date_str, close, turnover_yuan)]；成交量单位为手"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={_mkt(code)}{code},day,,,{n},"
    d = json.loads(_get(url))["data"][_mkt(code) + code]
    rows = d.get("day") or d.get("qfqday") or []
    return [(r[0], float(r[2]), float(r[5]) * 100 * float(r[2])) for r in rows]


def fetch_navs(code):
    """东财官方净值（最近 20 条）。返回 {date_str: nav}"""
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=20"
    d = json.loads(_get(url, referer=f"https://fund.eastmoney.com/{code}.html", timeout=10))
    return {x["FSRQ"]: float(x["DWJZ"]) for x in d.get("Data", {}).get("LSJZList", []) if x.get("DWJZ")}


def fetch_fee(code):
    """东财费率页：管理费 + 托管费（%/年）"""
    t = _get(f"https://fundf10.eastmoney.com/jjfl_{code}.html", timeout=10)
    t = re.sub(r"<[^>]+>", " ", t)
    mg = re.search(r"管理费率\s*([\d.]+)%", t)
    cu = re.search(r"托管费率\s*([\d.]+)%", t)
    if not (mg and cu):
        raise ValueError("费率解析失败")
    return round(float(mg.group(1)) + float(cu.group(1)), 4)


def get_fees(codes, refresh_days):
    """按周刷新费率；返回 ({code: fee}, [变动提示], [失败代码])"""
    cache = _load(FEE_CACHE, {})
    today = datetime.date.today()
    changes, failed = [], []
    for c in codes:
        ent = cache.get(c)
        fresh = ent and (today - datetime.date.fromisoformat(ent["date"])).days < refresh_days
        if fresh:
            continue
        try:
            fee = fetch_fee(c)
        except Exception:
            failed.append(c)
            continue
        if ent and abs(ent["fee"] - fee) > 1e-9:
            changes.append(f"{c} 费率 {ent['fee']:.2f}% → {fee:.2f}%")
        cache[c] = {"fee": fee, "date": today.isoformat()}
    _save(FEE_CACHE, cache)
    return {c: cache[c]["fee"] for c in codes if c in cache}, changes, failed


def fetch_ndx_pe():
    try:
        c = json.loads(_get(NDX_PE_URL)).get("current", {})
        return {"t": c.get("trailing"), "f": c.get("forward")}
    except Exception:
        return None


def fetch_ndx_closes(n=15):
    """纳指100 已完成交易日的收盘序列（腾讯美股K线），用于把滞后净值折算到最新美股收盘日。
    只取已收盘的日线，避免把盘中未完成的美国交易日混进与 A 股收盘价的比对。"""
    end = datetime.date.today()
    today = end.isoformat()
    start = end - datetime.timedelta(days=n * 2 + 10)
    u = ("https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?"
         f"param=usNDX,day,{start},{end},{n * 2 + 10},qfq")
    for _ in range(3):
        try:
            d = json.loads(_get(u, timeout=10))["data"]["usNDX"]
            rows = d.get("day") or d.get("qfqday") or []
            # 剔除当日（美股 21:30 后才开盘，当日报价是未完成的盘中bar）
            return {r[0]: float(r[2]) for r in rows if r[0] < today}
        except Exception:
            time.sleep(1)
    return {}


def correct_nav(nav_date, nav, ndx):
    """按纳指涨跌把滞后净值折算到最新美股收盘日。返回 (est_nav, ref_date)"""
    if not ndx or not nav_date or nav_date not in ndx:
        return None, None
    ref = max(ndx)
    base = ndx[nav_date]
    if not base:
        return None, None
    return nav * (ndx[ref] / base), ref


def fetch_marketgrep():
    try:
        d = json.loads(_get(MKG_URL))
    except Exception:
        return None
    u, t = d.get("us", {}), d.get("turbulence", {})
    regime = u.get("regime", "")
    dspx, cor1m = u.get("dspx"), u.get("cor1m")
    rl = "Risk ON" if "risk_on" in regime else "Risk OFF" if "risk_off" in regime else regime
    disp = "分散度高" if dspx and dspx > 35 else "分散中等" if dspx and dspx > 25 else "集中度高"
    parts = [f"VIX {u.get('vix')}", f"{rl} ({u.get('exposure_score')})", disp]
    if cor1m is not None:
        parts.append("个股分化" if cor1m < 15 else "板块联动" if cor1m < 30 else "同涨同跌")
    if t.get("state"):
        parts.append(f"湍流 {t['state']}")
    return " | ".join(parts)


# ── 开盘时点判定（不写死时间：按当日公告 + 实际成交判断） ──────

def halt_notice_today(codes, today):
    """今日是否有开市临停公告。公告在前一交易日晚间 18:30 发布，开盘前即可判读。
    返回摘要字符串或 None"""
    ds = today.isoformat()
    for c in codes:
        try:
            d = json.loads(_get(ANN_URL.format(c=c), referer="https://fund.eastmoney.com/", timeout=10))
        except Exception:
            continue
        for it in (d.get("Data") or []):
            t = it.get("TITLE") or ""
            if str(it.get("PUBLISHDATEDesc") or "")[:10] == ds and any(k in t for k in ("停牌", "停复牌")):
                return f"{c} 临停公告"
    return None


def traded_today(q, today):
    """今日是否已有成交（临停期间成交量为 0）"""
    return bool(q) and q["ts"].date() == today and (q.get("vol") or 0) > 0


# ── 溢价计算 ──────────────────────────────────────────────

def price_basis(q, cal, now):
    """确定用于溢价的价格及其日期。
    盘中(≥09:30)用实时价；集合竞价/盘前用昨收；休市用最近收盘。"""
    ts = q["ts"]
    if ts.date() == now.date():
        if now.time() > datetime.time(15, 0):
            return q["price"], now.date().isoformat(), "收盘"
        if ts.time() >= datetime.time(9, 30):
            return q["price"], now.date().isoformat(), "实时"
        prev = [d for d in cal if d < now.date().isoformat()]
        return q["prev_close"], (prev[-1] if prev else None), "昨收"
    return q["price"], ts.date().isoformat(), "收盘"


def calc_premium(price, price_date, navs, cal):
    """返回 dict(prem, nav, nav_date, lag) 或 None"""
    if not (price and price_date and navs):
        return None
    prev = [d for d in cal if d < price_date]
    if not prev:
        return None
    expected = prev[-1]
    usable = sorted(d for d in navs if d <= expected)
    if not usable:
        return None
    nd = usable[-1]
    lag = sum(1 for d in cal if nd < d <= expected)
    nav = navs[nd]
    return {"prem": (price / nav - 1) * 100, "nav": nav, "nav_date": nd, "lag": lag}


def log_premiums(rows, codes):
    """按价格日期记录决策池溢率（修正口径），供周报回顾。{price_date: {code: prem}}，保留 120 条"""
    log = _load(PREM_LOG, {})
    for c in codes:
        r = rows.get(c, {})
        if r.get("prem_use") is not None and r.get("price_date"):
            log.setdefault(r["price_date"], {})[c] = round(r["prem_use"], 2)
    _save(PREM_LOG, dict(sorted(log.items())[-120:]))


# ── 定投决策 ──────────────────────────────────────────────

def pick_tier(prem, tiers):
    for t in tiers:
        if t["below"] is None or prem < t["below"]:
            return t
    return tiers[-1]


def plan_amount(tier, base, backlog, cap):
    """返回 (本次投入, 投后积压)。
    低档位(release_backlog)：max(档位金额, 基准 + 全部积压)；
    其余：按档位金额，少投部分计入积压，积压不超过 cap。"""
    if tier.get("release_backlog"):
        return max(tier["amount"], base + backlog), 0
    amt = tier["amount"]
    return amt, min(cap, backlog + max(0, base - amt))


def commission(amount, cfg):
    c = cfg["commission"]
    if amount <= 0:
        return 0.0
    fee = amount * c["rate"]
    return fee if c["free_of_min"] else max(fee, c["min_per_order"])


def is_dca_day(today, trading_today, dca_day, state):
    month = today.strftime("%Y-%m")
    return trading_today and today.day >= dca_day and state.get("last_dca_month") != month


def next_dca_label(today, dca_day, state):
    if state.get("last_dca_month") != today.strftime("%Y-%m"):
        if today.day >= dca_day:
            return "下一个交易日（本月尚未执行）"
        return f"{today.month}月{dca_day}日（遇休市顺延）"
    m = 1 if today.month == 12 else today.month + 1
    return f"{m}月{dca_day}日（遇休市顺延）"


# ── 持仓敞口 ──────────────────────────────────────────────

def render_position(rows):
    """持仓真实敞口：市值 / 浮盈亏 / NAV资产与溢价空气拆分 / 触发线"""
    pos = _load(POS_PATH, None)
    if not pos or not pos.get("positions"):
        return []
    tg = pos.get("trigger", {})
    L = ["", "=" * 48, "  📦 持仓敞口", "=" * 48]
    for p in pos["positions"]:
        r = rows.get(p["code"])
        if not r or r.get("price") is None or r.get("prem") is None:
            L.append(f"  {p['code']} 数据缺失")
            continue
        px = r["price"]
        nav = r.get("nav_est") or r["nav"]
        prem = r["prem_est"] if r.get("prem_est") is not None else r["prem"]
        sh, cost = p["shares"], p["cost"]
        total, mv = sh * cost, sh * px
        navval = sh * nav
        air = mv - navval
        L.append(f"  {p['code']} {r['name']}  {sh} 股 @ {cost:.4f}")
        L.append(f"    现价 {px:.3f}  市值 {mv:,.0f}  盈亏 {mv - total:+,.0f}（{(mv - total) / total * 100:+.2f}%）")
        L.append(f"    NAV资产 {navval:,.0f} + 溢率空气 {air:,.0f}（占市值 {air / mv * 100:.1f}%）")
        if r.get("prem_est") is not None:
            L.append(f"    当前溢率 {prem:+.2f}%（修正口径；券商口径 {r['prem']:+.2f}%）")
        else:
            L.append(f"    当前溢率 {prem:+.2f}%")
        L.append(f"    回本需价格 {cost:.4f}（{(cost / px - 1) * 100:+.2f}%），对应溢率 {(cost / nav - 1) * 100:+.2f}%")
        a, w = tg.get("add_below_prem"), tg.get("watch_above_prem")
        if a is not None:
            pa = nav * (1 + a / 100)
            L.append(f"    加仓线 溢率<{a:.0f}% → 价格 {pa:.3f}（还需 {(pa / px - 1) * 100:+.1f}%）")
        if w is not None and prem >= w:
            L.append(f"    ⚠ 溢率 {prem:.2f}% 已触及警戒线 {w:.0f}%")
    L.append(f"  依据：{best_note(rows, pos)}")
    return L


def best_note(rows, pos):
    c = pos["positions"][0]["code"] if pos.get("positions") else ""
    r = rows.get(c, {})
    if r.get("nav_est"):
        return (f"溢率用纳指修正口径（官方净值 {r['nav_date']} {r['nav']:.4f} 滞后 {r.get('lag', 0)} 个交易日，"
                f"已按纳指折算至 {r['est_ref']}；券商口径 {r['prem']:+.2f}%）")
    if r.get("price_date") and r.get("nav_date"):
        return f"市价 {r['price_date']} ÷ 净值 {r['nav_date']}，净值滞后 {r.get('lag', 0)} 个交易日"
    return "净值口径见上方【溢率口径】"


# ── 主流程 ────────────────────────────────────────────────

def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg   = _load(CONFIG_PATH, None)
    state = _load(STATE_PATH, {"backlog": 0, "last_dca_month": None, "history": []})
    now   = datetime.datetime.now()
    today = now.date()
    pool, watch = cfg["pool"], cfg["watch"]
    errors = []
    rstate = _load(RUN_STATE, {})

    # 今日已推送 → 静默退出（供 10:32 兜底任务去重）
    if rstate.get("sent") == today.isoformat():
        return

    def defer(reason):
        _save(RUN_STATE, {**rstate, "defer": today.isoformat(), "defer_reason": reason})

    # ① 未开盘
    if now.time() < datetime.time(9, 30):
        defer("未到开盘")
        return

    # ② 当日开市临停公告（前一交易日晚间 18:30 发布，开盘前已可知）
    halt = halt_notice_today(pool[:1], today)
    if halt and now.time() < datetime.time(10, 31):
        defer(f"{halt}，开市停牌至 10:30")
        return

    # ③ 取行情：未停牌时等开盘首笔成交（最多 120 秒，最迟 09:33 收工）
    quotes, qerr = {}, None
    deadline = time.time() + 120
    while True:
        try:
            quotes = fetch_quotes(pool + watch)
            qerr = None
        except Exception as e:
            qerr = f"行情({type(e).__name__})"
        if halt or traded_today(quotes.get(pool[0]), today):
            break
        if datetime.datetime.now().time() >= datetime.time(9, 33) or time.time() >= deadline:
            break
        time.sleep(10)
    if qerr:
        errors.append(qerr)

    # ④ 无公告却开盘无成交 → 按临停处理，等复牌后再报
    if (not halt and not traded_today(quotes.get(pool[0]), today)
            and datetime.time(9, 32) <= now.time() < datetime.time(10, 31)):
        defer("开盘无成交（疑似临停）")
        return

    cal = []
    try:
        cal = [r[0] for r in fetch_kline(pool[0], 60)]
    except Exception as e:
        errors.append(f"交易日历({type(e).__name__})")

    fees, fee_changes, fee_failed = get_fees(pool + watch, cfg["fee_refresh_days"])
    if fee_failed:
        errors.append("费率:" + ",".join(fee_failed))

    ndx = fetch_ndx_closes()
    rows = {}
    for c in pool + watch:
        q = quotes.get(c)
        r = {"code": c, "name": q["name"] if q else c, "fee": fees.get(c), "prem": None}
        if not q:
            errors.append(f"{c}行情")
            rows[c] = r
            continue
        price, pdate, plabel = price_basis(q, cal, now)
        r.update(price=price, price_date=pdate, price_label=plabel)
        try:
            k = fetch_kline(c, 20)
            r["avg_turnover"] = sum(x[2] for x in k) / len(k) / 1e8 if k else None
        except Exception:
            r["avg_turnover"] = None
        try:
            pr = calc_premium(price, pdate, fetch_navs(c), cal)
        except Exception:
            pr = None
        if pr:
            r.update(pr)
            est, ref = correct_nav(pr["nav_date"], pr["nav"], ndx)
            if est and ref != pr["nav_date"]:
                r["nav_est"], r["est_ref"] = est, ref
                r["prem_est"] = (price / est - 1) * 100
        else:
            errors.append(f"{c}净值")
        r["prem_use"] = r["prem_est"] if r.get("prem_est") is not None else r.get("prem")
        rows[c] = r

    log_premiums(rows, pool)
    trading_today = any(q["ts"].date() == today for q in quotes.values())
    pool_ok = sorted((rows[c] for c in pool if rows[c]["prem_use"] is not None), key=lambda r: r["prem_use"])
    best = pool_ok[0] if pool_ok else None

    # ── 输出 ──
    L = ["", "=" * 48, "  📊 纳指 100 场内 ETF 定投日报",
         f"  📅 {now:%m-%d %H:%M}（{WEEKDAY_CN[today.weekday()]}{'' if trading_today else ' · 休市'}）",
         "=" * 48]
    if rstate.get("defer") == today.isoformat():
        L.append(f"  ⏸ {rstate.get('defer_reason', '开盘延迟')} → 以下为复牌后实时价")
    if errors:
        L.append(f"  ⚠ 部分数据获取失败：{'、'.join(dict.fromkeys(errors))}")

    L += ["", "【标的比价】决策池，按溢率升序"]
    any_corr = False
    for r in pool_ok + [rows[c] for c in pool if rows[c]["prem_use"] is None]:
        fee = f"{r['fee']:.2f}%" if r["fee"] is not None else "费率缺失"
        tv  = f"{r['avg_turnover']:.2f}亿" if r.get("avg_turnover") else "成交缺失"
        if r["prem_use"] is None:
            L.append(f"  {r['code']} {r['name']}  数据缺失")
            continue
        tag = "  ← 最低" if r is best else ""
        mark = "*" if r.get("prem_est") is not None else ""
        any_corr = any_corr or bool(mark)
        L.append(f"  {r['code']} {r['name']}  价 {r['price']:.3f}  溢率 {r['prem_use']:+.2f}%{mark}  "
                 f"费率 {fee}  日均 {tv}{tag}")
    if any_corr:
        L.append("  * 已按纳指折算到最新美股收盘日；无 * 的净值已是最新，两口径相同")

    if best:
        L += ["", "【溢率口径】现价 ÷ 基金净值 − 1",
              f"  {best['code']} 价格 {best['price_label']} {best['price_date']} {best['price']:.3f}"]
        L.append(f"    券商口径：÷ 官方净值 {best['nav_date']} {best['nav']:.4f}"
                 f"（滞后 {best['lag']} 个交易日）→ {best['prem']:+.2f}%")
        if best.get("nav_est"):
            L.append(f"    修正口径：{best['nav']:.4f} × 纳指 {best['nav_date'][5:]}→{best['est_ref'][5:]}"
                     f" = {best['nav_est']:.4f} → {best['prem_est']:+.2f}%  ← 决策用这个")
            L.append("    净值未公布时券商口径会被指数涨跌污染：指数隔夜跌→低估，涨→高估")
        else:
            L.append("    净值已是最新，两个口径相同")
        lagged = [r["code"] for r in pool_ok if r["lag"] > 0]
        if lagged:
            L.append(f"  ⚠ {','.join(lagged)} 净值滞后 {max(r['lag'] for r in pool_ok)} 个交易日，已按纳指折算")

    # 监视池提示
    wa = cfg["watch_alert"]
    alerts = [rows[c] for c in watch
              if rows[c]["prem_use"] is not None and best
              and (rows[c].get("avg_turnover") or 0) >= wa["min_avg_turnover_yi"]
              and rows[c]["prem_use"] <= best["prem_use"] - wa["premium_gap_pct"]]
    if alerts or fee_changes:
        L += ["", "【监视提示】"]
        for r in alerts:
            L.append(f"  {r['code']} {r['name']} 溢率 {r['prem_use']:+.2f}%（比 {best['code']} 低 "
                     f"{best['prem_use'] - r['prem_use']:.2f}pct，日均 {r['avg_turnover']:.2f}亿），可考虑调入决策池")
        for s in fee_changes:
            L.append(f"  ⚠ {s}")

    pe, mg = fetch_ndx_pe(), fetch_marketgrep()
    if (pe and pe.get("f")) or mg:
        L += ["", "【市场状态】"]
        if pe and pe.get("f"):
            L.append(f"  NDX PE: Tr {pe['t']} | Fwd {pe['f']}")
        if mg:
            L.append(f"  {mg}")

    # 定投建议
    base, cap = cfg["monthly_base_amount"], cfg["backlog_cap"]
    backlog = state.get("backlog", 0)
    L += ["", "=" * 48, "  💡 定投建议", "=" * 48]
    if not best:
        L.append("  ★ 决策池溢价数据缺失，无法给出金额，请人工查看")
    else:
        tier = pick_tier(best["prem_use"], cfg["premium_tiers"])
        amount, new_backlog = plan_amount(tier, base, backlog, cap)
        dca_now = is_dca_day(today, trading_today, cfg["dca_day"], state)
        head = "今日定投" if dca_now else f"按当前溢率预估（下次定投：{next_dca_label(today, cfg['dca_day'], state)}）"
        L.append(f"  ★ {head}：{amount} 元（{tier['label']}）")
        if amount > 0:
            L.append(f"  ★ 标的：513390 纳指100ETF博时（当前持有，月投 1000 元）")
        L.append(f"  ★ 依据：长期定投下溢率会被均值抹平，按每月 1000 元固定定投")
        cm = commission(amount, cfg)
        if amount > 0:
            L.append(f"  ★ 预估佣金 {cm:.2f} 元（占 {cm / amount * 100:.2f}%）")
        L.append(f"  ★ 积压资金：{backlog} 元 → 投后 {new_backlog} 元（上限 {cap}）")
        if not cfg["commission"]["free_of_min"]:
            L.append("  ★ 未免 5：只做月投，勿拆周投")
        if dca_now:
            state["backlog"] = new_backlog
            state["last_dca_month"] = today.strftime("%Y-%m")
            state.setdefault("history", []).append({
                "date": today.isoformat(), "code": best["code"], "premium": round(best["prem_use"], 2),
                "tier": tier["label"], "amount": amount, "backlog_after": new_backlog})
            _save(STATE_PATH, state)

    # 持仓真实敞口：市值 / 浮盈亏 / NAV资产与溢价空气拆分 / 触发线
    L += render_position(rows)

    # 纳指择时信号：QQQ MA200 止盈 + 回撤加仓档位（独立于上面的月度定投）
    L += etf_signals.render_sections(cfg, best)

    L += ["=" * 48, ""]
    _save(RUN_STATE, {**rstate, "sent": today.isoformat()})
    print("\n".join(L))


if __name__ == "__main__":
    main()
