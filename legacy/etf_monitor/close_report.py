#!/usr/bin/env python3
"""ETF 513300 收盘报告 — 工作日 15:05 运行"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, date
from etf513300 import realtime, klines, ma
from nasdaq_dca import get_data, premium_verdict, is_dca_day
from nasdaq_drawdown import get_sell_signal_status


def main():
    now = datetime.now()
    print(f"\n{'='*40}")
    print(f"📊 ETF 513300 收盘报告")
    print(f"📅 {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*40}")

    try:
        rt = realtime()
    except Exception as e:
        print(f"❌ 获取实时数据失败: {e}")
        return

    print(f"\n🏷 {rt['name']} ({rt['code']})")
    print(f"{'─'*40}")

    # 今日行情
    change = rt['price'] - rt['prev_close']
    emoji = "🟢" if change >= 0 else "🔴"
    print(f"\n{emoji} 今日行情:")
    print(f"   开盘: {rt['open']:.3f}")
    print(f"   最高: {rt['high']:.3f}")
    print(f"   最低: {rt['low']:.3f}")
    print(f"   收盘: {rt['price']:.3f}")
    print(f"   涨跌: {change:+.3f} ({rt['change_pct']:+.2f}%)")
    print(f"   成交量: {rt['volume']/10000:.0f} 万手")
    print(f"   成交额: {rt['amount']/100000000:.2f} 亿")

    # K 线形态
    try:
        kl = klines(20)
    except Exception as e:
        print(f"❌ 获取K线失败: {e}")
        return

    if kl:
        today = kl[-1]
        body = today['close'] - today['open']
        upper = today['high'] - max(today['open'], today['close'])
        lower = min(today['open'], today['close']) - today['low']

        print(f"\n🕯 K线形态:")
        if body > 0:
            ktype = "阳线"
            if upper < body * 0.1 and lower < body * 0.1:
                ktype += " (光头光脚，强势)"
            elif upper > body * 2:
                ktype += " (长上影，有压力)"
            elif lower > body * 2:
                ktype += " (长下影，有支撑)"
        elif body < 0:
            ktype = "阴线"
            if upper < abs(body) * 0.1 and lower < abs(body) * 0.1:
                ktype += " (光头光脚，弱势)"
            elif upper > abs(body) * 2:
                ktype += " (长上影，抛压重)"
            elif lower > abs(body) * 2:
                ktype += " (长下影，下方有承接)"
        else:
            ktype = "十字星 (多空平衡)"
        print(f"   类型: {ktype}")
        print(f"   实体: {abs(body):.3f}  上影: {upper:.3f}  下影: {lower:.3f}")

    # 均线分析
    ma5 = ma(kl, 5)
    ma10 = ma(kl, 10)
    ma20 = ma(kl, 20)
    print(f"\n📐 均线状态:")
    if ma5:  print(f"   MA5:  {ma5:.3f}  {'↑' if rt['price'] > ma5 else '↓'}")
    if ma10: print(f"   MA10: {ma10:.3f}  {'↑' if rt['price'] > ma10 else '↓'}")
    if ma20: print(f"   MA20: {ma20:.3f}  {'↑' if rt['price'] > ma20 else '↓'}")

    # 趋势判断
    if ma5 and ma10:
        if ma5 > ma10:
            print(f"   短期趋势: 偏多 (MA5 > MA10)")
        else:
            print(f"   短期趋势: 偏空 (MA5 < MA10)")

    # 近5日统计
    if len(kl) >= 5:
        last5 = kl[-5:]
        def _chg(k, idx):
            prev = last5[idx-1]["close"] if idx > 0 else k["open"]
            return (k["close"] / prev - 1) * 100 if prev else 0
        up_days = sum(1 for i, k in enumerate(last5) if _chg(k, i) > 0)
        down_days = sum(1 for i, k in enumerate(last5) if _chg(k, i) < 0)
        total_change = (last5[-1]['close'] / last5[0]['open'] - 1) * 100
        print(f"\n📊 近5日统计:")
        print(f"   涨跌天数: {up_days}涨 {down_days}跌")
        print(f"   累计涨跌: {total_change:+.2f}%")
        print(f"   区间: {min(k['low'] for k in last5):.3f} ~ {max(k['high'] for k in last5):.3f}")

    # 操作建议（仅供参考）
    print(f"\n💡 参考:")
    if rt['price'] > rt['open']:
        print(f"   今日收阳，多方占优")
    elif rt['price'] < rt['open']:
        print(f"   今日收阴，空方占优")
    else:
        print(f"   今日平盘，多空均衡")

    if ma5 and ma10 and ma20:
        if rt['price'] > ma5 > ma10:
            print(f"   短期偏强，关注上方压力位")
        elif rt['price'] < ma5 < ma10:
            print(f"   短期偏弱，关注下方支撑位")
        else:
            print(f"   震荡格局，等待方向选择")

    # 定投日收盘：定投复盘
    is_dca, day_info = is_dca_day()
    if is_dca:
        print(f"\n{'─'*40}")
        print(f"💰 今日定投复盘（周三）")
        try:
            d = get_data()
            if "error" not in d:
                premium = d.get("premium_pct", 0)
                verdict = premium_verdict(premium)
                print(f"   溢价: {premium:+.2f}% → {verdict}")
                if premium > 3.0:
                    print(f"   ❌ 未买（溢价过高）")
                elif premium > 1.0:
                    print(f"   ⚠️ 早上如买了半仓(250元)，剩余顺延下次")
                else:
                    print(f"   ✅ 今日应已买入500元")
            else:
                print(f"   ❌ 数据获取失败")
        except Exception as e:
            print(f"   ❌ 数据异常: {e}")

    # 纳指止盈信号
    try:
        print(get_sell_signal_status())
    except Exception as e:
        print(f"❌ 止盈信号获取失败: {e}")

    print(f"\n{'='*40}\n")


if __name__ == "__main__":
    main()
