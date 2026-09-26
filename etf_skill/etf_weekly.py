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
    d = _get(URLS["pe"])
    c = d.get("current", {})
    fwd_hist = [x["value"] for x in d.get("forward", []) if x.get("value") is not None]
    return {"trailing": c.get("trailing"), "forward": c.get("forward"),
            "fwd_pct": pct_rank(fwd_hist, c["forward"]) if c.get("forward") else None,
            "fwd_med": _median(fwd_hist), "fwd_since": d.get("historyStarts", {}).get("forward", "")[:4]}


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
    d = _get(URLS["ai_val"])
    cur = [(m["ticker"], m.get("snapshot", {}).get("forwardPE")) for m in d.get("members", [])]
    ref = [(r["ticker"], r["name"], r["peakForwardPE"], r.get("peakDate", "")) for r in d.get("reference_1999", [])]
    return {"cur": [(t, round(p, 1)) for t, p in cur if p], "ref": ref}


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
    L = ["  §7 定投执行回顾"]

    def window(lo, hi):
        return {d: v for d, v in log.items() if lo < d <= hi}

    t = today.isoformat()
    this_wk = window((today - datetime.timedelta(days=7)).isoformat(), t)
    last_wk = window((today - datetime.timedelta(days=14)).isoformat(), (today - datetime.timedelta(days=7)).isoformat())
    if not this_wk:
        L.append("  近 7 天无溢价记录（日报未运行或数据缺失）")
    else:
        L.append(f"  近 7 天决策池溢价（{min(this_wk)} ~ {max(this_wk)}，{len(this_wk)} 个交易日）")
        for c in cfg["pool"]:
            v = [d[c] for d in this_wk.values() if c in d]
            p = [d[c] for d in last_wk.values() if c in d]
            if not v:
                L.append(f"    {c}  数据缺失")
                continue
            chg = f"  较前一周均值 {sum(v)/len(v) - sum(p)/len(p):+.2f}pct" if p else ""
            L.append(f"    {c}  {min(v):.2f}% ~ {max(v):.2f}%  最新 {v[-1]:.2f}%{chg}")
        latest = this_wk[max(this_wk)]
        best_code = min(latest, key=latest.get)
        tier = daily.pick_tier(latest[best_code], cfg["premium_tiers"])
        amt, _ = daily.plan_amount(tier, cfg["monthly_base_amount"], state.get("backlog", 0), cfg["backlog_cap"])
        L.append(f"  按最新溢价 {latest[best_code]:.2f}%（{best_code}）→ {tier['label']} {amt} 元")

    nd = next_dca_date(today, cfg["dca_day"], state)
    if nd:
        L.append(f"  下次定投：{nd:%m-%d}（{(nd - today).days} 天后，遇休市顺延）")
    else:
        L.append("  下次定投：本月已过定投日且未执行 → 下一个交易日")
    L.append(f"  积压资金：{state.get('backlog', 0)} 元（上限 {cfg['backlog_cap']}）")
    hist = state.get("history", [])
    if hist:
        h = hist[-1]
        L.append(f"  上次执行：{h['date']} {h['code']} 溢价 {h['premium']}% {h['tier']} {h['amount']} 元")
    return L


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

    L = ["", "=" * 48, "  📊 纳指深度周报", f"  📅 {today:%Y-%m-%d}", "=" * 48]
    if failed:
        L.append(f"  ⚠ 部分数据获取失败：{'、'.join(failed)}")
    L.append("")

    if ndx:
        L += ["  §1 指数位置",
              f"  纳指100 {ndx['close']:,.0f}（{ndx['date']}）",
              f"  距历史高点 {ndx['dd']:+.1f}%（高点 {ndx['peak']:,.0f}，{ndx['peak_date']}）", ""]

    if pe and pe.get("forward"):
        L += ["  §2 估值",
              f"  预期市盈率（未来12个月盈利）：{pe['forward']}",
              f"    处于 {pe['fwd_since']} 年以来第 {pe['fwd_pct']} 百分位（中位数 {pe['fwd_med']:.1f}）"]
        if pe.get("trailing"):
            L.append(f"  市盈率（过去12个月盈利）：{pe['trailing']}  → 盈利预期增长约 "
                     f"{(pe['trailing'] / pe['forward'] - 1) * 100:.0f}%")
        L.append("")

    if r5:
        L += ["  §3 滚动 5 年年化收益",
              f"  当前 {r5['latest']:+.1f}%/年（{r5['date']}）",
              f"    {r5['since']} 年以来第 {r5['pct']} 百分位，中位数 {r5['med']:+.1f}%，"
              f"范围 {r5['min']:+.1f}% ~ {r5['max']:+.1f}%"]
        if r5.get("neg_pct") is not None:
            L.append(f"    历史上任意 5 年持有为负的比例：{r5['neg_pct']}%")
        L.append("")

    if vxn:
        L += ["  §4 纳指波动率指数（VXN，数值越高市场越恐慌）",
              f"  当前 {vxn['latest']:.1f}（{vxn['date']}）",
              f"    {vxn['since']} 年以来第 {vxn['pct']} 百分位，中位数 {vxn['med']:.1f}，"
              f"范围 {vxn['min']:.1f} ~ {vxn['max']:.1f}", ""]

    if dd:
        L.append("  §5 历史最大回撤（按跌幅排序）")
        for period, val, rec in dd:
            rec_s = f"，{rec} 天收复" if rec else ""
            L.append(f"    -{val:.0f}%  {period}{rec_s}")
        L.append("")

    if ai and ai["cur"]:
        L += ["  §6 AI 龙头 vs 2000 年泡沫峰值（均为预期市盈率）",
              "  当前：" + " | ".join(f"{CN_NAME.get(t, t)} {p}x" for t, p in ai["cur"]),
              "  峰值：" + " | ".join(f"{CN_NAME.get(t, n.split()[0])} {p}x({d})" for t, n, p, d in ai["ref"][:3]),
              ""]

    L += _safe(lambda: dca_review(today)) or ["  §7 定投执行回顾：读取本地配置/状态失败"]

    L += ["", "─" * 48,
          "  💡 以上估值与波动数据仅作背景参考，定投金额按日报溢价档位执行",
          "─" * 48, ""]
    print("\n".join(L))


if __name__ == "__main__":
    main()
