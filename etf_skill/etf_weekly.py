"""
513300 纳指深度周报 — 市场多维度全景
每周一推送，回顾上周五收盘后的5个核心维度
"""
import sys, json, urllib.request

BASE = "https://historyofmarket.com/api"
URLS = {
    "pe":       f"{BASE}/ndx/forward-pe.json",
    "driver":   f"{BASE}/ndx/driver-decomp.json",
    "rolling5y":f"{BASE}/ndx/rolling5y.json",
    "vxn":      f"{BASE}/ndx/vxn.json",
    "drawdowns":f"{BASE}/ndx/drawdowns.json",
    "ai_val":   f"{BASE}/mag7/ai-valuation.json",
    "ndx_price":f"{BASE}/ndx/price.json",
}


def _get(url):
    h = {"User-Agent": "Mozilla/5.0"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def fmt_pct(v):
    return f"{v*100:+.1f}%" if isinstance(v, (int, float)) else "─"


# ── 数据获取 ────────────────────────────────────────────────

def get_pe():
    d = _get(URLS["pe"])
    c = d.get("current", {})
    return {"trailing": c.get("trailing"), "forward": c.get("forward")}


def get_driver():
    d = _get(URLS["driver"])
    s = d.get("series", [])
    return s[-1] if s else {}


def get_rolling5y():
    d = _get(URLS["rolling5y"])
    s = d.get("series", d.get("data", []))
    vals = [x.get("value") for x in s if x.get("value") is not None]
    if not vals:
        return {}
    return {"latest": round(vals[-1], 1), "min": round(min(vals), 1), "max": round(max(vals), 1)}


def get_vxn():
    d = _get(URLS["vxn"])
    s = d.get("series", d.get("data", []))
    vals = [x.get("value") for x in s if x.get("value") is not None]
    if not vals:
        return {}
    return {"latest": round(vals[-1], 1), "min": round(min(vals), 1), "max": round(max(vals), 1)}


def get_drawdowns():
    d = _get(URLS["drawdowns"])
    dds = d.get("drawdowns", [])
    cur = dds[-1] if dds else {}
    major = [x for x in dds if abs(x.get("decline", 0)) >= 0.25]
    major_str = " | ".join(
        f"{x.get('causeEn','') or '未知'} {abs(x['decline']*100):.0f}%"
        for x in major[:4]
    )
    return {
        "current_pct": round(abs(cur.get("decline", 0)) * 100, 1) if cur else None,
        "active": cur.get("active", False),
        "major_list": [(x.get("period",""), abs(x["decline"]*100)) for x in major[:6]],
        "major_str": major_str,
    }


def get_ai_val():
    d = _get(URLS["ai_val"])
    members = d.get("members", [])
    ref = d.get("reference_1999", [])
    pes = {}
    for m in members:
        snap = m.get("snapshot", {})
        pe = snap.get("trailingPE")
        if pe:
            pes[m["ticker"]] = round(pe, 1)
    ref_pe = [f"{r['name'].split()[0]} {r['peakForwardPE']}" for r in ref[:3]]
    return {"pes": pes, "ref": " | ".join(ref_pe)}


def get_ndx_price():
    d = _get(URLS["ndx_price"])
    lat = d.get("latest", {})
    return lat.get("close"), lat.get("drawdown")


# ── 格式化 ────────────────────────────────────────────────

def _vxn_label(v):
    if v < 20: return "平静"
    if v < 30: return "略高"
    if v < 40: return "偏高"
    if v < 60: return "恐慌"
    return "极度恐慌"


def _health_icon(drv):
    pc = drv.get("peChange", 0)
    ec = drv.get("epsChange", 0)
    if pc >= -0.05 and ec > 0.05:
        return "✅ 盈利驱动"
    if pc > 0.05 and ec > 0.05:
        return "⚠️ 混合驱动"
    if pc > 0.05 and ec < 0:
        return "🔴 纯估值扩张"
    return "❓"


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("📡 拉取 NDX 深度数据...")

    pe      = get_pe()
    drv     = get_driver()
    r5      = get_rolling5y()
    vxn     = get_vxn()
    dd      = get_drawdowns()
    ai      = get_ai_val()
    ndx_pr, ndx_dd = get_ndx_price()

    lines = [
        "",
        "=" * 48,
        "  📊 纳指深度周报",
        f"  📅 {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}",
        "=" * 48,
        "",
    ]

    # --- §1 估值 ---
    if pe.get("trailing") or pe.get("forward"):
        tp, fp = pe.get("trailing"), pe.get("forward")
        gap = round((tp / fp - 1) * 100) if tp and fp else None
        lines += [
            "  §1 估值",
            f"  NDX Trailing PE: {tp}  |  Forward PE: {fp} (Bloomberg BEst)",
            f"  增长预期: {gap}%  →  Forward PE {fp} 属于",
            f"  {'偏低' if fp<22 else '适中' if fp<28 else '偏高' if fp<35 else '高估'}水平",
            "",
        ]

    # --- §2 收益拆解 ---
    if drv.get("year"):
        pr = drv["priceReturn"]
        ec = drv["epsChange"]
        pc = drv["peChange"]
        lines += [
            "  §2 收益拆解（年度）",
            f"  {drv['year']}年  NDX 回报: {fmt_pct(pr)}",
            f"  其中 盈利增长贡献: {fmt_pct(ec)}",
            f"       估值变动贡献: {fmt_pct(pc)}",
            f"  诊断: {_health_icon(drv)}",
            "",
        ]

    # --- §3 滚动收益 + VXN ---
    if r5.get("latest") is not None:
        lines += [
            "  §3 滚动5年收益",
            f"  当前 {r5['latest']:+.1f}%/年",
            f"  历史范围 {r5['min']:+.1f}% ~ {r5['max']:+.1f}%",
            "",
        ]
    if vxn.get("latest") is not None:
        lines += [
            "  §4 波动率 (VXN)",
            f"  当前 VXN {vxn['latest']}  {_vxn_label(vxn['latest'])}",
            f"  历史范围 {vxn['min']} ~ {vxn['max']}",
            "",
        ]

    # --- §4 回撤 ---
    if dd.get("current_pct") is not None:
        lines += [
            "  §5 回撤分析",
            f"  当前回撤: {dd['current_pct']:.1f}% ({'进行中' if dd.get('active') else '已修复'})",
            f"  历史最大:",
        ]
        for period, val in dd.get("major_list", []):
            lines.append(f"    -{val:.0f}%  {period}")
        lines.append("")

    # --- §5 AI估值 ---
    if ai.get("pes"):
        ai_str = " | ".join(f"{t} {p}x" for t, p in ai["pes"].items())
        lines += [
            "  §6 AI 龙头估值 vs 1999 Dotcom",
            f"  当前:  {ai_str}",
            f"  1999:  {ai['ref']}",
            "",
        ]

    # --- §6 NDX 当前位置 ---
    if ndx_pr:
        lines.append(f"  NDX 指数: {ndx_pr:,.0f}  距高点 {fmt_pct(ndx_dd)}")

    lines += [
        "",
        "─" * 48,
        "  💡 上述数据不构成操作建议，参考 btcdca 日报定投倍数执行",
        "─" * 48,
        "",
    ]
    print("\n".join(lines))
