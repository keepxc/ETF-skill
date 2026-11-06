"""ETF 异常哨兵（每日盘前跑，静默优先，事件驱动）
取代原 etf_daily.py 的日报地位——决策频率是"每周复盘"，不需要每天看溢价数字。
stdout 由 Hermes cron no_agent 投递 Telegram：无输出 = 不推送 = 频道安静（0 条也算正常）。

告警类别（配置在 dca_config.json 的 alerts 块，缺省用下面的 DEFAULT_ALERTS）：
  halt_notice          开市临停/停复牌公告——事件去重：同基金同标题公告连续出现不重复报，
                       标题变化（可能对应停牌安排变化）才再报。局限：停牌时段在公告正文，
                       标题级去重检测不到正文内的时间变化，如实接受。
  extreme_premium_pctile  溢价历史百分位 ≥ 此值报（边沿触发，回落不报恢复）
                       档位制已于 2026-10-14 废除（金额恒定，溢率只改入场价），
                       所以判据只有百分位一条；绝对阈值会被结构性抬升顶穿，不再使用。
  sub_status_change    场外联接基金申购状态翻转（暂停/限大额/恢复开放）
  fee_change           管理费/托管费变动
边沿触发口径：同一异常连续出现不重复打扰；状态写在 alert_state.json（gitignored）。
环境变量 ETF_FORCE=1 试跑：无论是否异常都打印当前状态（不写边沿状态）。
"""
import sys, os, json, datetime
from pathlib import Path

import etf_daily as daily

HERE = Path(__file__).resolve().parent
ALERT_STATE = HERE / "alert_state.json"

DEFAULT_ALERTS = {
    "halt_notice": True,
    "halt_remind_every_days": 0,  # 例行停复牌公告持续中：0=完全静默，N=每 N 天重申一次
    "extreme_premium_pctile": 95,
    "sub_status_change": True,
    "fee_change": True,
}


def edge(key, cond_now, state, force=False):
    """边沿触发：条件从 False→True 才返回 True。force=True 只读不写。"""
    prev = state.get(key)
    if cond_now:
        if not prev:
            if not force:
                state[key] = True
            return True
        return False  # 持续中，已报过
    if prev and not force:
        state[key] = False  # 解除（可考虑发恢复通知；先静默，周报会覆盖）
    return False


def halt_notices(codes, today):
    """今日停牌类公告（带事件标识）。返回 (list[(code, type, title, aid, pubdate)], ok)。
    ok=False = 公告接口整体不可达，不等于确认无停牌（别把取数失败读成「今天不停牌」）。"""
    ds = today.isoformat()
    ok, hits = False, []
    for c in codes:
        try:
            d = json.loads(daily._get(
                daily.ANN_URL.format(c=c), referer="https://fund.eastmoney.com/", timeout=10))
        except Exception:
            continue
        ok = True
        for it in (d.get("Data") or []):
            if str(it.get("PUBLISHDATEDesc") or "")[:10] != ds:
                continue
            title = it.get("TITLE") or ""
            if "停复牌" in title:
                hits.append((c, "停复牌", title, it.get("ID") or "", ds))
            elif "停牌" in title:
                hits.append((c, "停牌", title, it.get("ID") or "", ds))
    return hits, ok


