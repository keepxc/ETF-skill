"""
513300 纳斯达克ETF 每日市场数据抓取 + 操作决策
数据源：新浪财经（K线+MA），蛋卷（PE），Yahoo Finance（VIX）
"""

# ============================================================
# 个人配置（每年校准一次，平时不改）
# ============================================================
MONTHLY_DCA = 1000          # 每月定投总额（元）
DCA_WEEKDAY = 2             # 每周定投日：0=周一 1=周二 2=周三 3=周四 4=周五
# 1份 = 月定投 × 2（按 V1.2 设计：用于回调加仓单位）
UNIT_SIZE = MONTHLY_DCA * 2
# 条件C：突破后5日确认窗口（天）
TREND_CONFIRM_DAYS = 5
# ============================================================

import json
import time
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _make_session():
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


SESSION = _make_session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/sh513300.html",
    "Accept": "application/json",
}


def _urlopen_raw(url, headers=None):
    """返回原始 bytes"""
    import urllib.request
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _urlopen(url, headers=None):
    """返回解析后的 JSON"""
    return json.loads(_urlopen_raw(url, headers))


def fetch_etf_data(symbol="sh513300", days=300):
    """从新浪财经抓取ETF历史日K线"""
    import ast
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days}"
    )
    raw = _urlopen_raw(url, {"Referer": "https://finance.sina.com.cn/"})
    klines = ast.literal_eval(raw.decode("gbk"))
    return [
        {
            "date": k["day"],
            "open": float(k["open"]),
            "close": float(k["close"]),
            "high": float(k["high"]),
            "low": float(k["low"]),
        }
        for k in klines
    ]


def calc_ma(closes, n):
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 4)


def calc_ma_slope(closes, n, lookback=5):
    """MA斜率：比较当前MA和N日前的MA"""
    if len(closes) < n + lookback:
        return "未知"
    ma_now = sum(closes[-n:]) / n
    ma_prev = sum(closes[-(n + lookback):-lookback]) / n
    diff = ma_now - ma_prev
    if diff > ma_now * 0.001:
        return "向上"
    elif diff < -ma_now * 0.001:
        return "向下"
    return "横盘"


def calc_high_120(data):
    """计算120日最高价，判断当前是否为新高"""
    if len(data) < 2:
        return None, None
    recent = data[-120:] if len(data) >= 120 else data
    high_120 = max(d["high"] for d in recent[:-1])  # 排除今天
    current = data[-1]["close"]
    is_new_high = current >= high_120
    pct_from_high = round((current - high_120) / high_120 * 100, 2)
    return high_120, pct_from_high, is_new_high


def fetch_vix():
    """从Yahoo Finance抓取VIX（使用urllib绕过系统代理限制）"""
    import urllib.request
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    # 取最后一个非None值
    for v in reversed(closes):
        if v is not None:
            return round(v, 2)
    return None


def fetch_ndx_pe():
    """
    从蛋卷获取 NDX TTM PE，并估算 Forward PE。
    Forward PE 算法：
      - TTM EPS = NDX点位 / TTM_PE（蛋卷）
      - 用 Nasdaq 100 过去10年平均EPS增速作为 Forward 增速预期（约15%）
      - Forward PE = TTM PE / (1 + EPS_GROWTH_ESTIMATE)
    局限：EPS增速用历史均值近似，非分析师共识，属估算。
    """
    NDX_EPS_GROWTH_ESTIMATE = 0.15  # Nasdaq 100 十年平均EPS年增速

    url = "https://danjuanfunds.com/djapi/index_eva/dj?p=1&size=200"
    try:
        data = _urlopen(url, {"Referer": "https://danjuanfunds.com/"})
        items = data.get("data", {}).get("items", [])
        for item in items:
            if item.get("index_code") == "NDX":
                pe_ttm = item.get("pe")
                if pe_ttm and pe_ttm > 0:
                    pe_forward = round(pe_ttm / (1 + NDX_EPS_GROWTH_ESTIMATE), 2)
                    return {
                        "pe_ttm": round(pe_ttm, 2),
                        "pe_forward_est": pe_forward,
                        "pe_forward_growth_assumption": NDX_EPS_GROWTH_ESTIMATE,
                    }
    except Exception as e:
        print(f"  PE抓取失败: {e}")
    return {"pe_ttm": None, "pe_forward_est": None, "pe_forward_growth_assumption": NDX_EPS_GROWTH_ESTIMATE}


