"""
513300 纳指定投简报
数据：btcdca.me（综合评分） + qt.gtimg.cn（513300实时溢价）
     + historyofmarket.com（NDX PE / 收益拆解 / 滚动5年 / VXN / 回撤 / AI估值）
"""

import sys, os, json, urllib.request

MONTHLY_DCA  = 1000
DCA_WEEKDAY  = 2   # 周三
WEEKDAY_CN   = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
BASE_HOM     = "https://historyofmarket.com/api"
BTC_URL      = "https://www.btcdca.me/nasdaq/api/score"

URLS = {
    "ndx_pe":    f"{BASE_HOM}/ndx/forward-pe.json",
    "driver":    f"{BASE_HOM}/ndx/driver-decomp.json",
    "rolling5y": f"{BASE_HOM}/ndx/rolling5y.json",
    "vxn":       f"{BASE_HOM}/ndx/vxn.json",
    "drawdowns": f"{BASE_HOM}/ndx/drawdowns.json",
    "ai_val":    f"{BASE_HOM}/mag7/ai-valuation.json",
}


def _get(url, encoding=None):
    h = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36"}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    return raw.decode(encoding or "utf-8")


def _json(url):
    return json.loads(_get(url))


# ── 数据获取 ────────────────────────────────────────────────

def fetch_btcdca():
    d = _json(BTC_URL)["data"]
    ind = d.get("indicators", {})
    return {
        "score": d.get("totalScore"), "yesterday": d.get("yesterdayScore"),
        "multiplier": d.get("multiplier"), "status": d.get("status", ""),
        "pe": ind.get("valuation", {}).get("pe"),
        "vix": ind.get("macro", {}).get("vix"),
        "fear_greed": ind.get("sentiment", {}).get("fearGreed"),
        "rsi": ind.get("technical", {}).get("rsi"),
    }


def fetch_513300():
    raw = _get("https://qt.gtimg.cn/q=sh513300", encoding="gbk")
    f = raw.split("~")
    if len(f) < 40:
        return {"price": None, "name": "未知"}
    return {"price": float(f[3]) if f[3] else None, "name": f[1]}


def fetch_net_value():
    url = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=513300&pageIndex=1&pageSize=1&_=1"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/513300.html"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    lst = d.get("Data", {}).get("LSJZList", [])
    if lst:
        return float(lst[0]["DWJZ"]), lst[0]["FSRQ"]
    return None, None


def fetch_ndx_pe():
    d = _json(URLS["ndx_pe"])
    cur = d.get("current", {})
    return {"trailing": cur.get("trailing"), "forward": cur.get("forward")}


def fetch_driver():
    """收益拆解：最新一年，PE变动 vs EPS变动"""
    d = _json(URLS["driver"])
    series = d.get("series", [])
    if series:
        return series[-1]  # {year, priceReturn, peChange, epsChange, driver, endingPE}
    return {}


def fetch_rolling5y():
    """滚动5年收益：最新值 + 历史范围"""
    d = _json(URLS["rolling5y"])
    series = d.get("series", d.get("data", []))
    if not isinstance(series, list) or not series:
        return {}
    vals = [s.get("value", 0) for s in series if s.get("value") is not None]
    if not vals:
        return {}
    return {"latest": round(vals[-1], 1), "min": round(min(vals), 1), "max": round(max(vals), 1)}


def fetch_vxn():
    """纳指波动率指数 VXN"""
    d = _json(URLS["vxn"])
    series = d.get("series", d.get("data", []))
    if not isinstance(series, list) or not series:
        return {}
    vals = [s.get("value", 0) for s in series if s.get("value") is not None]
    if not vals:
        return {}
    return {"latest": round(vals[-1], 1), "min": round(min(vals), 1), "max": round(max(vals), 1)}


def fetch_drawdowns():
    """当前回撤 + 历史最大几次"""
    d = _json(URLS["drawdowns"])
    dd_list = d.get("drawdowns", [])
    cur = dd_list[-1] if dd_list else {}
    major = [dd for dd in dd_list if abs(dd.get("decline", 0)) >= 0.25]
    major_desc = []
    for dd in major[:3]:
        name = dd.get("causeEn", "")
        if not name:
            name = dd.get("cause", "未知")
        major_desc.append(f"{name} {abs(dd['decline']*100):.0f}%")
    return {
        "current_pct": round(abs(cur.get("decline", 0)) * 100, 1) if cur else None,
        "active": cur.get("active", False),
        "major": " | ".join(major_desc),
    }


