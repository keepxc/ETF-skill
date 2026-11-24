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
  金额只是 lots×100×price 的显示值。价格涨跌改变的是金额，不是「该投几手」。
"""
import datetime

LOT = 100  # A 股 ETF 最小交易单位（份）


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate(plan, prem, price, today=None):
    """算当前该投哪几档、各多少手。返回 dict，不产生副作用。"""
    today = today or datetime.date.today()
    tiers = plan.get("tiers") or []
    if not tiers or prem is None:
        return {"ok": False, "reason": "配置缺失或溢价取数失败"}

    executed = plan.get("executed") or {}
    triggered, pending = [], []
    for t in tiers:
        key = t.get("key") or t.get("label")
        cap = t.get("prem_below")
        if cap is not None and prem > _num(cap):
            continue
        quota_lots = int(_num(t.get("lots")))
        done_lots = sum(int(_num(e.get("lots"))) for e in executed.get(key) or [])
        left_lots = max(0, quota_lots - done_lots)
        row = {"key": key, "label": t.get("label"), "cap": cap,
               "quota_lots": quota_lots, "done_lots": done_lots, "left_lots": left_lots}
        triggered.append(row)
        if left_lots > 0:
            pending.append(row)

    # 下一档：尚未触发的最低溢价档（给用户「还差多少」）
    nxt = None
    for t in tiers:
        cap = t.get("prem_below")
        if cap is not None and prem > _num(cap):
            nxt = {"cap": _num(cap), "label": t.get("label"), "lots": int(_num(t.get("lots")))}
            break

    deadline = plan.get("deadline")
    overdue = bool(deadline and str(today) > deadline)
    # 已投手数按全部 executed 求和（不限于已触发档）：过期口径是「还剩几手没投」
    done_all = sum(int(_num(e.get("lots")))
                   for rows_ in executed.values() for e in rows_)
    return {"ok": True, "triggered": triggered, "pending": pending,
            "next": nxt, "deadline": deadline, "overdue": overdue,
            "price": price, "prem": prem,
            "total_lots": sum(int(_num(t.get("lots"))) for t in tiers),
            "done_lots": done_all}


def render(plan, prem, price, astate, force=False, today=None):
    """每日输出行。边沿触发：同一档只在首次可投时提醒一次，之后静默；
    force=True（ETF_FORCE 试跑）忽略去重、不写状态。"""
    r = evaluate(plan, prem, price, today)
    if not r.get("ok"):
        return [f"💼 一次性资金计划跳过：{r.get('reason')}"]

    astate = astate if isinstance(astate, dict) else {}
    reminded = astate.get("lump_reminded") or {}
    out = []

    # 过期优先于档位：到期就没必要再等溢率回落，剩余手数全部摊入定投
    if r["overdue"]:
        left = r["total_lots"] - r["done_lots"]
        if left > 0 and (not reminded.get("__deadline__") or force):
            out.append(f"⏰ 一次性资金计划到期（{r['deadline']}）· 仍有 {left} 手（{left * LOT} 股）未投")
            out.append("   按约定剩余摊入月度定投，或延长 deadline（要你拍板）")
            if not force:
                reminded["__deadline__"] = str(today or datetime.date.today())
                astate["lump_reminded"] = reminded
        return out

    if r["pending"]:
        lots = sum(x["left_lots"] for x in r["pending"])
        amt = sum(x["left_lots"] * LOT * price for x in r["pending"])
        new = [x for x in r["pending"] if not reminded.get(x["key"])]
        if new or force:
            out.append(f"💼 一次性资金 · 当前溢率 {prem:+.1f}% · 可投 {lots} 手（{lots * LOT} 股）")
            for x in r["pending"]:
                mark = " ← 新触发" if not reminded.get(x["key"]) else ""
                out.append(f"   {x['label']} {x['left_lots']}/{x['quota_lots']} 手"
                           f" ≈ {x['left_lots'] * LOT * price:,.0f} 元{mark}")
            out.append(f"   合计 ≈ {amt:,.0f} 元（{price:.3f}×{lots * LOT} 股，只能整手）")
            if r["next"]:
                gap = prem - r["next"]["cap"]
                out.append(f"   下一档 {r['next']['label']} 需溢率再降 {gap:.1f}pct "
                           f"到 <{r['next']['cap']:.0f}%")
            if not force:
                for x in r["pending"]:
                    reminded[x["key"]] = str(today or datetime.date.today())
                astate["lump_reminded"] = reminded

    if force and r.get("next"):
        out.append(f"（试跑：下一档 溢率 <{r['next']['cap']:.0f}% → {r['next']['label']} "
                   f"{r['next']['lots']} 手；已投 {r['done_lots']}/{r['total_lots']} 手）")
    return out
