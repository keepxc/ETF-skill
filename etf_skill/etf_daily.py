"""513300 纳指定投日报（精简版）"""
import sys, json, urllib.request

MONTHLY_DCA = 1000; DCA_WEEKDAY = 2
WEEKDAY_CN  = ["周一","周二","周三","周四","周五","周六","周日"]
BTC_URL     = "https://www.btcdca.me/nasdaq/api/score"
NDX_PE_URL  = "https://historyofmarket.com/api/ndx/forward-pe.json"
MKG_URL     = "https://www.marketgrep.com/api/summary"


def _get(url, encoding="utf-8"):
    h = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36"}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode(encoding)


def fetch_btcdca():
    d = json.loads(_get(BTC_URL))["data"]
    ind = d.get("indicators", {})
    return {"score": d["totalScore"], "yesterday": d.get("yesterdayScore"),
            "mult": d["multiplier"], "status": d.get("status", ""),
            "pe": ind.get("valuation", {}).get("pe"),
            "vix": ind.get("macro", {}).get("vix"),
            "fear": ind.get("sentiment", {}).get("fearGreed"),
            "rsi": ind.get("technical", {}).get("rsi")}


def fetch_513300():
    raw = _get("https://qt.gtimg.cn/q=sh513300", encoding="gbk")
    f = raw.split("~")
    if len(f) < 40:
        return {"price": None, "prev_close": None, "name": "513300"}
    return {
        "price": float(f[3]) if f[3] else None,
        "prev_close": float(f[4]) if f[4] else None,
        "name": f[1],
    }


def fetch_nav():
    url = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=513300&pageIndex=1&pageSize=1"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/513300.html"})
    d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
    lst = d.get("Data", {}).get("LSJZList", [])
    return (float(lst[0]["DWJZ"]), lst[0]["FSRQ"]) if lst else (None, None)


def fetch_ndx_pe():
    try:
        d = json.loads(_get(NDX_PE_URL))
        c = d.get("current", {})
        return {"t": c.get("trailing"), "f": c.get("forward")}
    except Exception:
        return {"t": None, "f": None}


def fetch_marketgrep():
    try:
        d = json.loads(_get(MKG_URL))
        u = d.get("us", {})
        t = d.get("turbulence", {})
        regime = u.get("regime", "")
        score = u.get("exposure_score")
        dspx = u.get("dspx")
        cor1m = u.get("cor1m")
        vix = u.get("vix")
        turb = t.get("state", "")
        rl = "🔵 Risk ON" if "risk_on" in regime else "🔴 Risk OFF" if "risk_off" in regime else regime
        # 分散度描述
        if dspx and dspx > 35:      disp = "分散度高"
        elif dspx and dspx > 25:    disp = "分散中等"
        else:                        disp = "集中度高"
        # 相关性描述
        if cor1m is not None:
            if cor1m < 15:           cor_str = "个股分化"
            elif cor1m < 30:         cor_str = "板块联动"
            else:                    cor_str = "同涨同跌"
        else:
            cor_str = ""
        return {"line": f"🌡 市场: {rl} ({score}) | {disp} | {cor_str} | 湍流{turb}" if turb else f"🌡 市场: {rl} ({score}) | {disp} | {cor_str}"}
    except Exception:
        return {"line": ""}


def _sco(s):
    if s is None: return "─"
    if s >= 70: return "🟢"
    if s >= 55: return "🟡"
    if s >= 40: return "🟠"
    return "🔴"


