"""
513300 纳斯达克ETF 每日巡检
数据源：新浪财经(K线) | 东方财富(净值) | 蛋卷(PE) | Yahoo Finance(QQQ/VIX)
"""

import sys
import json
import datetime
import urllib.request
import ast

# ============================================================
# 个人配置（每年校准一次，平时不改）
# ============================================================
MONTHLY_DCA  = 1000   # 每月定投总额（元）
DCA_WEEKDAY  = 2      # 定投日：0=周一 1=周二 2=周三 3=周四 4=周五
UNIT_SIZE    = MONTHLY_DCA * 2   # 1份 = 月定投×2，用于回调加仓
BULLET_STANDBY = 0    # 待命金余额（元），每次加仓后手动更新
BULLET_STORM   = 0    # 风暴金余额（元），同上

# 溢价率阈值
PREMIUM_WARN  = 0.03   # 溢价超过3%不买
PREMIUM_HALF  = 0.01   # 溢价1~3%半仓
# ============================================================

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _get(url, headers=None, encoding=None):
    h = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    return raw.decode(encoding) if encoding else raw


def _getj(url, headers=None):
    return json.loads(_get(url, headers))


# ── 数据抓取 ────────────────────────────────────────────────

def fetch_etf_kline(symbol="sh513300", days=300):
    """新浪财经：513300 日K线"""
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days}"
    )
    raw = _get(url, {"Referer": "https://finance.sina.com.cn/"}, encoding="gbk")
    return [
        {
            "date":  k["day"],
            "open":  float(k["open"]),
            "close": float(k["close"]),
            "high":  float(k["high"]),
            "low":   float(k["low"]),
        }
        for k in ast.literal_eval(raw)
    ]


def fetch_etf_nav():
    """东方财富：513300 最新净值（用于溢价率计算）"""
    url = (
        "https://api.fund.eastmoney.com/f10/lsjz"
        "?fundCode=513300&pageIndex=1&pageSize=1&startDate=&endDate=&_=1"
    )
    d = _getj(url, {"Referer": "https://fund.eastmoney.com/513300.html",
                    "Accept": "application/json, text/javascript"})
    lst = d.get("Data", {}).get("LSJZList", [])
    if lst:
        return {"nav": float(lst[0]["DWJZ"]), "nav_date": lst[0]["FSRQ"]}
    return {"nav": None, "nav_date": None}


def fetch_qqq_data():
    """Yahoo Finance：QQQ 日线（2年），计算 MA5/10/20/200 及52周高点"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range=2y"
    d = _getj(url)
    closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
    def ma(n):
        return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None
    price   = round(closes[-1], 2)
    ma200   = ma(200)
    hi52    = round(max(closes[-252:]), 2) if len(closes) >= 252 else round(max(closes), 2)
    dev200  = round((price - ma200) / ma200 * 100, 2) if ma200 else None
    dd52    = round((price - hi52)  / hi52  * 100, 2)
    return {
        "qqq":    price,
        "ma5":    ma(5),
        "ma10":   ma(10),
        "ma20":   ma(20),
        "ma200":  ma200,
        "hi52":   hi52,
        "dd52":   dd52,
        "dev200": dev200,
    }


def fetch_vix():
    """Yahoo Finance：VIX"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
    d = _getj(url)
    closes = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    for v in reversed(closes):
        if v is not None:
            return round(v, 2)
    return None


def fetch_ndx_pe():
    """蛋卷：NDX TTM PE，估算 Forward PE（基于10年历史EPS增速15%）"""
    G = 0.15
    url = "https://danjuanfunds.com/djapi/index_eva/dj?p=1&size=200"
    d = _getj(url, {"Referer": "https://danjuanfunds.com/"})
    for item in d.get("data", {}).get("items", []):
        if item.get("index_code") == "NDX":
            pe = item.get("pe")
            if pe and pe > 0:
                return {"pe_ttm": round(pe, 2), "pe_fwd": round(pe / (1 + G), 2)}
    return {"pe_ttm": None, "pe_fwd": None}


# ── 指标计算 ────────────────────────────────────────────────

def calc_ma(closes, n):
    return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None


def calc_ma_slope(closes, n, lb=5):
    if len(closes) < n + lb:
        return "未知"
    now  = sum(closes[-n:]) / n
    prev = sum(closes[-(n + lb):-lb]) / n
    d = now - prev
    if d >  now * 0.001: return "向上"
    if d < -now * 0.001: return "向下"
    return "横盘"


def calc_high_120(data):
    recent = data[-120:] if len(data) >= 120 else data
    h120   = max(d["high"] for d in recent[:-1])
    cur    = data[-1]["close"]
    return h120, round((cur - h120) / h120 * 100, 2), cur >= h120


def calc_peak_drawdown(closes, lookback=252):
    recent = closes[-lookback:] if len(closes) >= lookback else closes
    peak   = max(recent)
    return peak, round((closes[-1] - peak) / peak * 100, 2)


# ── 快照组装 ────────────────────────────────────────────────

