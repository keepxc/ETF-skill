"""一次性资金分档投放计划（LSI 分批）。

**为什么需要它**：定投（每月固定 1000）的规则是「金额不随溢价变」——那是对的，因为定投
平滑的是独立的价格波动。但**一次性资金不同**：它只有一个入场时点，溢价是此刻锁死的确定性
成本。skill 的口径是「定投金额不调，但额外一次性资金仍该等溢率」，两条不矛盾。

**为什么分批而不是二选一**：
- 全投 → 溢价 15% 锁死，等于白付通道费
- 全等 → 历史实证 59% 的情况等不到（溢率 8~11% 时其后回到 ≤5% 只有 41%），且期间行情会走
分批把两头风险都封顶，代价是承认自己判断不了。

**为什么按手数定档、不按金额**（2026-11-24 实测踩坑后定的）：
- A 股 ETF 只能整手（100 份）成交，约束是手数不是金额；
- 按金额分档时，「投完没有」的判定随价格漂移：全 58 手买完后价格一跌，
  同样的钱又能算出几手 → 计划永远「投不完」（场景实测会多出 5 手）；
- 按手数配额（12/17/15/14 = 58），已投也按手数记，left_lots 不随价格漂，
  金额只是 lots×lot_size×price 的显示值。

**提醒节奏（为什么不是「一档只提一次」）**：一次性边沿触发会漏掉再入场信号——
溢价 8% 时 t2 提醒过、用户没买，溢价涨到 12% 再跌回 8%，档位仍有剩余手数却永久静默。
改成冷却制：首次立即提，之后每 `remind_every_days` 天（默认 7）重申一次，直到该档投满。
与 etf_alert 的 `halt_remind_every_days` 同款语义（那边是「例行公告每 N 天重申」）。
"""
import datetime

LOT = 100  # A 股 ETF 最小交易单位（份）；跨市场标的不适用本文件


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _bad(x):
    """None / NaN / 非数值 —— 都不能拿去做算术或比较。"""
    if x is None:
        return True
    try:
        f = float(x)
    except (TypeError, ValueError):
        return True
    return f != f  # NaN


def _as_date(x):
    """today 允许 date / datetime / ISO 字符串；非法值退回今天。
    必须规范化：`date.fromisoformat` 在 str-datetime 混算时抛 TypeError，
    而 _remind_due 的 except 会静默降级为「当没提醒过」→ 天天重申。"""
    if isinstance(x, datetime.datetime):
        return x.date()
    if isinstance(x, datetime.date):
        return x
    try:
        return datetime.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return datetime.date.today()


def _remind_due(key, reminded, today, every):
    """该档是否到提醒时间。返回 (是否提醒, 距上次天数或 None)。
    无记录 → 立刻提醒；有记录 → 距上次 >= every 天才重申。"""
    last = reminded.get(key)
    if not last:
        return True, None
    try:
        days = (today - datetime.date.fromisoformat(str(last))).days
    except (TypeError, ValueError):
        return True, None  # 记录坏了就当没提醒过，宁可多提一次不漏
    return days >= every, days


def evaluate(plan, prem, price, today=None):
    """算当前该投哪几档、各多少手。返回 dict，不产生副作用。"""
    today = _as_date(today or datetime.date.today())
    tiers = plan.get("tiers") or []
    if not tiers:
        return {"ok": False, "reason": "配置缺失（tiers 为空）"}
    if _bad(prem):
        return {"ok": False, "reason": "溢价取数失败（None/NaN）"}
    # 判定与显示用同一精度：不加这一步，9.999 会触发「<10%」档却显示「+10.00%」，
    # 用户看到 10.00 却被告知触发，判定与看到的数字自相矛盾（复审 HIGH 抓到）。
    prem = round(_num(prem), 2)
    # 价格只影响金额显示，不影响档位判定 —— 价格缺失时照报档位，别把入场信号一起吞掉。
    price_ok = not (_bad(price) or _num(price) <= 0)

    executed = plan.get("executed") or {}
    triggered, pending = [], []
    for t in tiers:
        key = t.get("key") or t.get("label")
        cap = t.get("prem_below")
        # 严格小于：label 写「<10%」，溢价恰好 10.00% 时不算触发
        if cap is not None and not _bad(cap) and prem >= _num(cap):
            continue
        quota_lots = int(_num(t.get("lots")))
        done_lots = sum(int(_num(e.get("lots"))) for e in executed.get(key) or [])
        left_lots = max(0, quota_lots - done_lots)
        row = {"key": key, "label": t.get("label"), "cap": cap,
               "quota_lots": quota_lots, "done_lots": done_lots, "left_lots": left_lots}
        triggered.append(row)
        if left_lots > 0:
            pending.append(row)

    # 下一档：尚未触发的最低溢价档（tiers 按溢价降序配，见 dca_config.json）
    nxt = None
    for t in tiers:
        cap = t.get("prem_below")
        if cap is not None and not _bad(cap) and prem >= _num(cap):
            nxt = {"cap": _num(cap), "label": t.get("label"), "lots": int(_num(t.get("lots")))}
            break

    tier_total = sum(int(_num(t.get("lots"))) for t in tiers)
    cfg_total = int(_num(plan.get("total_lots")))
    warn = None
    total_lots = tier_total
    if cfg_total and cfg_total != tier_total:
        # 以各档之和为准（它才是能逐档执行的东西），但必须出声——否则到期剩余手数是错的
        warn = f"total_lots 配 {cfg_total} 与各档之和 {tier_total} 不一致，按各档执行"

    deadline = plan.get("deadline")
    # 到期判定：ISO 日期串字典序 = 时间序（deadline 由 config 保证 YYYY-MM-DD，today 是 date）。
    # 用 >=：到期日当天（含）即视为过期，不拖到次日。
    overdue = bool(deadline and str(today) >= str(deadline))
    # 已投手数按全部 executed 求和（不限于已触发档）：过期口径是「还剩几手没投」
    done_all = sum(int(_num(e.get("lots"))) for rows_ in executed.values() for e in rows_)
    return {"ok": True, "triggered": triggered, "pending": pending,
            "next": nxt, "deadline": deadline, "overdue": overdue,
            "price": price, "prem": prem, "warn": warn, "price_ok": price_ok,
            "total_lots": total_lots, "done_lots": done_all}