def _status(s):
    if "高估" in s: return "🔴 高估"
    if "偏高" in s: return "🟠 偏高"
    if "合理" in s: return "🟡 合理"
    if "低估" in s: return "🟢 低估"
    return s


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    b = fetch_btcdca()
    etf = fetch_513300()
    nav, nd = fetch_nav()
    pe = fetch_ndx_pe()
    mg = fetch_marketgrep()
    wi = __import__("datetime").datetime.now().weekday()
    wk = round(MONTHLY_DCA / 4)

    # 溢率：保证价格和净值同一天
    today_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    if nd == today_str:
        # 净值是最新的，用实时价格
        price_for_prem = etf["price"]
        prem_label_prefix = "实时"
    else:
        # 净值是昨天的，用昨收价（同一天对比）
        price_for_prem = etf["prev_close"]
        prem_label_prefix = "昨日"

    if price_for_prem and nav:
        p = (price_for_prem - nav) / nav * 100
        if p > 8.5:      pl = f"🔴 极端({prem_label_prefix})"
        elif p > 5:      pl = f"🟡 偏高({prem_label_prefix})"
        elif p > 3:      pl = f"🟠 略高({prem_label_prefix})"
        elif p > 0:      pl = f"🟢 正常({prem_label_prefix})"
        else:            pl = f"🔵 折价({prem_label_prefix})"
    else:
        p, pl = None, "─"

    # DCA
    dca = round(wk * b["mult"]) if wi == DCA_WEEKDAY else 0
    if dca:
        if b["mult"] < 0.9:   tag = "🔴 减量"
        elif b["mult"] > 1.1: tag = "🟢 加量"
        else:                 tag = "✅ 正常"
        dl = f"{tag}定投 {dca} 元"
    else:
        dl = "非定投日"

    # PE
    pe_line = ""
    if pe and pe.get("f"):
        fpe, tpe = pe["f"], pe.get("t")
        gap = round((tpe / fpe - 1) * 100) if tpe else None
        if fpe < 22:   note = "偏低"
        elif fpe < 28: note = "适中"
        elif fpe < 35: note = "偏高"
        else:          note = "高估"
        pe_line = f"  📐 PE: Tr {tpe} | Fwd {fpe} ({note}，增长预期{gap}%)"

    dets = []
    if b.get("pe"):   dets.append(f"PE {b['pe']}")
    if b.get("vix"):  dets.append(f"VIX {b['vix']}")
    if b.get("fear") is not None: dets.append(f"恐慌 {b['fear']}")
    if b.get("rsi"):  dets.append(f"RSI {round(b['rsi'], 1)}")
    det_str = " | ".join(dets) if dets else ""

    lines = [
        "",
        "=" * 48,
        f"  📊 513300 日报",
        f"  📅 {__import__('datetime').datetime.now().strftime('%m-%d %H:%M')} ({WEEKDAY_CN[wi]})",
        "=" * 48,
        "",
        f"  🏷 {etf['name']}  现价 {etf['price'] or '─'}  净值 {nav or '─'}({nd or '─'})",
    ]
    if price_for_prem == etf["prev_close"] and etf["price"] != etf["prev_close"] and etf["price"]:
        # 用了昨收价，加一行实时价参考
        lines.append(f"     昨收 {etf['prev_close']}（用于溢率计算）  实时 {etf['price']}")
    if p is not None:
        lines.append(f"  溢率 {p:+.2f}%  {pl}")
    lines += [
        "",
        f"  🔗 btcdca: {b['score']}/100 {_sco(b['score'])}  {_status(b['status'])}  倍数 {b['mult']}x",
    ]
    if det_str:
        lines.append(f"  {det_str}")
    if pe_line:
        lines.append("")
        lines.append(pe_line)
    if mg and mg.get("line"):
        lines.append(f"  {mg['line']}")
    # 操作理由
    reasons = []
    if b["score"] is not None and b["score"] <= 50:
        reasons.append(f"btcdca评分{b['score']}/100偏高")
    elif b["score"] is not None and b["score"] >= 65:
        reasons.append(f"btcdca评分{b['score']}/100偏低")
    if p is not None and p > 5:
        reasons.append(f"溢率{p:.1f}%极端")
    elif p is not None and p < 0:
        reasons.append(f"溢率折价{p:.1f}%")
    reason_str = "，".join(reasons) if reasons else "信号中性"

    lines += [
        "",
        "=" * 48,
        "  💡 操作建议",
        "=" * 48,
        "",
        f"  ★ {dl}",
        f"     依据: {reason_str}",
        "",
        "─" * 48,
        f"  【周{wk}元 | 月{MONTHLY_DCA}元】",
        "─" * 48,
        "",
    ]
    print("\n".join(filter(None, lines)))
