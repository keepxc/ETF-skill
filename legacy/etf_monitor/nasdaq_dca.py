"""纳斯达克100 ETF 定投策略模块 — 分仓加仓 + 溢价控制 + 回撤档位"""
import httpx
import re
import json
from datetime import datetime, date
from pathlib import Path

# ─── 基金配置 ───
FUND_CODE = "513300"
FUND_NAME = "纳斯达克ETF华夏"
FUND_MARKET = "sh"

# ─── 溢价阈值 ───
PREMIUM_BUY     = 3.0   # 溢价 > 3%：不买
PREMIUM_CAUTION = 1.0   # 溢价 1-3%：谨慎买半份
# 溢价 < 1%：正常买入

# ─── 定投参数（双周定投）───
DCA_DAY = 2              # 0=Mon, 2=Wed
DCA_BIWEEKLY = 500       # 每次定投额（双周，每月约1000元）

# ─── 分仓参数（保留，用于回撤加仓）───
MONTHLY_ATTACK  = 1000   # 进攻仓/月（双周500×2）
MONTHLY_RESERVE = 0      # 待命金/月（已并入定投）
MONTHLY_STORM   = 0      # 风暴金/月

STATE_FILE = Path(__file__).parent / "nasdaq_state.json"


def _get_json(url: str) -> dict:
    with httpx.Client(timeout=10) as c:
        return c.get(url).json()


def _get_text(url: str) -> str:
    with httpx.Client(timeout=10) as c:
        return c.get(url).text


def get_realtime() -> dict:
    """获取513300实时行情（腾讯接口）"""
    url = f"https://qt.gtimg.cn/q={FUND_MARKET}{FUND_CODE}"
    text = _get_text(url)
    fields = text.split("~")

    amount = 0
    for f in fields:
        parts = f.split("/")
        if len(parts) == 3:
            try:
                amount = float(parts[2])
                break
            except ValueError:
                continue

    return {
        "code": fields[2],
        "name": fields[1],
        "price": float(fields[3]),
        "prev_close": float(fields[4]),
        "open": float(fields[5]),
        "volume": int(fields[6]) if fields[6] else 0,
        "high": float(fields[33]) if len(fields) > 33 and fields[33] else float(fields[3]),
        "low": float(fields[34]) if len(fields) > 34 and fields[34] else float(fields[3]),
        "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] else 0,
        "amount": amount,
    }


def get_nav() -> dict:
    """获取513300最新净值（东方财富接口）"""
    url = f"https://fundgz.1234567.com.cn/js/{FUND_CODE}.js"
    text = _get_text(url)
    m = re.search(r'\((\{.*?\})\)', text)
    if m:
        data = json.loads(m.group(1))
        return {
            "code": data["fundcode"],
            "name": data["name"],
            "nav_date": data["jzrq"],
            "nav": float(data["dwjz"]),
            "est_nav": float(data["gsz"]),
            "est_change_pct": float(data["gszzl"]),
        }
    return {}


def get_data() -> dict:
    """获取513300实时数据 + 净值 + 溢价率"""
    rt = get_realtime()
    nav_data = get_nav()
    nav = nav_data.get("nav", 0)
    premium = ((rt["price"] - nav) / nav * 100) if nav else 0
    return {
        "code": FUND_CODE,
        "name": FUND_NAME,
        "price": rt["price"],
        "prev_close": rt["prev_close"],
        "change_pct": rt["change_pct"],
        "volume": rt["volume"],
        "amount": rt["amount"],
        "nav": nav,
        "nav_date": nav_data.get("nav_date", ""),
        "premium_pct": premium,
    }


def premium_verdict(premium: float) -> str:
    """根据溢价率给出操作判断"""
    if premium > PREMIUM_BUY:
        return "🚫 不买（溢价过高）"
    elif premium > PREMIUM_CAUTION:
        return "⚠️ 谨慎（溢价偏高）"
    elif premium > 0:
        return "✅ 可买（溢价合理）"
    else:
        return "🔥 折价！可加倍"


def is_dca_day() -> tuple[bool, str]:
    """判断今天是否是定投日（每月第2、4个周三）"""
    today = date.today()
    weekday = today.strftime("%A")
    is_wed = today.weekday() == 2
    # 每月第2个周三 (8~14) 或第4个周三 (22~28)
    is_dca = is_wed and (8 <= today.day <= 14 or 22 <= today.day <= 28)
    if is_dca:
        info = "定投日✅"
    elif is_wed:
        info = "周三但非定投周"
    else:
        info = "非定投日"
    return is_dca, f"今天{weekday}（{info}）"


def load_state() -> dict:
    from nasdaq_drawdown import load_state as _load, _default_state
    return _load()


def dca_recommendation(d: dict) -> str:
    """生成定投操作建议（含分仓 + 回撤档位）"""
    today = date.today()
    is_dca, day_info = is_dca_day()

    lines = []
    lines.append(f"\n{'='*40}")
    lines.append(f"💰 513300 定投策略")
    lines.append(f"📅 {today.strftime('%Y-%m-%d')} {day_info}")
    lines.append(f"{'='*40}")

    if "error" in d:
        lines.append(f"❌ 数据获取失败: {d['error']}")
        return "\n".join(lines)

    premium = d.get("premium_pct", 0)
    verdict = premium_verdict(premium)

    lines.append(f"\n🏷 {d['name']} ({d['code']})")
    lines.append(f"   现价: {d['price']:.3f}")
    lines.append(f"   净值: {d.get('nav', 0):.4f} ({d.get('nav_date', '')})")
    lines.append(f"   溢价: {premium:+.2f}% → {verdict}")

    # 操作建议
    lines.append(f"\n📋 今日操作:")
    if not is_dca:
        lines.append(f"   非定投日，不操作")
        # 计算下次定投日
        today_d = today.day
        if today_d < 8:
            lines.append(f"   下次定投: 本月第2个周三")
        elif today_d < 22:
            lines.append(f"   下次定投: 本月第4个周三")
        else:
            lines.append(f"   下次定投: 下月第2个周三")
    else:
        if premium > PREMIUM_BUY:
            lines.append(f"   溢价 {premium:.1f}% > {PREMIUM_BUY}%")
            lines.append(f"   ❌ 不买")
        elif premium > PREMIUM_CAUTION:
            lines.append(f"   溢价 {premium:.1f}% 偏高")
            half = DCA_BIWEEKLY // 2
            lines.append(f"   ⚠️ 买半仓: {half}元")
            shares = int(half / d['price'] / 100) * 100
            if shares < 100:
                shares = 100
            cost = shares * d['price']
            lines.append(f"   约买 {shares} 份 ≈ {cost:.0f} 元")
        else:
            lines.append(f"   溢价 {premium:.1f}% 合理")
            lines.append(f"   ✅ 全仓买入 {DCA_BIWEEKLY}元")
            shares = int(DCA_BIWEEKLY / d['price'] / 100) * 100
            if shares < 100:
                shares = 100
            cost = shares * d['price']
            lines.append(f"   约买 {shares} 份 ≈ {cost:.0f} 元")

# 定投计划
    lines.append(f"\\n📊 定投计划:")
    lines.append(f"   双周定投 500元/次（每月约1000元）")
    lines.append(f"   溢价 小于1% 全仓 | 1-3% 半仓 | 大于3% 不买")

    lines.append(f"{'='*40}\n")
    return "\n".join(lines)
