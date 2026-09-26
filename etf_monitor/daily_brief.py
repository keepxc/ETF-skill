#!/usr/bin/env python3
"""ETF 513300 每日早盘简报 — 工作日 8:30 运行"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from etf513300 import realtime, klines, ma


def main():
    now = datetime.now()
    print(f"\n{'='*40}")
    print(f"📊 ETF 513300 早盘简报")
    print(f"📅 {now.strftime('%Y-%m-%d %H:%M')} (工作日)")
    print(f"{'='*40}")

    # 实时/昨收数据
    try:
        rt = realtime()
    except Exception as e:
        print(f"❌ 获取实时数据失败: {e}")
        return

    print(f"\n🏷 {rt['name']} ({rt['code']})")
    print(f"   昨收: {rt['prev_close']:.3f}")

    # 近期 K 线
    try:
        kl = klines(20)
    except Exception as e:
        print(f"❌ 获取K线失败: {e}")
        return

    if kl:
        last = kl[-1]
        # 计算涨跌幅
        prev_close = kl[-2]["close"] if len(kl) >= 2 else last["open"]
        chg = (last["close"] / prev_close - 1) * 100
        amp = (last["high"] - last["low"]) / prev_close * 100
        print(f"\n📈 昨日收盘: {last['close']:.3f}  ({chg:+.2f}%)")
        print(f"   振幅: {amp:.2f}%")

    # 均线
    ma5 = ma(kl, 5)
    ma10 = ma(kl, 10)
    ma20 = ma(kl, 20)
    print(f"\n📐 均线:")
    if ma5:  print(f"   MA5:  {ma5:.3f}")
    if ma10: print(f"   MA10: {ma10:.3f}")
    if ma20: print(f"   MA20: {ma20:.3f}")

    # 趋势判断
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            trend = "📈 多头排列 (短>中>长)"
        elif ma5 < ma10 < ma20:
            trend = "📉 空头排列 (短<中<长)"
        else:
            trend = "⚖️ 震荡整理"
        print(f"   趋势: {trend}")

    # 近5日涨跌
    if len(kl) >= 5:
        print(f"\n📊 近5日表现:")
        for i, k in enumerate(kl[-5:]):
            prev = kl[-5+i-1]["close"] if i > 0 else k["open"]
            chg = (k["close"] / prev - 1) * 100 if prev else 0
            emoji = "🟢" if chg >= 0 else "🔴"
            print(f"   {emoji} {k['date']}  收:{k['close']:.3f}  {chg:+.2f}%")

    # 今日关注位
    if kl:
        recent_high = max(k["high"] for k in kl[-5:])
        recent_low = min(k["low"] for k in kl[-5:])
        print(f"\n🎯 今日关注:")
        print(f"   近5日高点: {recent_high:.3f}")
        print(f"   近5日低点: {recent_low:.3f}")
        print(f"   昨收: {last['close']:.3f}")

    print(f"\n{'='*40}\n")


if __name__ == "__main__":
    main()
