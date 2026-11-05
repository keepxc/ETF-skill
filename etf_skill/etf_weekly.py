"""
纳指 ETF 周报（五段制，每周日 21:00）— ①纳指市场状态 ②ETF价格与溢价 ③汇率与净值拆解
④持仓与定投 ⑤综合判断；Mag7 AI 龙头估值收附录。
估值类数据只作背景参考，定投金额恒定，溢价只影响入场价。
"""
import sys, json, datetime, urllib.request
from pathlib import Path

import etf_daily as daily

HERE = Path(__file__).resolve().parent
BASE = "https://historyofmarket.com/api"
URLS = {
    "pe":        f"{BASE}/ndx/forward-pe.json",
    "rolling5y": f"{BASE}/ndx/rolling5y.json",
    "vxn":       f"{BASE}/ndx/vxn.json",
    "drawdowns": f"{BASE}/ndx/drawdowns.json",
    "ai_val":    f"{BASE}/mag7/ai-valuation.json",
    "ndx_price": f"{BASE}/ndx/price.json",
}
CN_NAME = {"NVDA": "英伟达", "MSFT": "微软", "META": "Meta", "GOOGL": "谷歌",
           "AAPL": "苹果", "AMZN": "亚马逊", "TSLA": "特斯拉",
           "CSCO": "思科", "ORCL": "甲骨文", "SUNW": "Sun", "JAVA": "Sun"}


