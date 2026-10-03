"""纳指 100 场内 ETF 定投日报（多标的比价 + 溢价档位定额）

溢价口径：收盘价(T) ÷ 官方净值(T 的前一个 A 股交易日) − 1。
QDII 净值按美股收盘计价，A 股 T 日收盘时可知的最新美股信息是美股 T-1 收盘，
故 T 日价格应与 T-1 净值配对（与券商 App / 腾讯行情显示的溢价率同口径）。
该净值未公布时退用更早净值，并标注滞后交易日数。
"""
import sys, json, re, datetime, urllib.request
from pathlib import Path

import etf_signals

HERE        = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "dca_config.json"
STATE_PATH  = HERE / "dca_state.json"
FEE_CACHE   = HERE / "fee_cache.json"
PREM_LOG    = HERE / "premium_log.json"

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


# ── 溢价计算 ──────────────────────────────────────────────

def price_basis(q, cal, now):
    """确定用于溢价的价格及其日期。
    盘中(≥09:30)用实时价；集合竞价/盘前用昨收；休市用最近收盘。"""
    ts = q["ts"]
    if ts.date() == now.date():
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
    """按价格日期记录决策池溢价，供周报回顾。{price_date: {code: prem}}，保留 120 条"""
    log = _load(PREM_LOG, {})
    for c in codes:
        r = rows.get(c, {})
        if r.get("prem") is not None and r.get("price_date"):
            log.setdefault(r["price_date"], {})[c] = round(r["prem"], 2)
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

    try:
        quotes = fetch_quotes(pool + watch)
    except Exception as e:
        quotes = {}
        errors.append(f"行情({type(e).__name__})")

    cal = []
    try:
        cal = [r[0] for r in fetch_kline(pool[0], 60)]
    except Exception as e:
        errors.append(f"交易日历({type(e).__name__})")

    fees, fee_changes, fee_failed = get_fees(pool + watch, cfg["fee_refresh_days"])
    if fee_failed:
        errors.append("费率:" + ",".join(fee_failed))

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
        else:
            errors.append(f"{c}净值")
        rows[c] = r

    log_premiums(rows, pool)
    trading_today = any(q["ts"].date() == today for q in quotes.values())
    pool_ok = sorted((rows[c] for c in pool if rows[c]["prem"] is not None), key=lambda r: r["prem"])
    best = pool_ok[0] if pool_ok else None

    # ── 输出 ──
    L = ["", "=" * 48, "  📊 纳指 100 场内 ETF 定投日报",
         f"  📅 {now:%m-%d %H:%M}（{WEEKDAY_CN[today.weekday()]}{'' if trading_today else ' · 休市'}）",
         "=" * 48]
    if errors:
        L.append(f"  ⚠ 部分数据获取失败：{'、'.join(dict.fromkeys(errors))}")

    L += ["", "【标的比价】决策池，按溢价升序"]
    for r in pool_ok + [rows[c] for c in pool if rows[c]["prem"] is None]:
        fee = f"{r['fee']:.2f}%" if r["fee"] is not None else "费率缺失"
        tv  = f"{r['avg_turnover']:.2f}亿" if r.get("avg_turnover") else "成交缺失"
        if r["prem"] is None:
            L.append(f"  {r['code']} {r['name']}  数据缺失")
            continue
        tag = "  ← 最低" if r is best else ""
        L.append(f"  {r['code']} {r['name']}  价 {r['price']:.3f}  溢价 {r['prem']:+.2f}%  "
                 f"费率 {fee}  日均 {tv}{tag}")

    if best:
        L += ["", "【溢价口径】收盘价(T) ÷ 官方净值(T 前一交易日)",
              f"  {best['code']}：{best['price_label']} {best['price_date']} {best['price']:.3f}"
              f" ÷ 净值 {best['nav_date']} {best['nav']:.4f}"]
        lagged = [r["code"] for r in pool_ok if r["lag"] > 0]
        if lagged:
            L.append(f"  ⚠ {','.join(lagged)} 净值滞后 {max(r['lag'] for r in pool_ok)} 个交易日，"
                     "溢价含未计入的指数涨跌，仅供参考")

    # 监视池提示
    wa = cfg["watch_alert"]
    alerts = [rows[c] for c in watch
              if rows[c]["prem"] is not None and best
              and (rows[c].get("avg_turnover") or 0) >= wa["min_avg_turnover_yi"]
              and rows[c]["prem"] <= best["prem"] - wa["premium_gap_pct"]]
    if alerts or fee_changes:
        L += ["", "【监视提示】"]
        for r in alerts:
            L.append(f"  {r['code']} {r['name']} 溢价 {r['prem']:+.2f}%（比 {best['code']} 低 "
                     f"{best['prem'] - r['prem']:.2f}pct，日均 {r['avg_turnover']:.2f}亿），可考虑调入决策池")
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
        tier = pick_tier(best["prem"], cfg["premium_tiers"])
        amount, new_backlog = plan_amount(tier, base, backlog, cap)
        dca_now = is_dca_day(today, trading_today, cfg["dca_day"], state)
        head = "今日定投" if dca_now else f"按当前溢价预估（下次定投：{next_dca_label(today, cfg['dca_day'], state)}）"
        L.append(f"  ★ {head}：{amount} 元（{tier['label']}）")
        if amount > 0:
            L.append(f"  ★ 标的：{best['code']} {best['name']}（溢价 {best['prem']:+.2f}%，决策池最低）")
        L.append(f"  ★ 依据：溢价 {best['prem']:.2f}%（{best['price_date']} 价 ÷ {best['nav_date']} 净值）")
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
                "date": today.isoformat(), "code": best["code"], "premium": round(best["prem"], 2),
                "tier": tier["label"], "amount": amount, "backlog_after": new_backlog})
            _save(STATE_PATH, state)

    # 纳指择时信号：QQQ MA200 止盈 + 回撤加仓档位（独立于上面的月度定投）
    L += etf_signals.render_sections(cfg, best)

    L += ["=" * 48, ""]
    print("\n".join(L))


if __name__ == "__main__":
    main()