def render(plan, prem, price, astate, force=False, today=None):
    """每日输出行（会写 astate["lump_reminded"] 做冷却去重；force=True 只读不写）。"""
    r = evaluate(plan, prem, price, today)
    if not r.get("ok"):
        return [f"💼 一次性资金计划跳过：{r.get('reason')}"]

    astate = astate if isinstance(astate, dict) else {}
    reminded = astate.get("lump_reminded") or {}
    today = _as_date(today or datetime.date.today())
    every = int(_num(plan.get("remind_every_days"), 7))          # 档位冷却
    devery = int(_num(plan.get("deadline_remind_every_days"), 3))  # 到期催办（更密，语义是「催未完成」）
    lot = int(_num(plan.get("lot_size"), LOT)) or LOT
    prem = r["prem"]            # 判定与显示同精度（evaluate 已 round 2 位）
    price_ok = r["price_ok"]    # 价格只影响金额，不影响档位
    out = []
    if r["warn"]:
        out.append(f"⚠ 一次性资金计划{r['warn']}")

    # 过期优先于档位：到期就没必要再等溢率回落，剩余手数全部摊入定投。
    # 去重键带上 deadline 值：用户延长 deadline 后键跟着变，到期提醒能重新触发
    # （否则「延长 deadline」的指引与「永不重提」自我矛盾）。
    if r["overdue"]:
        left = r["total_lots"] - r["done_lots"]
        dkey = f"__deadline__:{r['deadline']}"
        due, _ = _remind_due(dkey, reminded, today, devery)
        if left > 0 and (due or force):
            out.append(f"⏰ 一次性资金计划到期（{r['deadline']}）· 仍有 {left} 手（{left * lot} 股）未投")
            out.append("   按约定剩余摊入月度定投，或延长 deadline（要你拍板）")
            if not force:
                reminded[dkey] = str(today)
                astate["lump_reminded"] = reminded
        return out

    if r["pending"]:
        marks = {}
        any_due = False
        for x in r["pending"]:
            due, days = _remind_due(x["key"], reminded, today, every)
            if due:
                any_due = True
                marks[x["key"]] = " ← 新触发" if days is None else f"（距上次 {days} 天重申）"
            elif days is not None:
                # 冷却中的档：必须标注上次提过的天数，否则用户误以为也是今天提的（复审 MED）
                marks[x["key"]] = f"（{days} 天前提过）"
        if any_due or force:
            lots = sum(x["left_lots"] for x in r["pending"])
            out.append(f"💼 一次性资金 · 当前溢率 {prem:+.2f}% · 可投 {lots} 手（{lots * lot} 股）")
            for x in r["pending"]:
                amt_txt = f" ≈ {x['left_lots'] * lot * price:,.0f} 元" if price_ok else ""
                out.append(f"   {x['label']} {x['left_lots']}/{x['quota_lots']} 手"
                           f"{amt_txt}{marks.get(x['key'], '')}")
            if price_ok:
                out.append(f"   合计 ≈ {lots * lot * price:,.0f} 元"
                           f"（{price:.3f}×{lots * lot} 股，只能整手）")
            else:
                out.append(f"   合计 {lots} 手（金额待行情恢复——价格缺失，档位不受影响）")
            if r["next"]:
                gap = prem - r["next"]["cap"]
                if gap <= 0.05:
                    # 严格 < 的边界：贴线但没触发时「再降 0.0pct」会让用户困惑
                    out.append(f"   下一档 {r['next']['label']} 已贴线"
                               f"（需 <{r['next']['cap']:.0f}%，现 {prem:.2f}%，差 {gap:.2f}pct）")
                else:
                    out.append(f"   下一档 {r['next']['label']} 需溢率再降 {gap:.1f}pct "
                               f"到 <{r['next']['cap']:.0f}%")
            if not force:
                for x in r["pending"]:
                    if x["key"] in marks and marks[x["key"]].startswith((" ← ", "（距上次")):
                        reminded[x["key"]] = str(today)
                astate["lump_reminded"] = reminded

    if force and r.get("next"):
        out.append(f"（试跑：下一档 溢率 <{r['next']['cap']:.0f}% → {r['next']['label']} "
                   f"{r['next']['lots']} 手；已投 {r['done_lots']}/{r['total_lots']} 手）")
    return out