def _get(url):
    h = {"User-Agent": "Mozilla/5.0"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


# ── 数据源健康（防「返回成功 ≠ 数据有效」：成功但数据陈旧必须显式标出） ──

_SOURCE_HEALTH = []  # 进程内累积（本脚本单次运行即退出，无需重建）


def _fetch(name, fn, stale_days=7):
    """带健康记录的取数：成功也检查数据新鲜度。返回 fn() 结果或 None。
    health 记录：name / ok / 数据截止日 / 条数 / 是否过期（数据日距今 > stale_days 天）。"""
    try:
        data = fn()
        ok = bool(data)
    except Exception:
        data, ok = None, False
    last, n, stale = None, None, False
    if ok:
        if isinstance(data, dict) and isinstance(data.get("date"), str):
            # 单对象带 date 字段（如 get_ndx_price 的 {close, date, dd, ...}）
            last, n = data["date"], 1
        elif isinstance(data, dict) and data:
            # 序列型 dict：{date: value} 或 {date: {...}}
            keys = [k for k in data.keys() if isinstance(k, str) and len(k) == 10 and k[4] == "-"]
            last = max(keys) if keys else None
            n = len(data)
        elif isinstance(data, (list, tuple)):
            n = len(data)
            for x in reversed(data):
                if isinstance(x, dict) and isinstance(x.get("date"), str):
                    last = x["date"]
                    break
    if last:
        try:
            stale = (datetime.date.today() -
                     datetime.date.fromisoformat(last[:10])).days > stale_days
        except ValueError:
            pass
    _SOURCE_HEALTH.append({"name": name, "ok": ok, "last": last, "n": n,
                           "stale": stale, "stale_days": stale_days})
    return data if ok else None


def source_health_lines():
    if not _SOURCE_HEALTH:
        return None
    L = []
    for h in _SOURCE_HEALTH:
        if not h["ok"]:
            L.append(f"  ✗ {h['name']}：请求失败/空响应")
        elif h["last"] is None:
            L.append(f"  ✓ {h['name']}：成功（{h['n']} 条，无日期戳——新鲜度无法核验）")
        elif h["stale"]:
            L.append(f"  ⚠ {h['name']}：响应成功但数据截至 {h['last']}"
                     f"（>{h['stale_days']}天前）——已按旧数据对待，勿当最新")
        else:
            L.append(f"  ✓ {h['name']}：数据截至 {h['last']}（{h['n']} 条）")
    return L


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def pct_rank(values, x):
    """x 在历史序列中的百分位（≤x 的占比）"""
    return round(sum(1 for v in values if v <= x) / len(values) * 100) if values else None


def _median(values):
    s = sorted(values)
    n = len(s)
    return (s[n // 2] + s[(n - 1) // 2]) / 2 if n else None


# ── 数据获取 ────────────────────────────────────────────────

def get_pe():
    """预期 PE。⚠ terminal 的 weekly `forward` 序列在 2026-08-05 后断更，
    之后由 `forwardOwn`（自算 blended-fy1fy2，日频）接管；两段在重叠日几乎相同
    （22.41 vs 22.37），可直接拼接。**`current.forward` 是断更那天的旧值，不能用**——
    2026-11-02 实测：用它得 22.37/P59「中性」，真实 forwardOwn 是 19.48/P40「便宜」。"""
    d = _get(URLS["pe"])
    fwd, own = d.get("forward", []) or [], d.get("forwardOwn", []) or []
    cut = str(fwd[-1]["date"]) if fwd else ""
    rows = fwd + [x for x in own if str(x.get("date", "")) > cut]
    hist = [x["value"] for x in rows if x.get("value") is not None]
    if not hist:
        return None
    cur = hist[-1]
    return {"trailing": d.get("current", {}).get("trailing"), "forward": cur,
            "fwd_pct": pct_rank(hist, cur), "fwd_med": _median(hist),
            "fwd_since": d.get("historyStarts", {}).get("forward", "")[:4],
            "fwd_asof": str(rows[-1].get("date", ""))}


def get_series_stat(key):
    d = _get(URLS[key])
    s = [x for x in d.get("series", []) if x.get("value") is not None]
    if not s:
        return None
    vals = [x["value"] for x in s]
    return {"latest": vals[-1], "date": s[-1]["date"], "pct": pct_rank(vals, vals[-1]),
            "med": _median(vals), "min": min(vals), "max": max(vals),
            "since": s[0]["date"][:4], "neg_pct": d.get("negativePercent")}


def get_drawdowns(n=5):
    dds = _get(URLS["drawdowns"]).get("drawdowns", [])
    top = sorted(dds, key=lambda x: x.get("decline", 0))[:n]
    return [(x.get("period", ""), abs(x["decline"]) * 100, x.get("recovery_days")) for x in top]


def get_ndx_price():
    s = _get(URLS["ndx_price"]).get("series", [])
    if not s:
        return None
    lat = s[-1]
    peak = max(s, key=lambda x: x["close"])
    # 周涨跌：最后一个交易日 vs 5 个交易日前（约一周）
    wk_ret = (lat["close"] / s[-6]["close"] - 1) * 100 if len(s) >= 6 else None
    return {"close": lat["close"], "date": lat["date"], "dd": lat["drawdown"] * 100,
            "peak": peak["close"], "peak_date": peak["date"], "wk_ret": wk_ret}


def get_ai_val():
    """AI 龙头：预期 PE + 隐含盈利增速（trailing/fwd 之比 = 市场定价的 EPS 增长）。"""
    d = _get(URLS["ai_val"])
    cur = []
    for m in d.get("members", []):
        snap = m.get("snapshot", {})
        fp, tp = snap.get("forwardPE"), snap.get("trailingPE")
        if not fp:
            continue
        growth = (tp / fp - 1) * 100 if tp and fp else None
        cur.append({"t": m["ticker"], "fp": round(fp, 1),
                    "g": round(growth) if growth is not None else None})
    ref = [(r["ticker"], r["name"], r["peakForwardPE"], r.get("peakDate", "")) for r in d.get("reference_1999", [])]
    return {"cur": cur, "ref": ref}


# ── 定投执行回顾 ─────────────────────────────────────────────

def next_dca_date(today, dca_day, state):
    """下一个名义定投日（不含休市顺延）"""
    if state.get("last_dca_month") != today.strftime("%Y-%m"):
        if today.day <= dca_day:
            return datetime.date(today.year, today.month, dca_day)
        return None  # 本月逾期未执行，日报会在下一个交易日触发
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return datetime.date(y, m, dca_day)


def dca_review(today, heading=True):
    cfg = daily._load(daily.CONFIG_PATH, None)
    state = daily._load(daily.STATE_PATH, {"backlog": 0, "last_dca_month": None, "history": []})
    log = daily._load(daily.PREM_LOG, {})
    L = ["", "④ 本周执行 " + "─" * 14] if heading else []

    t = today.isoformat()
    lo = (today - datetime.timedelta(days=7)).isoformat()
    this_wk = {d: v for d, v in log.items() if lo < d <= t}
    if this_wk:
        # 只给区间，不点名标的、不下「谁更便宜」的结论：本节的快照是当天某一次记录，
        # 与 ② 的实时价不同时点，两者给出相反结论会让整份报告自相矛盾。
        vals = [x for snap in this_wk.values() for x in snap.values()]
        L.append(f"  溢价 本周区间 {min(vals):.1f}~{max(vals):.1f}%（每日快照；当前值见 ②）")

    nd = next_dca_date(today, cfg["dca_day"], state)
    due = f"{nd:%m-%d}（{(nd - today).days} 天后）" if nd else "本月已过且未执行 → 下一个交易日"
    L.append(f"  定投 下次 {due} · {cfg['monthly_base_amount']} 元 · 积压 {state.get('backlog', 0)} 元")
    hist = state.get("history", [])
    if hist:
        h = hist[-1]
        L.append(f"  上次 {h['date'][5:]} {h['amount']} 元 @溢率 {h['premium']}%")
    sig = (cfg.get("signals") or {})
    trg = _load_trigger()
    if sig.get("show_levels"):
        L.append(f"  加仓 溢率<{trg or 5}% + 回撤档位（-8% 起）两条都有效")
    else:
        L.append(f"  加仓 仅「溢率<{trg or 5}%」有效；回撤档位未启用")
    return L


def _load_trigger():
    pos = daily._load(daily.POS_PATH, None) or {}
    return (pos.get("trigger") or {}).get("add_below_prem")


# ── 五段制新增：ETF 溢价块 + 汇率/净值拆解 ────────────────

def etf_premium_block(today):
    """② ETF 价格与溢价：决策池溢价 + 历史百分位 + 近一周变化 + 横向比价。
    返回 dict（lines/extreme/cheapest/cheapest_prem/cheapest_stats，供⑤复用）或 None。
    溢价百分位判读用溢价专用措辞：低溢价 = 定投友好（不是"便宜"——那是估值概念，见①）。"""
    cfg = daily._load(daily.CONFIG_PATH, None) or {}
    pool = cfg.get("pool", [])
    quotes = _safe(lambda: daily.fetch_quotes(pool))
    cal = _safe(lambda: [r[0] for r in daily.fetch_kline(pool[0], 60)]) or []
    ndx = _safe(daily.fetch_ndx_closes) or {}
    fx = _safe(daily.fetch_fx_closes) or {}
    rows = {}
    for c in pool:
        q = (quotes or {}).get(c)
        if not q:
            continue
        price, pdate, _ = daily.price_basis(q, cal, daily.datetime.datetime.now())
        try:
            pr = daily.calc_premium(price, pdate, daily.fetch_navs(c), cal)
        except Exception:
            pr = None
        if not pr:
            continue
        est, ref, _, _ = daily.correct_nav(pr["nav_date"], pr["nav"], ndx, fx)
        prem = (price / est - 1) * 100 if (est and ref != pr["nav_date"]) else pr["prem"]
        rows[c] = {"prem": prem, "price": price, "name": q["name"]}
    if not rows:
        return None
    L = []
    extreme = False
    stats_by_code = {}
    for c, r in sorted(rows.items(), key=lambda x: x[1]["prem"]):
        st = _safe(lambda: daily.premium_stats(r["prem"], code=c, cur_date=today.isoformat()))
        stats_by_code[c] = st
        extra = ""
        if st:
            p = st["pctile"]
            verdict = ("溢价低位·定投友好" if p < 15 else
                       "中性" if p < 70 else "溢价偏高" if p < 85 else "溢价极端区")
            extra = f" P{p:.0f}（{verdict}）"
            extreme = extreme or p >= 85
            if st.get("delta") is not None:
                extra += f" · 较上日 {st['delta']:+.1f}pct"
        L.append(f"  {c} {r['name']} 溢价 {r['prem']:+.1f}%{extra}")
    cheapest = min(rows, key=lambda c: rows[c]["prem"])
    L.append(f"  判读 决策池最低溢价 = {cheapest}（定投按它执行）"
             if len(rows) > 1 else "  判读 单标的池，无切换选项")
    return {"lines": L, "extreme": extreme, "cheapest": cheapest,
            "cheapest_prem": rows[cheapest]["prem"],
            "cheapest_stats": stats_by_code.get(cheapest)}


def fx_nav_block():
    """③ 汇率与净值：近一周 纳指涨跌 vs USD/CNY 各贡献多少（防止把汇率误判为指数表现）。
    口径（三件事说清）：
    - 指标是 USD/CNY（1 美元兑多少人民币）：上涨 = 美元升值 = 净值增厚（正向）。
    - 时间区间：美股交易日收盘至收盘，指数与汇率取同一区间（日期对齐，缺失即弃）。
    - 这是「同期指数表现」，不是已公布净值变动——QDII 净值估值日滞后 1~2 日，
      不能拿 11-04 的指数直接对 11-03 的净值。
    - 拆解用乘法：(1+指数收益)×(1+汇率收益)−1（复利口径，与净值折算公式一致），
      且是近似估算：未含管理/托管费、跟踪误差、申赎摩擦。"""
    ndx = _fetch("指数日线(腾讯)", daily.fetch_ndx_closes) or {}
    fx = _fetch("USD/CNY日线(新浪)", daily.fetch_fx_closes) or {}
    if len(ndx) < 6:
        return None
    dates = sorted(ndx)[-6:]
    ndx_ret = (ndx[dates[-1]] / ndx[dates[0]] - 1) * 100
    L = [f"  纳指100 近一周 {ndx_ret:+.2f}%（美股收盘 {dates[0]} → {dates[-1]}，腾讯日线）"]
    if fx and dates[0] in fx and dates[-1] in fx:
        fx_ret = (fx[dates[-1]] / fx[dates[0]] - 1) * 100
        direction = "美元升值 → 人民币净值增厚（正向）" if fx_ret > 0 else \
                    "美元贬值 → 人民币净值减记（负向）"
        comb = ((1 + ndx_ret / 100) * (1 + fx_ret / 100) - 1) * 100
        L.append(f"  USD/CNY 近一周 {fx_ret:+.2f}%（{direction}）")
        L.append(f"  近似拆解 同期净值表现 ≈ (1{ndx_ret:+.2f}%)×(1{fx_ret:+.2f}%)−1 = {comb:+.2f}%"
                 "（乘法口径；未含费用/跟踪误差；指数与汇率同期对齐，非已公布净值变动）")
        L.append("  注意 QDII 估值日滞后：T 日场内价对应的是 T-1 美股收盘的净值，别拿昨夜指数骂今天净值")
    return L


def _premium_week_ago(code, today):
    """上周溢价：premium_log.json（per-code 修正口径，日报每日写入）取 5~9 天前最近值；
    history_premium.csv 仅 code=513300 时可用（它是 513300 的全史溢率，对其他标的是错口径）。
    返回 (date, prem) 或 None——数据不足如实返回 None，不拿别的标的/上日冒充上周。"""
    vals = {}
    if code == "513300":
        try:
            with daily.PREM_HIST.open(encoding="utf-8") as f:
                import csv as _csv
                for row in _csv.reader(f):
                    if row and len(row) >= 4 and row[0][:4].isdigit():
                        try:
                            vals[row[0]] = float(row[3])
                        except ValueError:
                            continue
        except OSError:
            pass
    for d, mp in (daily._load(daily.PREM_LOG, {}) or {}).items():
        if isinstance(mp, dict) and mp.get(code) is not None:
            vals[d] = mp[code]
    import datetime as _dt
    lo = (today - _dt.timedelta(days=9)).isoformat()
    hi = (today - _dt.timedelta(days=5)).isoformat()
    win = sorted((d, v) for d, v in vals.items() if lo <= d <= hi)
    return win[-1] if win else None


def position_block():
    """④ 持仓：市值/浮动盈亏（不展示回本溢价——成本是历史结果，不构成决策依据）。
    三态：有持仓 / 明确无持仓（文件存在且为空）/ 数据不可用（缺失或解析失败）。
    另做交叉一致性：position 有持仓但 dca_state 无任何执行记录 → 提示不一致。
    持仓文件只由人工维护（系统只读不写），空账本永远不会被自动初始化为零持仓。"""
    if not daily.POS_PATH.exists():
        return ["  ⚠ 持仓数据不可用（position.json 不存在）——若应有持仓，这是数据异常，"
                "先核查文件，不要按无持仓做任何判断"]
    pos = daily._load(daily.POS_PATH, None)
    if pos is None:
        return ["  ⚠ 持仓数据不可用（position.json 读取/解析失败）——同上，先核查"]
    if not pos.get("positions"):
        return ["  无持仓记录（文件存在且为空）· 定投计划：每月15日执行，金额恒定"]
    # 交叉一致性：持仓存在但定投历史为空 → 数据不一致（两文件之一有问题）
    state = daily._load(daily.STATE_PATH, None)
    hist = (state or {}).get("history") or []
    L = []
    if not hist:
        L.append("  ⚠ 数据不一致：position.json 有持仓但 dca_state 无任何定投记录——"
                 "两文件至少一个不完整，累计投入口径暂不可信")
    cfg = daily._load(daily.CONFIG_PATH, None) or {}
    try:
        codes = [p["code"] for p in pos["positions"]]
        quotes = daily.fetch_quotes(codes)
    except Exception:
        quotes = {}
    mv = cost = 0.0
    for p in pos["positions"]:
        q = quotes.get(p["code"])
        cost += p["shares"] * p["cost"]
        if q and q.get("price"):
            mv += p["shares"] * q["price"]
    L.append(f"  市值 {mv:,.0f} · 成本 {cost:,.0f} · 浮动 {mv - cost:+,.0f}（{(mv - cost) / cost * 100:+.1f}%）"
             if mv else "  持仓有记录但行情取不到，市值跳过")
    L += _safe(lambda: dca_review(datetime.date.today(), heading=False)) or []
    return L




def bar(pct, width=12):
    """百分位 → 横条（left = 低，right = 高）"""
    f = int(max(0.0, min(1.0, pct / 100)) * width)
    return "█" * f + "░" * (width - f)


def verdict_valu(p):
    return "便宜" if p < 30 else "中性" if p < 70 else "偏贵" if p < 85 else "极端贵"


def verdict_return(p):
    return "低于常态" if p < 50 else "常态" if p < 70 else "高于常态"


def verdict_vxn(p):
    return "平静" if p < 30 else "正常" if p < 70 else "偏恐慌" if p < 85 else "恐慌"


# ── 主流程 ────────────────────────────────────────────────

def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    today = datetime.date.today()
    pe  = _fetch("NDX前瞻PE(historyofmarket)", get_pe)
    r5  = _fetch("滚动5年(historyofmarket)", lambda: get_series_stat("rolling5y"))
    vxn = _fetch("VXN(historyofmarket)", lambda: get_series_stat("vxn"))
    dd  = _fetch("历史回撤(historyofmarket)", get_drawdowns)
    ndx = _fetch("指数价格(historyofmarket)", get_ndx_price)
    ai  = _fetch("AI龙头估值(historyofmarket)", get_ai_val)
    failed = [n for n, v in [("市盈率", pe), ("滚动收益", r5), ("波动率", vxn),
                             ("历史回撤", dd), ("指数价格", ndx), ("AI估值", ai)] if not v]

    wk = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]
    L = [f"📊 纳指ETF 周报 · {today:%m-%d} {wk}"]
    if failed:
        L.append(f"  ⚠ 数据缺口：{'、'.join(failed)}"
                 "（仅指 historyofmarket 源不可用；③的指数/汇率走腾讯/新浪独立源，不受此影响）")
    L.append("")

    # ── ① 纳指市场状态：指数表现、回撤、波动、估值（各自的数，不合并成一句"贵不贵"） ──
    L.append("① 纳指市场状态 " + "─" * 14)
    if ndx:
        wr = f"，本周 {ndx['wk_ret']:+.1f}%" if ndx.get("wk_ret") is not None else ""
        L.append(f"  指数 纳指100 {ndx['close']:,.0f}{wr}，距历史高点 {ndx['dd']:+.1f}%"
                 f"（高点 {ndx['peak_date'][:4]} 年；历史常态回撤 -28~-40%）")
    if pe and pe.get("forward"):
        asof = f"，截至 {pe.get('fwd_asof', '?')}" if pe.get("fwd_asof") else ""
        L.append(f"  估值 预期PE {pe['forward']}  {bar(pe['fwd_pct'] or 0)} P{pe['fwd_pct']}"
                 f"（中位 {pe['fwd_med']:.1f}） {verdict_valu(pe['fwd_pct'] or 0)}"
                 f"（P 值参照该指标自身历史分布{asof}）")
    if vxn:
        L.append(f"  波动 VXN {vxn['latest']:.1f}  {bar(vxn['pct'] or 0)} P{vxn['pct']} {verdict_vxn(vxn['pct'] or 0)}")
    if r5:
        L.append(f"  回报 历史滚动5年年化 {r5['latest']:+.1f}%，处该序列 P{r5['pct']}"
                 f"（{verdict_return(r5['pct'] or 0)}；P 值参照滚动样本自身分布）"
                 + (f" · 滚动5年样本中收益为负的占比 {r5['neg_pct']}%（历史频率，非未来概率）"
                    if r5.get('neg_pct') is not None else ""))
    if not any([ndx, pe and pe.get("forward"), vxn, r5]):
        L.append("  （① 各项数据全部不可用——本节无结论，不硬凑）")
    L.append("  注 指数估值/回撤是指数自身的数，与场内 ETF 溢价（见②）不是一回事")

    # ── ② ETF 价格与溢价 ──
    prem_blk = _safe(lambda: etf_premium_block(today))
    prem_lines = prem_blk["lines"] if prem_blk else None
    prem_extreme = prem_blk["extreme"] if prem_blk else False
    L += ["", "② ETF 价格与溢价 " + "─" * 14]
    L += prem_lines or ["  溢价数据取不到（净值/行情失败）——不硬凑"]

    # ── ③ 汇率与净值拆解 ──
    L += ["", "③ 汇率与净值 " + "─" * 14]
    L += _safe(fx_nav_block) or ["  拆解数据不足，跳过（不硬凑）"]

    # ── ④ 持仓与定投 ──
    L += ["", "④ 持仓与定投 " + "─" * 14]
    L += _safe(position_block) or ["  ⚠ 持仓模块异常（函数失败）——数据可用性需核查，不硬凑"]

    # ── ⑤ 综合判断：指数状态 / 溢价状态 / 定投状态（三句话整合前四节） ──
    L += ["", "⑤ 综合判断 " + "─" * 14]
    risks, notes = [], []
    # 指数状态
    if ndx and ndx.get("dd") is not None:
        d = ndx["dd"]
        zone = ("回撤轻微（<10%）" if d > -10 else
                "中等回撤（-10~-20%）" if d > -20 else
                "深回撤（-20~-40%，历史常态区）" if d > -40 else
                "极端回撤（>-40%，历史仅 2000 年）")
        L.append(f"  指数 距历史高点 {d:+.1f}% → {zone}")
    else:
        L.append("  指数 状态数据缺口（historyofmarket 源不可用）——不硬凑")
    # 溢价状态（当前 / 上周 / 周变化 / 历史百分位——溢率只改入场价，不改投入金额）
    if prem_blk:
        st = prem_blk["cheapest_stats"]
        code_c = prem_blk["cheapest"]
        seg = f"当前 {prem_blk['cheapest_prem']:+.1f}%"
        if st:
            seg += f" · 历史百分位 P{st['pctile']:.0f}"
        wa = _safe(lambda: _premium_week_ago(code_c, today))
        if wa:
            d_week = prem_blk["cheapest_prem"] - wa[1]
            seg += f" · 上周 {wa[1]:+.1f}%（{wa[0]}），周变化 {d_week:+.1f}pct（{'扩大' if d_week > 0 else '回落'})"
        else:
            seg += " · 上周溢价数据不足，周变化无法核实（不拿上日冒充上周）"
        if st and st.get("trend"):
            seg += f" · 轨迹 {st['trend']}"
        L.append(f"  溢价 {code_c} {seg}")
        if prem_extreme:
            risks.append("溢价进历史极端区（②）")
    else:
        L.append("  溢价 数据缺口——方向（扩大/收缩）无法判断，不硬凑")
    # 定投状态
    cfg_v = daily._load(daily.CONFIG_PATH, None) or {}
    if prem_blk and cfg_v.get("premium_tiers"):
        tier = daily.pick_tier(prem_blk["cheapest_prem"], cfg_v["premium_tiers"])
        state_v = daily._load(daily.STATE_PATH, {}) or {}
        nd = _safe(lambda: next_dca_date(today, cfg_v.get("dca_day", 15), state_v))
        when = f"下次 {nd:%m-%d}" if nd else "本月待执行"
        L.append(f"  定投 {when} · {tier.get('amount', 0)} 元（金额不随溢价变，溢价只改入场价）")
    else:
        L.append("  定投 溢价数据缺口，金额不受影响（恒为基准额），入场价到时按当日溢价算")
    # 风险/有利
    if pe and pe.get("fwd_pct") is not None:
        if pe["fwd_pct"] >= 85:
            risks.append(f"估值进入极端区 P{pe['fwd_pct']}")
        elif pe["fwd_pct"] <= 15:
            notes.append(f"估值便宜（P{pe['fwd_pct']}）")
    if risks:
        L.append("  风险 " + "、".join(risks))
    if notes:
        L.append("  有利 " + "、".join(notes))
    L.append("  边界 市场分析影响的是风险认识，不能随意改变定投规则——"
             "触发动作的只有两件事：定投日 + 加仓阈值")

    # ── 附录：AI 龙头估值（数据保留，收进附录不占主线篇幅） ──
    if ai and ai["cur"]:
        rows = sorted(ai["cur"], key=lambda x: x["fp"])
        name = lambda r: CN_NAME.get(r["t"], r["t"])  # noqa: E731
        L += ["", "附录 AI 龙头估值 " + "─" * 14]
        cut = (len(rows) + 1) // 2
        for i, chunk in enumerate((rows[:cut], rows[cut:])):
            if chunk:
                L.append(("  预期PE   " if i == 0 else "           ")
                         + " · ".join(f"{name(r)} {r['fp']:.1f}" for r in chunk))
        gs = sorted([r for r in rows if r["g"] is not None], key=lambda x: x["g"], reverse=True)
        if gs:
            L.append(f"  盈利预期 {name(gs[0])} {gs[0]['g']:+.0f}% ~ {name(gs[-1])} {gs[-1]['g']:+.0f}%")

    L += ["", "─" * 14]
    sh = source_health_lines()
    if sh:
        L.append("  数据源健康")
        L += sh
    L += ["  下一份：月报（每月16日核对定投执行）· 异常随时提醒 · 平时安静", ""]
    print("\n".join(L))


if __name__ == "__main__":
    main()
