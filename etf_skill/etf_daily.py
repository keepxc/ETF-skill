"""纳指 100 场内 ETF 定投日报（多标的比价 + 固定月投）

溢率 = 现价 ÷ 基金净值 − 1，两个口径并列输出：
  券商口径：用最新已公布净值（与券商 App / 腾讯行情一致）
  修正口径：滞后净值 × 纳指涨跌 × 美元人民币涨跌 —— 决策用这个
QDII 净值通常滞后 1~2 个交易日，滞后期间溢率会被指数涨跌与汇率双重污染：指数隔夜下跌而
净值尚未更新时，券商口径会**低估**真实溢率（2026-10-23 实测券商 +6.43%、真实 +9.60%）。
净值以人民币计价：纳指不动而人民币升值 1% → 净值跌 1%，所以折算必须同时乘汇率比。

版面分三层：结论（今天做什么）→ ①②③（仓位 / 溢率贵不贵 / 通道更便宜吗）→ 附录（数据）。
ETF_FORCE=1 环境变量 = 试跑：跳过去重、不写 run_state.sent，交易日随时可干跑。
"""
import sys, os, json, re, csv, time, datetime, statistics, urllib.request
from pathlib import Path

import etf_signals

HERE        = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "dca_config.json"
STATE_PATH  = HERE / "dca_state.json"
FEE_CACHE   = HERE / "fee_cache.json"
PREM_LOG    = HERE / "premium_log.json"
POS_PATH    = HERE / "position.json"
RUN_STATE   = HERE / "run_state.json"
PREM_HIST   = HERE / "history_premium.csv"

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


FX_URL = ("https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/x/"
          "NewForexService.getDayKLine?symbol=fx_susdcny")


def fetch_fx_closes():
    """美元人民币 日收盘序列（新浪外汇，直连）。返回 {date: close}。
    QDII 净值以人民币计价，折算到最新美股收盘日必须同时乘汇率比，
    否则人民币升值的日子会把溢率算高（3 个月人民币升 1.5% ≈ 溢率高估 1.5pct）。"""
    for _ in range(3):
        try:
            t = _get(FX_URL, timeout=10)
            hit = re.findall(r"(\d{4}-\d{2}-\d{2}),([\d.]+),([\d.]+),([\d.]+),([\d.]+)", t)
            out = {d: float(c) for d, _o, _l, _h, c in hit if float(c) > 0}
            if out:
                return out
        except Exception:
            time.sleep(1)
    return {}


def correct_nav(nav_date, nav, ndx, fx=None):
    """把滞后净值折算到最新美股收盘日：净值 × 纳指涨跌 × 美元人民币涨跌。
    返回 (est_nav, ref_date, ndx_ret, fx_ret)；fx_ret 为小数（-0.0007 = -0.07%）。"""
    if not ndx or not nav_date or nav_date not in ndx:
        return None, None, None, None
    ref = max(ndx)
    base = ndx[nav_date]
    if not base:
        return None, None, None, None
    ndx_ret = ndx[ref] / base - 1
    fx_ret = 0.0
    if fx and nav_date in fx and ref in fx and fx[nav_date]:
        fx_ret = fx[ref] / fx[nav_date] - 1
    return nav * (1 + ndx_ret) * (1 + fx_ret), ref, ndx_ret, fx_ret