def get_snapshot():
    print("📡 抓取 513300 K线...")
    kline  = fetch_etf_kline()
    closes = [d["close"] for d in kline]
    latest = kline[-1]

    ma5   = calc_ma(closes, 5)
    ma10  = calc_ma(closes, 10)
    ma20  = calc_ma(closes, 20)
    ma60  = calc_ma(closes, 60)
    ma60s = calc_ma_slope(closes, 60)
    h120, pct120, is_hi = calc_high_120(kline)
    peak, dd = calc_peak_drawdown(closes)

    print("📡 抓取 513300 净值...")
    try:
        nav_d = fetch_etf_nav()
    except Exception as e:
        print(f"  净值失败: {e}")
        nav_d = {"nav": None, "nav_date": None}

    print("📡 抓取 QQQ 数据...")
    try:
        qqq = fetch_qqq_data()
    except Exception as e:
        print(f"  QQQ失败: {e}")
        qqq = {k: None for k in ["qqq","ma5","ma10","ma20","ma200","hi52","dd52","dev200"]}

    print("📡 抓取 VIX...")
    try:
        vix = fetch_vix()
    except Exception as e:
        print(f"  VIX失败: {e}")
        vix = None

    print("📡 抓取 NDX PE...")
    try:
        pe = fetch_ndx_pe()
    except Exception as e:
        print(f"  PE失败: {e}")
        pe = {"pe_ttm": None, "pe_fwd": None}

    # 溢价率
    premium = None
    if nav_d["nav"] and latest["close"]:
        premium = round((latest["close"] - nav_d["nav"]) / nav_d["nav"], 4)

    return {
        "date":      latest["date"],
        "price":     latest["close"],
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ma60_slope": ma60s,
        "h120": h120, "pct120": pct120, "is_hi120": is_hi,
        "peak": peak, "drawdown": dd,
        "nav":       nav_d["nav"],
        "nav_date":  nav_d["nav_date"],
        "premium":   premium,
        "qqq":       qqq,
        "vix":       vix,
        "pe_ttm":    pe["pe_ttm"],
        "pe_fwd":    pe["pe_fwd"],
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ── 决策引擎 ────────────────────────────────────────────────

def make_decision(s):
    today    = datetime.date.today()
    dd       = abs(s["drawdown"])
    fpe      = s.get("pe_fwd")
    premium  = s.get("premium")
    weekly   = round(MONTHLY_DCA / 4)

    # 1. 定投
    is_dca = today.weekday() == DCA_WEEKDAY
    if not is_dca:
        dca_action = f"非定投日，不操作"
        dca_amount = 0
    elif premium is not None and premium > PREMIUM_WARN:
        dca_action = f"定投日但溢价{premium*100:.1f}%>3%，🚫 暂停定投"
        dca_amount = 0
    elif premium is not None and premium > PREMIUM_HALF:
        dca_action = f"定投日，溢价{premium*100:.1f}%，半仓定投 {weekly//2} 元"
        dca_amount = weekly // 2
    else:
        dca_action = f"执行定投 {weekly} 元"
        dca_amount = weekly

    # 2. 波段仓
    cond_a = bool(s["ma20"] and s["ma60"] and s["ma20"] > s["ma60"] and s["ma60_slope"] == "向上")
    cond_b = s["is_hi120"]
    if cond_a and cond_b:
        if fpe and fpe >= 35:   wave_t, wave_n = 20, "PE高估，压至20%"
        elif fpe and fpe >= 30: wave_t, wave_n = 25, "PE偏高，降5%至25%"
        else:                   wave_t, wave_n = 30, "趋势确认，目标30%"
        trend_s = "A+B满足 ⚠️ 需确认条件C（突破后5日不跌破-2%）"
    elif cond_a:
        wave_t, wave_n = 15, "未创120日新高，维持15%"
        trend_s = "仅A满足，待突破"
    else:
        wave_t, wave_n = 0, "趋势不成立，转现金"
        trend_s = "条件A不满足"

    # 3. 回调加仓
    tiers = [(-10, 1), (-20, 2), (-30, 3), (-40, 1)]  # (阈值, 份数)
    add_units = 0
    add_tier  = 0
    for i, (thresh, units) in enumerate(tiers):
        if dd >= abs(thresh):
            add_units = units
            add_tier  = i + 1
    if fpe and fpe >= 35 and add_units > 0:
        add_units = max(1, add_units // 2)

    # 4. QQQ止盈
    dev200 = s["qqq"].get("dev200") if s.get("qqq") else None
    if dev200 is None:          tp = "数据缺失"
    elif dev200 > 20:           tp = f"🔴 乖离{dev200}%，考虑止盈波段仓"
    elif dev200 > 12:           tp = f"🟡 乖离{dev200}%，偏高，持有观望"
    elif dev200 > 0:            tp = f"🟢 乖离{dev200}%，正常"
    else:                       tp = f"🔵 价格低于MA200，熊市信号"

    # 汇总
    ops = []
    if dca_amount > 0:   ops.append(f"定投{dca_amount}元")
    if add_units  > 0:   ops.append(f"加仓{add_units}份({add_units*UNIT_SIZE}元)")
    if not ops:          ops.append("无需操作，持仓观察")

    return {
        "dca_action": dca_action, "dca_amount": dca_amount, "weekly": weekly,
        "wave_target": wave_t, "wave_note": wave_n, "trend_status": trend_s,
        "add_tier": add_tier, "add_units": add_units, "add_amount": add_units * UNIT_SIZE,
        "tp_signal": tp,
        "summary": "、".join(ops),
    }


# ── 格式化输出 ───────────────────────────────────────────────

def _bar(pct, total=40, filled="▓", empty="░"):
    """回撤进度条，pct 为正数百分比"""
    n = min(int(pct / total * 15), 15)
    return filled * n + empty * (15 - n)


def _pe_temp(fpe):
    if fpe is None:    return "未知"
    if fpe < 22:       return "🔵 偏低"
    if fpe < 30:       return "🟢 正常"
    if fpe < 35:       return "🟡 偏高"
    if fpe < 40:       return "🟠 高估"
    return             "🔴 泡沫"


def _trend_icon(s):
    ma20, ma60 = s.get("ma20"), s.get("ma60")
    if ma20 and ma60:
        if ma20 > ma60: return "📈 多头排列"
        return              "📉 空头排列"
    return "─"


def format_output(s, d):
    q   = s.get("qqq") or {}
    dd  = abs(s["drawdown"])
    fpe = s.get("pe_fwd")
    nav = s.get("nav")
    prem = s.get("premium")
    prem_str = f"{prem*100:+.2f}%" if prem is not None else "未知"
    prem_icon = ("🚫 溢价过高" if prem and prem > PREMIUM_WARN
                 else "⚠️ 溢价偏高" if prem and prem > PREMIUM_HALF
                 else "✅ 正常" if prem is not None else "─")

    dca_icon = "★" if d["dca_amount"] > 0 else "○"
    add_icon = "★" if d["add_units"] > 0 else "○"

    lines = [
        "",
        "=" * 48,
        f"  📊 513300 早盘简报",
        f"  📅 {s['fetched_at']}  ({WEEKDAY_CN[datetime.date.today().weekday()]})",
        "=" * 48,
        "",
        f"  🏷  纳斯达克ETF华夏 (513300)",
        f"  昨收: {s['price']}    净值: {nav or '─'} ({s['nav_date'] or '─'})",
        f"  溢价: {prem_str}  →  {prem_icon}",
        "",
        f"  📐 均线 (513300)",
        f"  MA5:{s['ma5']}  MA10:{s['ma10']}  MA20:{s['ma20']}  MA60:{s['ma60']}",
        f"  趋势: {_trend_icon(s)}  |  MA60斜率: {s['ma60_slope']}",
        "",
        "─" * 48,
        f"  📈 纳指100 (QQQ)",
        f"  现价: ${q.get('qqq','─')}    MA200: ${q.get('ma200','─')}",
        f"  MA5:{q.get('ma5','─')}  MA10:{q.get('ma10','─')}  MA20:{q.get('ma20','─')}",
        f"  52周高: ${q.get('hi52','─')}  回撤: {q.get('dd52','─')}%",
        f"  MA200乖离: {q.get('dev200','─')}%  →  {d['tp_signal']}",
        "",
        f"  🌡 估值温度: TTM PE {s['pe_ttm'] or '─'} | Fwd PE {fpe or '─'}  {_pe_temp(fpe)}",
        f"  😰 VIX: {s['vix'] or '─'}",
        "",
        "=" * 48,
        f"  💡 今日操作建议  (定投日: 每{WEEKDAY_CN[DCA_WEEKDAY]})",
        "=" * 48,
        "",
        f"  {dca_icon} 定投（核心仓）",
        f"     {d['dca_action']}",
        "",
        f"  ○ 波段仓",
        f"     趋势: {d['trend_status']}",
        f"     目标: {d['wave_target']}%  —  {d['wave_note']}",
        "",
        f"  {add_icon} 回调加仓追踪",
    ]

    # 回撤进度条
    tiers = [
        ( 8, UNIT_SIZE,      "待命金"),
        (15, UNIT_SIZE,      "待命金"),
        (22, UNIT_SIZE,      "待命金+风暴金"),
        (30, UNIT_SIZE,      "风暴金"),
        (40, UNIT_SIZE,      "风暴金"),
    ]
    for thresh, amt, label in tiers:
        hit = dd >= thresh
        icon = "🔥" if hit else "  "
        bar  = _bar(dd, total=50)
        lines.append(f"  {icon} -{thresh:2d}% [{bar}] {amt}元 ({label})")

    bullet_total = BULLET_STANDBY + BULLET_STORM
    lines += [
        "",
        f"  💰 子弹余额: 待命金 {BULLET_STANDBY}元 | 风暴金 {BULLET_STORM}元 | 合计 {bullet_total}元",
        "",
        "─" * 48,
        f"  【今日总结】 {d['summary']}",
        f"  【单位金额】 1份={UNIT_SIZE}元 | 周定投={d['weekly']}元 | 月定投={MONTHLY_DCA}元",
        "─" * 48,
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s = get_snapshot()
    d = make_decision(s)
    print(format_output(s, d))