def calc_drawdown_from_peak(closes, lookback=252):
    """计算距近1年高点的回撤"""
    recent = closes[-lookback:] if len(closes) >= lookback else closes
    peak = max(recent)
    current = closes[-1]
    drawdown = round((current - peak) / peak * 100, 2)
    return peak, drawdown


def get_market_snapshot():
    """主函数：返回完整市场快照"""
    print("正在抓取 513300 历史数据...")
    data = fetch_etf_data(days=300)
    closes = [d["close"] for d in data]
    latest = data[-1]

    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    ma60_slope = calc_ma_slope(closes, 60)
    high_120, pct_from_high, is_new_high = calc_high_120(data)
    peak, drawdown = calc_drawdown_from_peak(closes)

    print("正在抓取 VIX...")
    try:
        vix = fetch_vix()
    except Exception as e:
        vix = None
        print(f"  VIX抓取失败: {e}")

    print("正在抓取 NDX PE...")
    pe_data = fetch_ndx_pe()

    snapshot = {
        "date": latest["date"],
        "price": latest["close"],
        "ma20": ma20,
        "ma60": ma60,
        "ma60_slope": ma60_slope,
        "high_120": high_120,
        "pct_from_high_120": pct_from_high,
        "is_new_high_120": is_new_high,
        "peak_1y": peak,
        "drawdown_from_peak": drawdown,
        "vix": vix,
        "pe_ttm": pe_data["pe_ttm"],
        "pe_forward_est": pe_data["pe_forward_est"],
        "pe_forward_note": f"估算（TTM PE / 1.{int(pe_data['pe_forward_growth_assumption']*100)}，基于NDX历史EPS增速{int(pe_data['pe_forward_growth_assumption']*100)}%）",
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return snapshot


WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def make_decision(s):
    """
    根据市场快照输出操作决策。
    返回 dict，包含各仓位建议和汇总。
    """
    today = datetime.date.today()
    drawdown = abs(s["drawdown_from_peak"])  # 正数，如 12.5
    fpe = s.get("pe_forward_est")

    # ── 1. 定投决策 ──────────────────────────────────────────
    weekly_dca = round(MONTHLY_DCA / 4)
    is_dca_day = (today.weekday() == DCA_WEEKDAY)
    dca = {
        "is_dca_day": is_dca_day,
        "weekday": WEEKDAY_CN[DCA_WEEKDAY],
        "amount": weekly_dca,
        "action": f"执行定投 {weekly_dca} 元（核心仓）" if is_dca_day else "非定投日，无需操作",
    }

    # ── 2. 波段仓决策 ─────────────────────────────────────────
    cond_a = bool(
        s["ma20"] and s["ma60"]
        and s["ma20"] > s["ma60"]
        and s["ma60_slope"] == "向上"
    )
    cond_b = s["is_new_high_120"]

    if cond_a and cond_b:
        trend_status = "确认（条件A+B满足，需人工确认条件C）"
        # 估值调整
        if fpe and fpe >= 35:
            wave_target = 20
            wave_note = "Forward PE偏高，波段仓压至20%"
        elif fpe and fpe >= 30:
            wave_target = 25
            wave_note = "Forward PE偏高，波段仓降5%至25%"
        else:
            wave_target = 30
            wave_note = "趋势确认，波段仓目标30%"
    elif cond_a:
        trend_status = "待确认（条件A满足，条件B未满足：未创120日新高）"
        wave_target = 15
        wave_note = "趋势未完全确认，波段仓维持15%"
    else:
        trend_status = "不成立（条件A不满足）"
        wave_target = 0
        wave_note = "趋势不成立，波段仓降至0%，资金转现金仓"

    wave = {
        "trend_status": trend_status,
        "target_pct": wave_target,
        "note": wave_note,
    }

    # ── 3. 回调加仓决策 ──────────────────────────────────────
    # 累计暴露上限30%，每档加仓不超限
    if drawdown < 10:
        add_tier = 0
        add_units = 0
        add_note = "回撤不足10%，无回调加仓"
    elif drawdown < 20:
        add_tier = 1
        add_units = 1
        add_note = f"回撤{drawdown:.1f}%，触发第1档，加1份（{UNIT_SIZE}元）"
    elif drawdown < 30:
        add_tier = 2
        add_units = 2
        add_note = f"回撤{drawdown:.1f}%，触发第2档，加2份（{UNIT_SIZE*2}元）"
    elif drawdown < 40:
        add_tier = 3
        add_units = 3
        add_note = f"回撤{drawdown:.1f}%，触发第3档，加3份（{UNIT_SIZE*3}元）"
    else:
        add_tier = 4
        add_units = 1  # 封顶：1~2份弹性
        add_note = f"回撤{drawdown:.1f}%，进入封顶区（40%+），弹性加1份（{UNIT_SIZE}元），累计暴露勿超30%"

    # 估值高估时加仓减半
    if fpe and fpe >= 35 and add_units > 0:
        add_units = max(1, add_units // 2)
        add_note += f"  ⚠️ Forward PE偏高，加仓减半至{add_units}份"

    adding = {
        "tier": add_tier,
        "units": add_units,
        "amount": add_units * UNIT_SIZE,
        "note": add_note,
    }

    # ── 4. 汇总今日操作 ──────────────────────────────────────
    actions = []
    if is_dca_day:
        actions.append(f"定投 {weekly_dca} 元")
    if add_units > 0:
        actions.append(f"回调加仓 {add_units} 份（{add_units * UNIT_SIZE} 元）")
    if not actions:
        actions.append("无需操作，持仓观察")

    return {
        "dca": dca,
        "wave": wave,
        "adding": adding,
        "summary": "、".join(actions),
    }


def format_snapshot(s):
    trend_a = "✅" if s["ma20"] and s["ma60"] and s["ma20"] > s["ma60"] else "❌"
    trend_a2 = "✅" if s["ma60_slope"] == "向上" else ("⚠️" if s["ma60_slope"] == "横盘" else "❌")
    trend_b = "✅ 已创新高" if s["is_new_high_120"] else f"❌ 距120日高点 {s['pct_from_high_120']}%"
    vix_str = f"{s['vix']}" if s["vix"] else "未获取"
    drawdown_str = f"{s['drawdown_from_peak']}%"

    pe_ttm_str = f"{s['pe_ttm']}" if s["pe_ttm"] else "未获取"
    pe_fwd_str = f"{s['pe_forward_est']}（{s['pe_forward_note']}）" if s["pe_forward_est"] else "未获取"

    # 估值温度判断（基于 Forward PE）
    fpe = s.get("pe_forward_est")
    if fpe:
        if fpe < 22:
            temp = "偏低 | 可提高风险预算"
        elif fpe < 30:
            temp = "正常 | 按基准执行"
        elif fpe < 35:
            temp = "偏高 | 波段仓降5%"
        elif fpe < 40:
            temp = "高估 | 波段仓降至20%，加仓减半"
        else:
            temp = "泡沫警示 | 波段仓20%，加仓0.5份"
    else:
        temp = "未知"

    lines = [
        "=" * 52,
        f"  513300 纳斯达克ETF 市场快照",
        f"  抓取时间：{s['fetched_at']}",
        "=" * 52,
        f"  价格：{s['price']}  MA20：{s['ma20']}  MA60：{s['ma60']}",
        f"",
        f"  【趋势（V1.3）】",
        f"  {trend_a} MA20>MA60  {trend_a2} MA60{s['ma60_slope']}  {trend_b}",
        f"",
        f"  【回撤】距近1年高点（{s['peak_1y']}）：{drawdown_str}",
        f"",
        f"  【估值温度】TTM PE {pe_ttm_str} | Forward PE {s.get('pe_forward_est','未知')}  →  {temp}",
        f"  【VIX】{vix_str}",
        "=" * 52,
    ]
    return "\n".join(lines)


def format_decision(d):
    """将决策结果格式化为可读文本"""
    dca = d["dca"]
    wave = d["wave"]
    adding = d["adding"]

    dca_icon = "★" if dca["is_dca_day"] else "○"
    add_icon = "★" if adding["units"] > 0 else "○"

    lines = [
        "",
        "=" * 52,
        f"  今日操作建议（定投日：每{dca['weekday']}）",
        "=" * 52,
        f"",
        f"  {dca_icon} 定投（核心仓，每周固定）",
        f"     {dca['action']}",
        f"",
        f"  ○ 波段仓状态",
        f"     趋势：{wave['trend_status']}",
        f"     目标仓位：{wave['target_pct']}%  —  {wave['note']}",
        f"",
        f"  {add_icon} 回调加仓",
        f"     {adding['note']}",
        f"",
        "─" * 52,
        f"  【今日总结】{d['summary']}",
        f"  【参考金额】1份 = {UNIT_SIZE}元  |  月定投 = {MONTHLY_DCA}元  |  周定投 = {dca['amount']}元",
        "─" * 52,
        f"  ⚠️  条件C（突破后5日未跌破-2%）需人工确认",
        "=" * 52,
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    snapshot = get_market_snapshot()
    decision = make_decision(snapshot)
    print(format_snapshot(snapshot))
    print(format_decision(decision))
