"""定投月报 — 长期计划的执行核对（每月一次，建议 cron 每月 16 日 20:00）
定投日是 15 日：16 日核对"本月是否按规则执行了"。
内容只回答四件事：本月执行了吗 / 累计投入与成本 / 当前持仓值多少 / 下次计划。
不回答"要不要改计划"——短期波动不改月度规则（这是这套系统存在的意义）。
数据源：dca_state.json（执行历史）+ position.json（持仓）+ 腾讯实时价。ETF_FORCE=1 试跑。
"""
import sys, os, datetime
from pathlib import Path

import etf_daily as daily
import etf_fund_compare as fund_compare

HERE = Path(__file__).resolve().parent


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    now = datetime.datetime.now()
    today = now.date()
    cfg = daily._load(daily.CONFIG_PATH, None) or {}
    state = daily._load(daily.STATE_PATH, {"backlog": 0, "last_dca_month": None, "history": []})
    force = bool(os.environ.get("ETF_FORCE"))
    month = today.strftime("%Y-%m")

    # 持仓三态：有 / 明确无 / 数据不可用——把「没读到」当「无持仓」会污染收益口径
    if not daily.POS_PATH.exists():
        pos_err = "position.json 不存在——若应有持仓，这是数据异常，先核查文件"
        pos = {}
    else:
        pos = daily._load(daily.POS_PATH, None)
        pos_err = None if pos is not None else "position.json 读取/解析失败——同上，先核查"
        pos = pos or {}

    hist = state.get("history", [])
    mv = 0.0
    cost = 0.0
    this_month = [h for h in hist if h.get("date", "").startswith(month)]
    # 未到核对点（16日前）且本月无记录 → 静默（试跑除外）
    if not this_month and today.day < 16 and not force:
        return

    L = [f"📋 定投月报 · {month} · {now:%m-%d %H:%M}"]

    # ── 本月执行核验（四态：成交 / 未执行 / 休市顺延 / 无法核实） ──
    # 原则：计划投入 ≠ 实际投入。累计口径只认 history 里的执行记录；
    # 原系统不记录成交价/份额，所以「按计划执行」只能核到金额级，成交价如实标注缺失。
    if this_month:
        for h in this_month:
            L.append(f"  ✓ {h['date'][5:]} 投 {h['amount']} 元 @溢率 {h.get('premium', '?')}%"
                     f"{' ' + h['code'] if h.get('code') else ''}")
        L.append("  核验口径 金额以执行记录为准；成交价/份额原系统未记录，无法核实——非未执行")
    elif state.get("last_dca_month") == month:
        L.append("  ？ 已标记本月执行但无明细记录——无法核实，不当作未执行（检查 dca_state.history）")
    else:
        # 判定 15 日是否交易日（用决策池标日 K 作 A 股交易日历）
        d15 = datetime.date(today.year, today.month, cfg.get("dca_day", 15))
        is_trading_d15 = False
        next_trading = None
        try:
            cal = [r[0] for r in daily.fetch_kline(cfg["pool"][0], 90)]
            is_trading_d15 = d15.isoformat() in cal
            after = [d for d in cal if d > d15.isoformat()]
            next_trading = after[0] if after else None
        except Exception:
            pass  # 日历取不到 → 不猜，按未执行如实报
        if today < d15:
            L.append(f"  - 定投日 {d15} 未到（月报提前试跑）")
        elif is_trading_d15:
            L.append("  ✗ 15日至今无执行记录（执行窗本月内每个交易日仍会触发，"
                     "若最终未执行才是真未执行）——检查哨兵/手工执行情况")
        elif next_trading:
            L.append(f"  - 15日休市，按顺延规则应在 {next_trading} 执行——现在无记录属预期")
        else:
            L.append("  ？ 交易日历取不到，无法判定 15 日休市/顺延——如实标记：无执行记录")
    if state.get("backlog"):
        L.append(f"  积压 {state['backlog']} 元（上限 {cfg.get('backlog_cap', 5000)}）"
                 "——低溢价档时一次性投放")

    # ── 累计：从执行历史 + 持仓两路算（history 缺失时不瞎凑） ──
    total_in = sum(h.get("amount", 0) for h in hist)
    L.append(f"  历史定投 {len(hist)} 次 · 累计 {total_in:,.0f} 元（只认执行记录，计划金额不算数）")
    if pos.get("positions") and not hist:
        L.append("  ⚠ 数据不一致：有持仓但无任何定投记录——两文件至少一个不完整，累计口径暂不可信")
    if pos.get("positions"):
        try:
            codes = [p["code"] for p in pos["positions"]]
            quotes = daily.fetch_quotes(codes)
        except Exception:
            quotes = {}
        for p in pos["positions"]:
            sh, c0 = p["shares"], p["cost"]
            cost += sh * c0
            q = quotes.get(p["code"])
            if q and q.get("price"):
                mv += sh * q["price"]
        if mv:
            L.append(f"  持仓 市值 {mv:,.0f} · 成本 {cost:,.0f} · 浮动 {mv - cost:+,.0f}"
                     f"（{(mv - cost) / cost * 100:+.1f}%）")
        # 下次计划
        nd = None
        if state.get("last_dca_month") != month and today.day <= cfg.get("dca_day", 15):
            nd = datetime.date(today.year, today.month, cfg.get("dca_day", 15))
        else:
            y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            nd = datetime.date(y, m, cfg.get("dca_day", 15))
        L.append(f"  下次 {nd:%Y-%m-%d}（遇休市顺延）· 基准 {cfg.get('monthly_base_amount', 1000)} 元")
        L.append(f"  规则不变：每月 {cfg.get('dca_day', 15)} 日执行，"
                 f"金额恒为 {cfg.get('monthly_base_amount', 1000)}（溢价只改入场价）")
    elif pos_err:
        L.append(f"  ⚠ {pos_err}（本月市值/浮动已跳过——这不等于无持仓）")
    else:
        L.append("  无持仓记录（文件存在且为空）")

    # ── 基金体检：13 只横向对比（美元净值口径 + 溢价 + 费率 + 现金趋势） ──
    # 与上面的「执行核对」是两个维度：上面看「有没有按规则投」，这里看「投的那只还对不对」。
    # 失败只跳过本节，不让整份月报挂掉（核对信息更重要）。
    universe = cfg.get("fund_universe") or []
    if universe:
        try:
            L += fund_compare.render(universe, cfg=cfg, mv=mv or None, today=today)
        except Exception as e:  # noqa: BLE001 — 附加节，失败降级不阻断
            L.append(f"  ⚠ 基金体检失败（{type(e).__name__}: {e}）——本节跳过，不影响上面的定投核对")

    print("\n".join(L))


if __name__ == "__main__":
    main()
