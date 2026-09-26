"""纳指100回撤追踪 + 分仓加仓档位管理"""
import json
import httpx
from datetime import datetime, date
from pathlib import Path

# ─── 档位配置 ───
# (回撤%, 加仓金额, 从哪出钱)
DRAWDOWN_LEVELS = [
    (8,  300, "待命金"),   # 额外 1 个月进攻仓
    (15, 500, "待命金"),   # 额外 ~1.5 个月
    (22, 500, "待命金+风暴金"),
    (30, 500, "风暴金"),
    (40, 500, "风暴金"),
]

# ─── 每月资金分配 ───
MONTHLY_ATTACK  = 300   # 进攻仓（定投 513300）
MONTHLY_RESERVE = 150   # 待命金
MONTHLY_STORM   = 50    # 风暴金
MONTHLY_TOTAL   = MONTHLY_ATTACK + MONTHLY_RESERVE + MONTHLY_STORM

# ─── 状态文件 ───
STATE_FILE = Path(__file__).parent / "nasdaq_state.json"


def _default_state() -> dict:
    return {
        "reserve_balance": 0,       # 待命金余额
        "storm_balance": 0,         # 风暴金余额
        "triggered_levels": [],     # 已触发的档位 [8, 15, ...]
        "last_topup_month": "",     # 上次充值月份 "2026-04"
        "last_update": "",
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
        # 确保所有 key 存在
        for k, v in _default_state().items():
            state.setdefault(k, v)
        return state
    return _default_state()


def save_state(state: dict):
    state["last_update"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def monthly_topup(state: dict) -> bool:
    """每月初自动充值待命金+风暴金（幂等，每月只充一次）"""
    current_month = date.today().strftime("%Y-%m")
    if state["last_topup_month"] == current_month:
        return False
    state["reserve_balance"] += MONTHLY_RESERVE
    state["storm_balance"] += MONTHLY_STORM
    state["last_topup_month"] = current_month
    save_state(state)
    return True


def get_qqq_history() -> list[float]:
    """从 Yahoo Finance 获取 QQQ 近一年日收盘价"""
    headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://query1.finance.yahoo.com/v8/finance/chart/QQQ?range=1y&interval=1d"
    with httpx.Client(timeout=15, proxy="http://127.0.0.1:7890") as c:
        r = c.get(url, headers=headers)
        r.raise_for_status()
        closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    return [c for c in closes if c is not None]


def get_qqq_realtime() -> dict:
    """从腾讯获取 QQQ 实时价格"""
    with httpx.Client(timeout=10) as c:
        text = c.get("https://qt.gtimg.cn/q=usQQQ").text
    fields = text.split("~")
    return {
        "price": float(fields[3]),
        "prev_close": float(fields[4]),
        "change_pct": float(fields[31]) if len(fields) > 31 and fields[31] else 0,
    }


def calc_drawdown(closes: list[float]) -> dict:
    """计算当前回撤幅度"""
    if not closes:
        return {"high": 0, "current": 0, "drawdown_pct": 0, "high_date": ""}
    
    high = max(closes)
    current = closes[-1]
    drawdown = (current - high) / high * 100
    
    # 找高点日期（近似：用索引对应天数）
    high_idx = closes.index(high)
    
    return {
        "high": round(high, 2),
        "current": round(current, 2),
        "drawdown_pct": round(drawdown, 2),
        "high_index": high_idx,
        "days_since_high": len(closes) - 1 - high_idx,
    }


def calc_ma200_deviation(closes: list[float]) -> dict:
    """计算QQQ相对MA200的乖离率，用于止盈判断

    阈值：
      > 25% → 严重超买，卖出
      > 15% → 超买区域，关注/卖出
      > 5%  → 偏高，持有观望
      ≤ 5%  → 正常，不操作
    """
    if len(closes) < 200:
        return {"ma200": 0, "deviation_pct": 0, "signal": "数据不足"}

    ma200 = sum(closes[-200:]) / 200
    current = closes[-1]
    deviation = (current - ma200) / ma200 * 100

    if deviation > 25:
        signal = "🔴 严重超买"
    elif deviation > 15:
        signal = "⚠️ 超买关注"
    elif deviation > 5:
        signal = "🟡 偏高"
    else:
        signal = "🟢 正常"

    return {
        "ma200": round(ma200, 2),
        "deviation_pct": round(deviation, 2),
        "signal": signal,
    }


def get_sell_signal_status() -> str:
    """生成止盈信号报告（基于QQQ MA200乖离率）"""
    lines = []
    lines.append(f"\n{'─'*40}")
    lines.append("📈 纳指止盈信号（QQQ vs MA200）")
    lines.append(f"{'─'*40}")

    try:
        closes = get_qqq_history()
        dd = calc_drawdown(closes)
        dev = calc_ma200_deviation(closes)
    except Exception as e:
        return f"❌ 纳指数据获取失败: {e}"

    lines.append(f" QQQ 现价: ${dd['current']:.2f}")
    lines.append(f" MA200:    ${dev['ma200']:.2f}")
    lines.append(f" 乖离率:   {dev['deviation_pct']:+.2f}% → {dev['signal']}")

    # 操作建议
    pct = dev['deviation_pct']
    lines.append("")
    lines.append("📋 操作建议:")
    if pct > 25:
        lines.append("   🔴 严重超买，建议卖出 30% 仓位")
        lines.append("      若继续涨至 +35%: 再卖 20%")
    elif pct > 15:
        lines.append("   ⚠️  进入超买区域，建议卖出 30% 仓位")
        lines.append("      或等 +25% 再执行")
    elif pct > 5:
        lines.append("   🟡 偏高，持有观望，暂不操作")
    else:
        lines.append("   🟢 正常，不操作")

    lines.append("")
    lines.append("📌 联动说明:")
    lines.append("   止盈资金 → 入待命金")
    lines.append("   回撤触发 → drawdown 系统自动消耗")

    lines.append(f"{'─'*40}")
    return "\n".join(lines)


def check_triggers(drawdown_pct: float, state: dict) -> list[dict]:
    """检查当前回撤触发了哪些档位"""
    triggered = []
    already = set(state.get("triggered_levels", []))
    
    for level, amount, source in DRAWDOWN_LEVELS:
        if drawdown_pct <= -level and level not in already:
            triggered.append({
                "level": level,
                "amount": amount,
                "source": source,
            })
    return triggered


def consume_trigger(level: int, state: dict):
    """标记档位已使用"""
    if level not in state["triggered_levels"]:
        state["triggered_levels"].append(level)
        save_state(state)


def get_drawdown_status() -> str:
    """生成回撤状态报告"""
    lines = []
    
    try:
        closes = get_qqq_history()
        dd = calc_drawdown(closes)
        rt = get_qqq_realtime()
    except Exception as e:
        return f"❌ 纳指数据获取失败: {e}"
    
    state = load_state()
    monthly_topup(state)  # 每月初自动充值
    
    drawdown = dd["drawdown_pct"]
    
    lines.append(f"\n{'─'*40}")
    lines.append(f"📉 纳指100回撤追踪")
    lines.append(f"{'─'*40}")
    lines.append(f" QQQ 现价: ${rt['price']:.2f} ({rt['change_pct']:+.2f}%)")
    lines.append(f" 52周高点: ${dd['high']:.2f} ({dd['days_since_high']}天前)")
    lines.append(f" 当前回撤: {drawdown:+.2f}%")
    
    # 回撤档位进度条
    lines.append(f"\n📊 加仓档位:")
    for level, amount, source in DRAWDOWN_LEVELS:
        already = level in state.get("triggered_levels", [])
        triggered = drawdown <= -level
        marker = ""
        if already:
            marker = " ✅已用"
        elif triggered:
            marker = " 🔔触发！"
        
        progress = min(abs(drawdown) / level * 100, 100)
        bar_len = 15
        filled = int(progress / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        lines.append(f" -{level:>2}% [{bar}] {amount}元({source}){marker}")
    
    # 子弹余额
    lines.append(f"\n💰 子弹余额:")
    lines.append(f" 待命金: {state['reserve_balance']}元")
    lines.append(f" 风暴金: {state['storm_balance']}元")
    lines.append(f" 合计:   {state['reserve_balance'] + state['storm_balance']}元")
    
    # 触发提醒
    new_triggers = check_triggers(drawdown, state)
    if new_triggers:
        lines.append(f"\n🚨 回撤档位触发！")
        for t in new_triggers:
            lines.append(f" ⚡ 跌{t['level']}%: 从{t['source']}转{t['amount']}元加仓 513300")
    
    lines.append(f"{'─'*40}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_drawdown_status())