def halt_should_alert(hit, memo):
    """停牌公告去重。判定依据（按用户优先级落到可实现层）：
    1) 公告 ID——唯一标识每篇公告，但例行公告每天都是新 ID，「ID 变化」不构成
       提醒信号（检查它等于天天报，与静默目标矛盾）；ID 只做留档。
    2) 发布日期+基金代码——例行重申（同 code 每天新 ID 同标题）由 3) 拦截。
    3) 标题变化（辅助依据）——标题变 → 可能停牌安排变 → 提醒。
    已知局限（如实接受）：停牌时段/复牌时间在公告正文 PDF 里，PDF 有反爬挑战页，
    「同标题但停牌时段改了」检测不到。
    补偿手段：配置 halt_remind_every_days: N>0 时对持续中的例行公告每 N 天重申一次（0=关）。
    注意：本函数只做判定，不写状态；force 试跑模式由调用方控制写入与否。"""
    c, typ, title, aid, pubdate = hit
    prev = memo.get(c)
    if prev is None:
        return True  # 首次发现
    if prev.get("title") != title:
        return True  # 标题变化 → 辅助判断为事件变化
    return False  # 同标题例行重申：默认静默


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    now = datetime.datetime.now()
    today = now.date()
    cfg = daily._load(daily.CONFIG_PATH, None) or {}
    if not cfg.get("pool"):
        # 哨兵最忌静默失败：配置缺失必须出声，否则永远没人发现哨兵已瘫
        print("🚨 ETF 哨兵无法运行：dca_config.json 缺失或无 pool 决策池——配置异常，请人工核查")
        return
    pool = cfg["pool"]
    alerts = {**DEFAULT_ALERTS, **(cfg.get("alerts") or {})}
    astate = daily._load(ALERT_STATE, {})
    force = bool(os.environ.get("ETF_FORCE"))
    out = []

    # ── 1) 停牌类公告（去重判定见 halt_should_alert；ID 留档不构成提醒信号） ──
    if alerts["halt_notice"]:
        hits, halt_ok = halt_notices(pool[:1], today)
        memo = astate.setdefault("halt_memo", {})  # {code: {"title","id","date","last_alert"}}
        for c, typ, title, aid, pubdate in hits:
            rec = memo.get(c) or {}
            should = halt_should_alert((c, typ, title, aid, pubdate), memo)
            every = int(alerts.get("halt_remind_every_days") or 0)
            due = False
            if not should and every > 0 and rec.get("last_alert"):
                due = (today - datetime.date.fromisoformat(rec["last_alert"])).days >= every
            if should or due:
                why = "首次发现" if rec.get("title") is None else (
                    "标题变化" if rec.get("title") != title else f"例行重申（每{every}天）")
                out.append(f"⛔ {c} {typ}公告（{why}）：{title}")
                if not force:
                    memo[c] = {"title": title, "id": aid, "date": pubdate,
                               "last_alert": today.isoformat()}
            else:
                # 同标题例行重申：静默，只刷新 id/date 防状态腐烂
                if not force:
                    rec.update({"id": aid, "date": pubdate})
                    memo[c] = rec
        if not halt_ok and not hits:
            out.append("⚠ 公告接口不可达——本次无法确认是否有停牌（不等于无停牌）")

    # ── 行情/净值/溢价（复用日报管道，静默取数） ──
    quotes = {}
    try:
        quotes = daily.fetch_quotes(pool + cfg.get("watch", []))
    except Exception as e:
        out.append(f"⚠ 行情获取失败 {type(e).__name__}——溢价检查本次跳过（不等于无异常）")
    cal = []
    try:
        cal = [r[0] for r in daily.fetch_kline(pool[0], 60)]
    except Exception:
        pass
    ndx, fx = {}, {}
    try:
        ndx = daily.fetch_ndx_closes()
        fx = daily.fetch_fx_closes()
    except Exception as e:
        # 指数/汇率取不到 → correct_nav 退回券商口径溢价（etf_daily 原生行为），不崩不静默
        out.append(f"⚠ 指数/汇率取数失败 {type(e).__name__}——溢价退回券商口径（低估真实溢价，已知偏差）")

    rows = {}
    for c in pool:
        q = quotes.get(c)
        if not q:
            continue
        price, pdate, _ = daily.price_basis(q, cal, now)
        try:
            pr = daily.calc_premium(price, pdate, daily.fetch_navs(c), cal)
        except Exception:
            pr = None
        if not pr:
            continue
        est, ref, _, _ = daily.correct_nav(pr["nav_date"], pr["nav"], ndx, fx)
        prem = (price / est - 1) * 100 if (est and ref != pr["nav_date"]) else pr["prem"]
        rows[c] = {"prem": prem, "price": price, "pctile": None, "pdate": pdate}
    best_code = min(rows, key=lambda c: rows[c]["prem"]) if rows else None
    best = rows.get(best_code) if best_code else None
    # 账本续供（11-06 发现：三层改造后完整日报不再被 cron 调用，premium_log.json
    # 的唯一写入口断粮——哨兵是工作日唯一每日运行者，补上写入）。
    # 口径差异如实说明：哨兵 9:20 开盘前跑，价格=昨收盘（与 CSV 全史收盘口径一致），
    # 日报时代=开盘首笔；键=价格日期，两者同构，混用不影响 P 值/周报读法。
    if rows:
        try:
            daily.log_premiums(
                {c: {"prem_use": r["prem"], "price_date": r["pdate"]}
                 for c, r in rows.items()},
                list(rows))
        except Exception as e:
            out.append(f"⚠ premium_log 写入失败 {type(e).__name__}——不影响本次判断")

    # ── 2) 极端溢价（决策池最低溢价者：定投实际按它执行；百分位按同 code 历史） ──
    # 档位制已废除（金额恒为 monthly_base_amount，溢率只改入场价）→ 判据只剩百分位一条。
    if best:
        st = daily.premium_stats(best["prem"], code=best_code, cur_date=today.isoformat())
        if st and st["pctile"] >= alerts["extreme_premium_pctile"]:
            if edge("extreme_prem_pctile", True, astate, force):
                out.append(f"🚨 溢价 {best['prem']:+.1f}% 处历史 P{st['pctile']:.0f}（极端区）"
                           f"——月投金额不变，场内买入等于多付 {best['prem']:.1f}% 通道费；")
                out.append("   场外联接按净值成交，换通道先查申购状态")
        else:
            edge("extreme_prem_pctile", False, astate, force)

    # ── 3) 场外联接申购状态变化（状态翻转才报） ──
    if alerts["sub_status_change"]:
        for c in pool:
            sub = daily.fetch_sub_status(c)
            if sub is None:
                continue  # 取不到 ≠ 无变化，不误报
            prev = (astate.get("sub_status") or {}).get(c)
            if prev is not None and prev != sub:
                out.append(f"⚠ {c} 场外联接申购状态变化：{prev} → {sub}"
                           + ("——换通道建议先过这一关" if "暂停" in sub or "限" in sub else ""))
            astate.setdefault("sub_status", {})[c] = sub

    # ── 4) 费率变动 ──
    if alerts["fee_change"]:
        _, fee_changes, _ = daily.get_fees(pool + cfg.get("watch", []),
                                           cfg.get("fee_refresh_days", 7))
        for ch in fee_changes:
            out.append("⚠ 费率变动：" + ch)

    # ── 5) 定投日决策（原日报在定投日的唯一不可替代职责，搬到哨兵） ──
    trading_today = any(q["ts"].date() == today for q in quotes.values()) if quotes else False
    state = daily._load(daily.STATE_PATH, {"backlog": 0, "last_dca_month": None})
    if best and daily.is_dca_day(today, trading_today, cfg["dca_day"], state):
        tier = daily.pick_tier(best["prem"], cfg["premium_tiers"])
        amount, new_backlog = daily.plan_amount(
            tier, cfg["monthly_base_amount"], state.get("backlog", 0), cfg["backlog_cap"])
        cm = daily.commission(amount, cfg)
        out.append("📌 今日定投 · 买 %s %d 元（溢率 %+.1f%%）· 佣金 %.0f 元"
                   % (best_code, amount, best["prem"], cm))
    # 定投日恰逢休市：is_dca_day 的 day>=dca_day + 下一交易日触发逻辑自动顺延，此处不重复

    if out:
        print("📣 ETF 异常提醒 · %s" % now.strftime("%m-%d %H:%M"))
        for line in out:
            print("  " + line)
    elif force:
        print("（ETF_FORCE 试跑：今日无异常。当前溢价 " + (
            "%s %+.1f%%" % (best_code, best["prem"]) if best else "取数失败") + "）")

    if not force:
        daily._save(ALERT_STATE, astate)


if __name__ == "__main__":
    main()