def fetch_ai_valuation():
    """AI 龙头 PE + 1999 dotcom 参考峰值"""
    d = _json(URLS["ai_val"])
    members = d.get("members", [])
    ref = d.get("reference_1999", [])
    latest_pe = {}
    for m in members:
        snap = m.get("snapshot", {})
        pe = snap.get("trailingPE")
        if pe:
            latest_pe[m["ticker"]] = round(pe, 1)
    ref_line = []
    for r in ref[:2]:
        ref_line.append(f"{r['name'].split()[0]} {r['peakForwardPE']}")
    # 前4家：NVDA, MSFT, META, GOOGL
    ai_pe_str = ", ".join(f"{t} {p}×" for t, p in list(latest_pe.items())[:4])
    return {"ai_pe": ai_pe_str, "dotcom_ref": " | ".join(ref_line)}


# ── 格式化 ────────────────────────────────────────────────

def _icon_score(s):
    if s is None: return "─"
    if s >= 70: return "🟢"
    if s >= 55: return "🟡"
    if s >= 40: return "🟠"
    return "🔴"


def _status_label(s):
    if "高估" in s: return "🔴 高估-减量定投"
    if "偏高" in s: return "🟠 偏高一减少定投"
    if "合理" in s: return "🟡 合理区"
    if "低估" in s: return "🟢 低估值-加量定投"
    return s


