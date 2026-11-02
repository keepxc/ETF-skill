#!/usr/bin/env python3
"""test_etf_dca.py — ETF 定投的**金额与日期决策**离线回归（门禁 fast 集）。

为什么测这几个函数（2026-11-01）：ETF 定投是每天 9:30 真跑的生产 cron，
而 `harness.py audit` 一直点名 `etf-positions: tests.fast=0` —— 提交只过 lint，
一行回归都没有。钱相关的逻辑（投多少 / 什么时候投 / 手续费）最该被锁死。

只测纯函数，不联网、不写盘、不读真实持仓（那是 test_timing_gate.py 的活）。

锁定的不变量：
  1. `pick_tier` 的**边界是严格小于**（溢率正好等于档位阈值时不该触发更深的档）
  2. `plan_amount` 的积压（backlog）口径：低档位释放积压并清零；其余档少投的差额计入积压且封顶
  3. `is_dca_day` 用 `day >= dca_day` —— 这就是「15 号遇休市顺延」，不是只在 15 号
  4. `commission` 有最低值兜底（金额很小的时候费率算出来低于最低佣金）
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etf_daily as D  # noqa: E402

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if detail and not cond else ""))


# 顺序是契约的一部分：pick_tier 从头扫、返回**第一个**满足 `below is None or prem < below` 的档位，
# 所以档位表必须「从最深到最浅」排列、`below=None` 的兜底档放最后。顺序错了会永远命中第一档，
# 深档静默失效 —— 见第 6 节的真实配置不变量。金额仅测试用，非生产参数。
TIERS = [
    {"label": "-6% 加两档", "below": -6.0, "amount": 4000, "release_backlog": True},
    {"label": "-3% 加一档", "below": -3.0, "amount": 3000},
    {"label": "常态", "below": None, "amount": 2000},
]

print("== 1. pick_tier：阈值边界（严格小于）==")
check("溢率 +1% → 常态档", D.pick_tier(1.0, TIERS)["label"] == "常态")
check("溢率 0% → 常态档（below=None 兜底在最前/最后按序）", D.pick_tier(0.0, TIERS)["label"] == "常态")
check("溢率 -3.5% → 加一档", D.pick_tier(-3.5, TIERS)["label"] == "-3% 加一档")
check("溢率正好 -3.0% → **不**进加一档（边界严格小于）", D.pick_tier(-3.0, TIERS)["label"] == "常态",
      D.pick_tier(-3.0, TIERS)["label"])
check("溢率 -6.5% → 加两档", D.pick_tier(-6.5, TIERS)["label"] == "-6% 加两档")
check("溢率极低 -20% → 命中最深档（不会无处可落）", D.pick_tier(-20.0, TIERS)["label"] == "-6% 加两档")

print("== 2. plan_amount：积压口径 ==")
amt, backlog = D.plan_amount(TIERS[2], base=2000, backlog=0, cap=6000)
check("常态档 base=amount → 投 2000、积压 0", (amt, backlog) == (2000, 0), f"{amt}/{backlog}")
amt, backlog = D.plan_amount(TIERS[2], base=2000, backlog=0, cap=6000)
check("base 等于档位金额时积压不增", backlog == 0)
amt, backlog = D.plan_amount({"label": "保守", "amount": 1000}, base=2000, backlog=500, cap=6000)
check("少投差额计入积压（1000 投、积压 500+1000=1500）", (amt, backlog) == (1000, 1500), f"{amt}/{backlog}")
amt, backlog = D.plan_amount({"label": "保守", "amount": 1000}, base=2000, backlog=5900, cap=6000)
check("积压封顶 cap（5900+1000 → 6000）", backlog == 6000, f"{backlog}")
amt, backlog = D.plan_amount(TIERS[0], base=2000, backlog=4000, cap=6000)
check("低档位释放积压：max(档位额, 基准+积压)=6000 且积压清零", (amt, backlog) == (6000, 0), f"{amt}/{backlog}")
amt, backlog = D.plan_amount({"label": "更狠", "amount": 9000, "release_backlog": True},
                             base=2000, backlog=1000, cap=6000)
check("低档位取档位额与 base+backlog 的较大者", (amt, backlog) == (9000, 0), f"{amt}/{backlog}")

print("== 3. commission：最低佣金兜底 ==")
cfg_min = {"commission": {"rate": 0.0003, "min_per_order": 5.0, "free_of_min": False}}
cfg_free = {"commission": {"rate": 0.0003, "min_per_order": 5.0, "free_of_min": True}}
check("金额 0 → 佣金 0", D.commission(0, cfg_min) == 0.0)
check("负金额 → 佣金 0（不产生负费用）", D.commission(-100, cfg_min) == 0.0)
check("小额时按最低佣金 5 元", D.commission(2000, cfg_min) == 5.0, str(D.commission(2000, cfg_min)))
check("大额时按费率 10000*0.0003=3 元 < 5 → 仍取最低 5", D.commission(10000, cfg_min) == 5.0,
      str(D.commission(10000, cfg_min)))
check("free_of_min=True 时纯费率，不兜底", abs(D.commission(10000, cfg_free) - 3.0) < 1e-9,
      str(D.commission(10000, cfg_free)))

print("== 4. is_dca_day：「15 号遇休市顺延」= day >= 15 且本月未执行 ==")
state_todo: dict = {}
state_done = {"last_dca_month": "2026-11"}
check("到日子 + 今天开市 + 本月没投 → True",
      D.is_dca_day(dt.date(2026, 11, 16), True, 15, state_todo) is True)
check("正好 15 号 → True", D.is_dca_day(dt.date(2026, 11, 15), True, 15, state_todo) is True)
check("14 号 → False（还没到）", D.is_dca_day(dt.date(2026, 11, 14), True, 15, state_todo) is False)
check("16 号但今天休市 → False（等下一个交易日，不硬买）",
      D.is_dca_day(dt.date(2026, 11, 16), False, 15, state_todo) is False)
check("本月已投 → False（不重复扣款）",
      D.is_dca_day(dt.date(2026, 11, 20), True, 15, state_done) is False)
check("跨月后重新允许（12 月 15 号）",
      D.is_dca_day(dt.date(2026, 12, 15), True, 15, state_done) is True)

print("== 5. next_dca_label：给人看的下次日期 ==")
check("已到日子但本月未投 → 说「下一个交易日」",
      D.next_dca_label(dt.date(2026, 11, 16), 15, state_todo) == "下一个交易日（本月尚未执行）",
      D.next_dca_label(dt.date(2026, 11, 16), 15, state_todo))
check("还没到日子 → 本月 15 号",
      D.next_dca_label(dt.date(2026, 11, 3), 15, state_todo) == "11月15日（遇休市顺延）",
      D.next_dca_label(dt.date(2026, 11, 3), 15, state_todo))
check("本月已投 → 下月 15 号",
      D.next_dca_label(dt.date(2026, 11, 20), 15, state_done) == "12月15日（遇休市顺延）",
      D.next_dca_label(dt.date(2026, 11, 20), 15, state_done))
check("12 月已投 → 跨年到 1 月（不出现 13 月）",
      D.next_dca_label(dt.date(2026, 12, 20), 15, {"last_dca_month": "2026-12"}) == "1月15日（遇休市顺延）",
      D.next_dca_label(dt.date(2026, 12, 20), 15, {"last_dca_month": "2026-12"}))


print("== 6. 真实配置 dca_config.json 的不变量（防「档位顺序写错导致深档静默失效」）==")
_cfg = D._load(D.CONFIG_PATH, None)
check("dca_config.json 可读", isinstance(_cfg, dict), type(_cfg).__name__)
if isinstance(_cfg, dict):
    _tiers = _cfg.get("premium_tiers") or []
    check("至少一个档位", len(_tiers) >= 1, str(len(_tiers)))
    _b = [(-1e9 if t.get("below") is None else t["below"]) for t in _tiers]
    check("below 从深到浅单调递增（None 兜底档在最后）", all(_b[i] < _b[i + 1] for i in range(len(_b) - 1)), str(_b))
    check("最后一档的 below 必须是 None（否则存在无档可落的溢率）",
          bool(_tiers) and _tiers[-1].get("below") is None, str([t.get("below") for t in _tiers]))
    check("每档都有一个正数金额", all(isinstance(t.get("amount"), (int, float)) and t["amount"] > 0 for t in _tiers))
    _day = _cfg.get("dca_day")
    check("dca_day 在 1–28（避免 29–31 号在短月永不触发）", isinstance(_day, int) and 1 <= _day <= 28, str(_day))
    check("定投池非空", bool(_cfg.get("pool")), str(_cfg.get("pool")))
    check("佣金费率在 0<rate<1%", 0 < (_cfg.get("commission") or {}).get("rate", 0) < 0.01)

print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
sys.exit(1 if FAIL else 0)
