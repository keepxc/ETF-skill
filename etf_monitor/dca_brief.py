#!/usr/bin/env python3
"""纳指定投策略早盘简报 — 工作日 8:30 运行（含回撤追踪 + 分仓加仓）"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from etf513300 import realtime as rt_513300, klines, ma
from nasdaq_dca import get_data, dca_recommendation
from nasdaq_drawdown import get_drawdown_status, get_sell_signal_status


def main():
    now = datetime.now()
    print(f"\n{'='*40}")
    print(f"📊 513300 早盘简报")
    print(f"📅 {now.strftime('%Y-%m-%d %H:%M')} (工作日)")
    print(f"{'='*40}")

    # 行情
    try:
        rt = rt_513300()
        print(f"\n🏷 {rt['name']} ({rt['code']})")
        print(f"   昨收: {rt['prev_close']:.3f}")
    except Exception as e:
        print(f"❌ 513300数据获取失败: {e}")
        rt = None

    try:
        kl = klines(20)
    except Exception:
        kl = None

    if kl:
        last = kl[-1]
        prev_close = kl[-2]["close"] if len(kl) >= 2 else last["open"]
        chg = (last["close"] / prev_close - 1) * 100
        print(f"📈 昨日收盘: {last['close']:.3f}  ({chg:+.2f}%)")

        ma5 = ma(kl, 5)
        ma10 = ma(kl, 10)
        ma20 = ma(kl, 20)
        print(f"\n📐 均线:")
        if ma5:  print(f"   MA5:  {ma5:.3f}")
        if ma10: print(f"   MA10: {ma10:.3f}")
        if ma20: print(f"   MA20: {ma20:.3f}")

        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                trend = "📈 多头排列"
            elif ma5 < ma10 < ma20:
                trend = "📉 空头排列"
            else:
                trend = "⚖️ 震荡整理"
            print(f"   趋势: {trend}")

    # 定投建议
    try:
        data = get_data()
        print(dca_recommendation(data))
    except Exception as e:
        print(f"❌ 定投数据获取失败: {e}")

    # 纳指回撤追踪
    try:
        print(get_drawdown_status())
    except Exception as e:
        print(f"❌ 回撤数据获取失败: {e}")

    # 纳指止盈信号
    try:
        print(get_sell_signal_status())
    except Exception as e:
        print(f"❌ 止盈数据获取失败: {e}")


if __name__ == "__main__":
    main()