def format_output(b, etf, nav, nav_date, ndx_pe, dim):
    today_idx = __import__("datetime").datetime.now().weekday()
    weekly = round(MONTHLY_DCA / 4)

    # 溢价
    if etf["price"] and nav:
        pct = (etf["price"] - nav) / nav * 100
        if pct > 8.5:  p_lbl = "🔴 极端溢价"
        elif pct > 5:  p_lbl = "🟡 偏高"
        elif pct > 3:  p_lbl = "🟠 略高"
        elif pct > 0:  p_lbl = "🟢 正常"
        else:          p_lbl = "🔵 折价"
    else:
        pct, p_lbl = None, "─"

    # DCA
    mult = b.get("multiplier", 1.0)
    dca_amt = round(weekly * mult) if today_idx == DCA_WEEKDAY else 0
    if dca_amt > 0:
        if mult < 0.9:  dca_l = f"🔴 减量定投 {dca_amt} 元 (基250×{mult})"
        elif mult > 1.1: dca_l = f"🟢 加量定投 {dca_amt} 元 (基250×{mult})"
        else:            dca_l = f"✅ 正常定投 {dca_amt} 元"
    else:
        dca_l = "非定投日，不操作"

    lines = [
        "", "=" * 48,
        f"  📊 513300 早盘简报",
        f"  📅 {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} ({WEEKDAY_CN[today_idx]})",
        "=" * 48, "",
        f"  🏷  {etf['name']}",
    ]
    if etf["price"]:
        lines.append(f"  现价: {etf['price']}    净值: {nav or '─'} ({nav_date or '─'})")
        if pct is not None:
            lines.append(f"  溢价: {pct:+.2f}%  →  {p_lbl}")
    else:
        lines.append("  实时行情获取失败")

    # btcdca 评分
    lines += ["", "─" * 48,
        f"  🔗 btcdca 纳指定投评分",
        f"  综合评分: {b['score']}/100 {_icon_score(b['score'])}  昨日: {b.get('yesterday','─')}/100",
        f"  状态: {_status_label(b.get('status',''))}",
        f"  DCA倍数: {b.get('multiplier','─')}x", ""]

    details = []
    if b.get("pe"):  details.append(f"PE {b['pe']}")
    if b.get("vix"): details.append(f"VIX {b['vix']}")
    if b.get("fear_greed") is not None: details.append(f"恐惧贪婪 {b['fear_greed']}")
    if b.get("rsi"): details.append(f"RSI {round(b['rsi'], 1)}")
    if details:
        lines.append(f"  {' | '.join(details)}")
        lines.append("")

    # PE解读
    if ndx_pe and ndx_pe.get("forward"):
        fpe, tpe = ndx_pe["forward"], ndx_pe.get("trailing")
        gap = round((tpe / fpe - 1) * 100) if tpe else None
        if fpe < 22:     pe_n = f"Forward PE {fpe}，偏低，估值有吸引力"
        elif fpe < 28:   pe_n = f"Forward PE {fpe}，适中，盈利增长预期{gap}%"
        elif fpe < 35:   pe_n = f"Forward PE {fpe}，偏高，增长需{gap}%以上支撑"
        else:            pe_n = f"Forward PE {fpe}，高估"
        lines.append(f"  📐 PE解读: Trailing {tpe} | Forward {fpe} → {pe_n}")
        lines.append("")

    # ── 市场多维度 ──
    lines.append("─" * 48)
    lines.append("  📊 市场多维度")
    lines.append("")

    # 1. 收益拆解
    drv = dim.get("driver", {})
    if drv.get("year"):
        pr = round(drv.get("priceReturn", 0) * 100, 1)
        ec = round(drv.get("epsChange", 0) * 100, 1)
        pc = round(drv.get("peChange", 0) * 100, 1)
        health = "✅" if pc >= -5 and ec > 5 else "⚠️"
        lines.append(f"  📈 收益拆解 {drv['year']}: {pr:+.1f}% (盈利{ec:+.1f}% | 估值{pc:+.1f}%) {health}")

    # 2. 滚动5年
    r5 = dim.get("rolling5y", {})
    if r5.get("latest") is not None:
        lines.append(f"  🏃 5年收益 {r5['latest']:+.1f}%/年 | 范围 {r5['min']:+.1f}%~{r5['max']:+.1f}%")

    # 3. VXN
    vxn = dim.get("vxn", {})
    if vxn.get("latest") is not None:
        v = vxn["latest"]
        lbl = "平静" if v < 20 else "略高" if v < 30 else "偏高" if v < 40 else "恐慌"
        lines.append(f"  🌊 VXN {v} {lbl} | 历史 {vxn['min']}~{vxn['max']}")

    # 4. 回撤
    dd = dim.get("drawdowns", {})
    if dd.get("current_pct") is not None:
        lines.append(f"  📉 当前回撤 {dd['current_pct']:.1f}% | 最大 {dd.get('major','─')}")

    # 5. AI估值
    ai = dim.get("ai_val", {})
    if ai.get("ai_pe"):
        lines.append(f"  🤖 AI PE: {ai['ai_pe']}")
    if ai.get("dotcom_ref"):
        lines.append(f"       1999峰: {ai['dotcom_ref']}")

    lines.append("")

    # 操作
    lines += ["=" * 48,
        "  💡 今日操作", "=" * 48, "",
        f"  ★ 定投", f"     {dca_l}", "",
        "─" * 48,
        f"  【周定投基数】 {weekly}元 | 【月定投】 {MONTHLY_DCA}元",
        "─" * 48, ""]
    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dim = {}

    print("📡 btcdca 评分...")
    try:
        btc = fetch_btcdca()
    except Exception as e:
        print(f"btcdca失败: {e}")
        btc = {"score": None, "yesterday": None, "multiplier": None, "status": "数据失败"}

    print("📡 513300 实时行情...")
    etf = fetch_513300()

    print("📡 513300 净值...")
    try:
        nav, nav_date = fetch_net_value()
    except Exception:
        nav, nav_date = None, None

    print("📡 NDX 数据 (PE/收益拆解/5年/VXN/回撤/AI估值)...")
    ndx_pe = fetch_ndx_pe()
    dim["driver"]   = fetch_driver()
    dim["rolling5y"] = fetch_rolling5y()
    dim["vxn"]      = fetch_vxn()
    dim["drawdowns"] = fetch_drawdowns()
    dim["ai_val"]   = fetch_ai_valuation()

    print(format_output(btc, etf, nav, nav_date, ndx_pe, dim))