def premium_stats(cur, code="513390"):
    """历史溢率分布与近期走势。CSV 全史 + premium_log 里更新的日期（CSV 停在 2026-09 末）。
    返回 dict(n, median, p95, p99, pctile, trend, streak) 或 None。"""
    if cur is None:
        return None
    vals = {}
    try:
        with PREM_HIST.open(encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and len(row) >= 4 and row[0][:4].isdigit():
                    try:
                        vals[row[0]] = float(row[3])
                    except ValueError:
                        continue
    except OSError:
        pass
    for d, mp in _load(PREM_LOG, {}).items():
        if isinstance(mp, dict) and mp.get(code) is not None:
            vals[d] = mp[code]
    if len(vals) < 60:
        return None
    ser = sorted(vals.items())
    v = [x for _, x in ser]
    v_sorted = sorted(v)
    pctile = sum(1 for x in v if x < cur) / len(v) * 100

    def q(p):
        return v_sorted[min(len(v_sorted) - 1, int(p * (len(v_sorted) - 1)))]

    recent = [x for x in ser if x[0] >= "2026-09-01"] or ser[-30:]
    peak = max(recent, key=lambda x: x[1])
    trend = f"{recent[0][0][5:]} {recent[0][1]:.1f} → {peak[0][5:]} {peak[1]:.1f}(峰) → 今天 {cur:.1f}"
    streak = 0
    for _, x in reversed(ser):
        if x >= 8.0:
            streak += 1
        else:
            break
    return {"n": len(v), "median": statistics.median(v), "p95": q(0.95), "p99": q(0.99),
            "pctile": pctile, "trend": trend, "streak": streak}


def fetch_sub_status(code):
    """场外联接基金的申购状态（东财基金页）。返回 '暂停申购' / '限大额 上限100元' / '开放申购' / None。
    溢率>0.5% 本该改走场外按净值成交，但 QDII 额度耗尽期联接基金常同步暂停申购 ——
    这一行存在的意义就是让「换通道」这个建议先过长假/限购的现实检验。"""
    try:
        t = re.sub(r"<[^>]+>", " ", _get(f"https://fund.eastmoney.com/{code}.html", timeout=10))
        t = re.sub(r"\s+", " ", t)
        i = t.find("交易状态：")
        if i < 0:
            return None
        seg = t[i:i + 60]
        m = re.search(r"(暂停申购|开放申购|限大额|暂停买入|封闭期)", seg)
        if not m:
            return None
        cap = re.search(r"上限\s*([\d.,]+)\s*元", seg)
        return m.group(1) + (f" 上限{cap.group(1)}元" if cap else "")
    except Exception:
        return None


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
    """① 我的仓位：市值 / 浮亏 / 净值与溢率空气拆分 / 回本线 / 加仓线"""
    pos = _load(POS_PATH, None)
    if not pos or not pos.get("positions"):
        return []
    tg = pos.get("trigger", {})
    L = ["", "① 我的仓位 " + "─" * 32]
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
        L.append(f"  {p['code']} {r['name']}   {sh}股 @{cost:.4f}")
        L.append(f"  现价 {px:.3f}   市值 {mv:,.0f}   浮亏 {mv - total:+,.0f}（{(mv - total) / total * 100:+.2f}%）")
        L.append(f"  ├ 净值资产 {navval:,.0f} ＋ 溢率空气 {air:,.0f}"
                 f"（占市值 {air / mv * 100:.1f}%；溢率每降1pct 亏 {navval * 0.01:,.0f}元）")
        L.append(f"  ├ 回本 {cost:.4f} = 溢率须到 {(cost / nav - 1) * 100:+.2f}%（纳指不动就回不来）")
        a, w = tg.get("add_below_prem"), tg.get("watch_above_prem")
        if a is not None:
            pa = nav * (1 + a / 100)
            L.append(f"  └ 加仓线 溢率<{a:.0f}% → {pa:.3f}（现价 {(pa / px - 1) * 100:+.1f}%）")
        if w is not None and prem >= w:
            L.append(f"  ⚠ 溢率 {prem:.2f}% 已触警戒线 {w:.0f}%")
    return L



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
    force = bool(os.environ.get("ETF_FORCE"))   # 试跑：跳过去重且不回写 sent

    # 今日已推送 → 静默退出（供 10:32 兜底任务去重）
    if rstate.get("sent") == today.isoformat() and not force:
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
    fx = fetch_fx_closes()
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
            est, ref, ndx_ret, fx_ret = correct_nav(pr["nav_date"], pr["nav"], ndx, fx)
            if est and ref != pr["nav_date"]:
                r["nav_est"], r["est_ref"] = est, ref
                r["ndx_ret"], r["fx_ret"] = ndx_ret, fx_ret
                r["prem_est"] = (price / est - 1) * 100
        else:
            errors.append(f"{c}净值")
        r["prem_use"] = r["prem_est"] if r.get("prem_est") is not None else r.get("prem")
        rows[c] = r

    log_premiums(rows, pool)
    trading_today = any(q["ts"].date() == today for q in quotes.values())
    pool_ok = sorted((rows[c] for c in pool if rows[c]["prem_use"] is not None), key=lambda r: r["prem_use"])
    best = pool_ok[0] if pool_ok else None

    # ── 输出：结论 → ①②③ → 附录（先给动作，再给依据，数据沉到底部） ──
    base, cap = cfg["monthly_base_amount"], cfg["backlog_cap"]
    backlog = state.get("backlog", 0)
    prem_use = best["prem_use"] if best else None
    st = premium_stats(prem_use)
    if best:
        tier = pick_tier(prem_use, cfg["premium_tiers"])
        amount, new_backlog = plan_amount(tier, base, backlog, cap)
        dca_now = is_dca_day(today, trading_today, cfg["dca_day"], state)
    else:
        tier, amount, new_backlog, dca_now = None, 0, backlog, False
    trig = (_load(POS_PATH, {}) or {}).get("trigger", {})

    L = ["", "=" * 48, f"  📊 纳指100 ETF 日报 · {now:%m-%d %H:%M} {WEEKDAY_CN[today.weekday()]}"]
    if not trading_today:
        L.append("  · 休市，价格为最近收盘")
    if rstate.get("defer") == today.isoformat() and not force:
        L.append(f"  ⏸ {rstate.get('defer_reason', '开盘延迟')} → 以下为复牌价")
    L.append("=" * 48)
    if errors:
        L.append(f"  ⚠ 数据获取失败：{'、'.join(dict.fromkeys(errors))}")

    # ── 结论：今天做什么 ──
    L.append("")
    if not best:
        L.append("  ▎结论：决策池溢率数据缺失，今日不给金额（见附录错误项）")
    else:
        if dca_now:
            L.append(f"  ▎结论：今天是定投日 → 买 {amount} 元 {best['code']}")
        else:
            L.append(f"  ▎结论：今天不动（下次定投 {next_dca_label(today, cfg['dca_day'], state)}，{amount} 元）")
        head = f"    溢率 {best['prem_use']:+.2f}%"
        if st:
            head += f" · 历史 P{st['pctile']:.0f}（中位 {st['median']:+.1f}%）"
        L.append(head)
        navb = best.get("nav_est") or best["nav"]
        a = trig.get("add_below_prem")
        if a is not None:
            pa = navb * (1 + a / 100)
            gap = (pa / best["price"] - 1) * 100
            tail = "已到加仓价" if gap >= 0 else f"现价还需 {gap:+.1f}%"
            L.append(f"    加仓线 溢率<{a:.0f}% → {pa:.3f}（{tail}）")
        if amount > 0:
            cm = commission(amount, cfg)
            tail = "；只做月投勿拆周" if (dca_now and not cfg["commission"]["free_of_min"]) else ""
            L.append(f"    月投固定 {base} 元（佣金 {cm:.0f} 元={cm / amount * 100:.2f}%{tail}）")
            L.append("    溢率不改金额，只改入场价（长期定投摊平）")
        if backlog:
            L.append(f"    积压资金 {backlog} 元（上限 {cap}）")

    # ── ① 我的仓位 ──
    L += render_position(rows)

    # ── ② 溢率贵不贵 ──
    if best:
        L += ["", "② 溢率贵不贵 " + "─" * 30,
              f"  决策口径 {prem_use:+.2f}%    ← 下单看这个"]
        if best.get("nav_est"):
            diff = prem_use - best["prem"]
            tail = "可忽略" if abs(diff) < 0.2 else ("指数隔夜跌→低估，涨→高估" if best["ndx_ret"] < 0 else "指数隔夜涨→高估")
            L.append(f"  券商口径 {best['prem']:+.2f}%    ← 券商App显示，差 {diff:+.2f}pct（{tail}）")
        else:
            L.append("  券商口径 同上（净值已最新）")
        if st:
            L.append(f"  历史 {st['n']} 天：中位 {st['median']:+.1f}% / P95 {st['p95']:+.1f}% / 今天 P{st['pctile']:.0f}")
            L.append(f"  走势 {st['trend']}")
            if st["streak"] >= 3:
                L.append(f"  连续 {st['streak']} 个交易日溢率 ≥8%（位置极端）")
        if best.get("nav_est"):
            L.append(f"  折算 {best['nav']:.4f}({best['nav_date'][5:]}) × 纳指 {best['ndx_ret'] * 100:+.2f}%"
                     f" × 汇率 {best['fx_ret'] * 100:+.2f}% = {best['nav_est']:.4f}")

    # ── ③ 有没有更便宜的通道 ──
    if pool_ok:
        L += ["", "③ 有没有更便宜的通道 " + "─" * 22]
        parts = []
        for r in pool_ok:
            mark = "*" if r.get("prem_est") is not None else ""
            parts.append(f"{r['code']} {r['prem_use']:+.1f}%{mark}" + (" ←最低" if r is best else ""))
        L.append("  场内 " + "｜".join(parts))
        if any(r.get("prem_est") is not None for r in pool_ok):
            L.append("       * 已折算到最新美股收盘（纳指+汇率）")
        otc = cfg.get("otc") or {"code": "016055", "name": "博时纳指100联接A"}  # config 未同步时取默认
        if otc.get("code"):
            s = fetch_sub_status(otc["code"])
            if s:
                bad = ("暂停" in s or "限大额" in s)
                L.append(f"  场外 {otc['code']} {otc.get('name', '')}：{s}" + ("  ← 便宜通道是关的" if bad else "  ← 0% 溢率，更便宜"))

    # 监视提示
    wa = cfg["watch_alert"]
    alerts = [rows[c] for c in watch
              if rows[c]["prem_use"] is not None and best
              and (rows[c].get("avg_turnover") or 0) >= wa["min_avg_turnover_yi"]
              and rows[c]["prem_use"] <= best["prem_use"] - wa["premium_gap_pct"]]
    for r in alerts:
        L.append(f"  🔍 {r['code']} {r['name']} 溢率 {r['prem_use']:+.2f}%（比 {best['code']} 低 "
                 f"{best['prem_use'] - r['prem_use']:.2f}pct，日均 {r['avg_turnover']:.2f}亿），可考虑调入决策池")
    for s in fee_changes:
        L.append(f"  ⚠ {s}")

    # ── 附录：数据（结论不依赖它，缺了不影响上面） ──
    L += ["", "附录 " + "─" * 40]
    pe, mg = fetch_ndx_pe(), fetch_marketgrep()
    if pe and pe.get("f"):
        L.append(f"  估值 NDX PE Tr {pe['t']} / Fwd {pe['f']}")
    if mg:
        L.append(f"  温度 {mg}")
    if best:
        ref = f"，折算基准 {best['est_ref'][5:]} 收盘" if best.get("est_ref") else ""
        L.append(f"  数据 实时价 {best['price_date'][5:]} {best['price']:.3f}｜官方净值 {best['nav_date'][5:]}"
                 f"（滞后 {best['lag']} 日）{ref}")
    L += etf_signals.render_sections(cfg, best, header=False)

    # 定投日写状态
    if dca_now and best:
        state["backlog"] = new_backlog
        state["last_dca_month"] = today.strftime("%Y-%m")
        state.setdefault("history", []).append({
            "date": today.isoformat(), "code": best["code"], "premium": round(best["prem_use"], 2),
            "tier": tier["label"], "amount": amount, "backlog_after": new_backlog})
        _save(STATE_PATH, state)

    L += ["=" * 48, ""]
    if not force:
        _save(RUN_STATE, {**rstate, "sent": today.isoformat()})
    print("\n".join(L))


if __name__ == "__main__":
    main()
