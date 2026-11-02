"""
纳指深度周报 — 估值 / 滚动收益 / 波动 / 回撤 / AI 龙头估值 + 定投执行回顾
每周一推送。估值类数据只作背景参考，定投金额以日报溢价档位为准。
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
    return {"close": lat["close"], "date": lat["date"], "dd": lat["drawdown"] * 100,
            "peak": peak["close"], "peak_date": peak["date"]}


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


def dca_review(today):
    cfg = daily._load(daily.CONFIG_PATH, None)
    state = daily._load(daily.STATE_PATH, {"backlog": 0, "last_dca_month": None, "history": []})
    log = daily._load(daily.PREM_LOG, {})
    L = ["", "④ 本周执行 " + "─" * 14]

    def window(lo, hi):
        return {d: v for d, v in log.items() if lo < d <= hi}

    t = today.isoformat()
    this_wk = window((today - datetime.timedelta(days=7)).isoformat(), t)
    last_wk = window((today - datetime.timedelta(days=14)).isoformat(), (today - datetime.timedelta(days=7)).isoformat())
    if not this_wk:
        L.append("  溢率 近 7 天无记录（日报未运行或数据缺失）")
    else:
        latest = this_wk[max(this_wk)]
        main_c = min(latest, key=latest.get)
        v = [d[main_c] for d in this_wk.values() if main_c in d]
        p = [d[main_c] for d in last_wk.values() if main_c in d]
        chg = sum(v) / len(v) - sum(p) / len(p) if p else None
        direc = "" if chg is None else ("上行" if chg > 0.5 else "回落" if chg < -0.5 else "横")
        L.append(f"  溢率 {main_c}  {min(v):.1f}~{max(v):.1f}% · 最新 {v[-1]:.1f}%"
                 + (f" · 较上周 {chg:+.2f}pct → 高位{direc}" if chg is not None else ""))
        others = " · ".join(f"{c} {latest[c]:.1f}%" for c in cfg["pool"] if c != main_c and c in latest)
        if others:
            L.append(f"  其他 {others}（都更贵，无切换价值）")

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


# ── 输出辅助：把百分位变成「一眼能读」的词 + 条 ─────────────

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
    pe  = _safe(get_pe)
    r5  = _safe(lambda: get_series_stat("rolling5y"))
    vxn = _safe(lambda: get_series_stat("vxn"))
    dd  = _safe(get_drawdowns)
    ndx = _safe(get_ndx_price)
    ai  = _safe(get_ai_val)
    failed = [n for n, v in [("市盈率", pe), ("滚动收益", r5), ("波动率", vxn),
                             ("历史回撤", dd), ("指数价格", ndx), ("AI估值", ai)] if not v]

    wk = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]
    L = [f"📊 纳指周报 · {today:%m-%d} {wk}"]
    if failed:
        L.append(f"  ⚠ 数据缺口：{'、'.join(failed)}")

    # ── 顶部：三句话说完（不重复下面任何数字条） ──
    L.append("")
    L.append("  ▎一句话")
    if ndx:
        L.append(f"    位置 纳指100 {ndx['close']:,.0f}，距高点 {ndx['dd']:+.1f}%"
                 f"（历史常态回撤 -28~-40%）")
    temps = []
    if pe and pe.get("forward"):
        temps.append(f"估值{verdict_valu(pe['fwd_pct'] or 0)} {pe['fwd_pct']}")
    if vxn:
        temps.append(f"情绪{verdict_vxn(vxn['pct'] or 0)} {vxn['pct']}")
    if r5:
        temps.append(f"回报{verdict_return(r5['pct'] or 0)} {r5['pct']}")
    if temps:
        L.append("    温度 " + " · ".join(temps) + " — 无一进极端区")
    cfg_w = daily._load(daily.CONFIG_PATH, {}) or {}
    st_w = daily._load(daily.STATE_PATH, {}) or {}
    nd_w = _safe(lambda: next_dca_date(today, cfg_w.get("dca_day", 15), st_w))
    when = f"下次 {nd_w:%m-%d} " if nd_w else "本月待执行 "
    L.append(f"    动作 定投照旧（{when}投 {cfg_w.get('monthly_base_amount', 1000)} 元）；不追高、不砍仓；")
    L.append("         加仓只等溢率阈值，不等指数点位")

    # ── ① 贵不贵：三个维度各一句，不堆区间 ──
    if pe or r5 or vxn:
        L += ["", "① 贵不贵（三个维度） " + "─" * 14]
        if pe and pe.get("forward"):
            L.append(f"  估值 预期PE {pe['forward']}  {bar(pe['fwd_pct'] or 0)} P{pe['fwd_pct']}"
                     f"（中位 {pe['fwd_med']:.1f}） {verdict_valu(pe['fwd_pct'] or 0)}")
        if vxn:
            L.append(f"  情绪 VXN {vxn['latest']:.1f}  {bar(vxn['pct'] or 0)} P{vxn['pct']}"
                     f"（中位 {vxn['med']:.1f}） {verdict_vxn(vxn['pct'] or 0)}")
        if r5:
            L.append(f"  回报 5年年化 {r5['latest']:+.1f}%  {bar(r5['pct'] or 0)} P{r5['pct']}"
                     f"（中位 {r5['med']:+.1f}%） {verdict_return(r5['pct'] or 0)}")
            if r5.get("neg_pct") is not None:
                L.append(f"       任取 5 年持有为负的历史概率 {r5['neg_pct']}%")
        pcts = [x for x in [pe.get("fwd_pct") if pe else None,
                            vxn.get("pct") if vxn else None,
                            r5.get("pct") if r5 else None] if x is not None]
        extreme = [n for n, x in [("估值", pe.get("fwd_pct") if pe else None),
                                  ("情绪", vxn.get("pct") if vxn else None),
                                  ("回报", r5.get("pct") if r5 else None)]
                   if x is not None and (x <= 15 or x >= 85)]
        if pcts and not extreme:
            L.append("  判读 三项都落在 15~85 之间 = 没有一个维度支持现在加仓或减仓 → 按计划执行")
        elif extreme:
            L.append(f"  判读 {'、'.join(extreme)} 已进极端区（≤15 或 ≥85）→ 这一项才是本周要盯的")
        else:
            L.append("  判读 分位不齐，按下表读数判断")

    # ── ② 是不是 2000 年泡沫：只比一张表 ──
    if ai and ai["cur"]:
        rows = sorted(ai["cur"], key=lambda x: x["fp"])
        name = lambda r: CN_NAME.get(r["t"], r["t"])  # noqa: E731
        L += ["", "② AI 龙头贵不贵 " + "─" * 14]
        cut = (len(rows) + 1) // 2
        for i, chunk in enumerate((rows[:cut], rows[cut:])):
            if chunk:
                L.append(("  预期PE   " if i == 0 else "           ")
                         + " · ".join(f"{name(r)} {r['fp']:.1f}" for r in chunk))
        L.append("  2000峰值  " + " · ".join(f"{CN_NAME.get(t, n.split()[0])} {p:.0f}"
                                             for t, n, p, _ in ai["ref"][:3]))
        gs = sorted([r for r in rows if r["g"] is not None], key=lambda x: x["g"], reverse=True)
        if gs:
            tail = f" · {name(gs[-1])} {gs[-1]['g']:+.0f}%（唯一下滑）" if gs[-1]["g"] < 0 else ""
            L.append(f"  盈利预期  {name(gs[0])} {gs[0]['g']:+.0f}%{tail}")
        cur_max = max(r["fp"] for r in rows)
        ref_min = min(p for _, _, p, _ in ai["ref"][:3])
        if cur_max and ref_min:
            L.append(f"  判读 当年最便宜的泡沫股 {ref_min:.0f}x 仍是今天最贵（{cur_max:.0f}x）的"
                     f" {ref_min / cur_max:.1f} 倍 → 不同结构")
        if gs and gs[0]["g"] > 30:
            L.append("       低 PE 是「盈利预期翻倍」撑的，不是股价便宜")

    # ── ③ 跌下来有多深：给区间，不给年表 ──
    if dd:
        L += ["", "③ 跌下来有多深 " + "─" * 14]
        L.append("  " + " · ".join(f"-{v:.0f}%({p[:4]})" for p, v, _ in dd))
        recs = [r for _, _, r in dd if r]
        if recs:
            L.append(f"  收复 {min(recs) / 365:.1f}~{max(recs) / 365:.1f} 年 · 常态 -28%~-40%，-83% 只出现过一次")
        L.append("  判读 -83% 那次的前提是「盈利证伪 + 估值极端」同时成立；")
        tail = (f"今天估值 P{pe['fwd_pct']}，不具备那个前提"
                if pe and pe.get("fwd_pct") else "今天估值分位见 ①")
        L.append(f"       {tail}")

    # ── ④ 本周执行 ──
    L += _safe(lambda: dca_review(today)) or ["", "④ 本周执行：读取本地配置/状态失败"]

    L += ["", "─" * 14,
          "  估值/波动只是背景；买卖只看两件事：定投日 + 溢率阈值", ""]
    print("\n".join(L))


if __name__ == "__main__":
    main()
