# ETF 监控脚本（纳指 100 场内 ETF 定投）

纳指 100 场内 ETF 的**多标的比价 + 溢价档位定投**监控，附每日 / 每周简报。
由本机 Hermes cronjob 驱动，输出推送到 Telegram。

> 决策池与档位见 `etf_skill/dca_config.json`（现为 513390 / 513870 / 159660；早期版本只做单标的 513300，见 `legacy/`）。

> ⚠️ 本仓库的**文件就位于生产路径** `/home/gyan/scripts/`，不是拷贝。
> 修改后 git 会跟踪；cron 直接跑的就是这里的文件。

---

## 每日/每周任务（Hermes cronjob）

> **三层架构（2026-11 改版）**：决策频率决定报告频率——加密短线看 Radar，ETF 实际按月定投，
> 所以 ETF 取消每日快报，改为 **每周分析 + 每月核对 + 异常才出声**。

| 任务名 | 调度 (CST) | 入口 wrapper | 实际脚本 | 说明 |
|--------|-----------|--------------|----------|------|
| ETF 异常哨兵 | `20 9 * * 1-5` | `~/.hermes/scripts/etf_check.sh` | `etf_skill/etf_alert.py` | **静默优先**：只在临停公告/极端溢价/申购状态变化/费率变动/定投日决策时输出；平时 stdout 为空 = 不推送 |
| ETF 周报 | `0 21 * * 0` | `~/.hermes/scripts/etf_weekly.sh` | `etf_skill/etf_weekly.py` | 五段制：①纳指市场状态 ②ETF 价格与溢价 ③汇率与净值拆解 ④持仓与定投 ⑤综合判断（AI 龙头估值收附录） |
| 定投月报 | `0 20 16 * *` | `~/.hermes/scripts/etf_monthly.sh` | `etf_skill/etf_monthly.py` | 定投日（15 日）次日核对：本月执行/累计投入/市值浮动/下次计划 |

wrapper 负责「跑脚本 + 双投」，例如：

```bash
cd /home/gyan/scripts/etf_skill
out=$(python3 etf_alert.py); rc=$?
ch=$(cat /home/gyan/.hermes/scripts/.etf_channel_id 2>/dev/null)
if [ -n "$out" ] && [ -n "$ch" ]; then
  printf '%s' "$out" | python3 /home/gyan/.hermes/scripts/tg_push.py --stdin --chat "$ch" \
    || echo "[warn] 频道推送失败（DM 照发）" >&2
fi
[ -n "$out" ] && printf '%s\n' "$out"
exit $rc
```

投递策略：
- **哨兵 / 月报**：双投 —— stdout 由 Hermes cron 用 `BTC1DayBot` 发 DM，同一份内容经 `tg_push.py` 用 `BTC2dayBot` 发私有频道。
- **周报**：**只发频道**（DM 不重复）；频道不可用时才回落 stdout，由 Hermes 投 DM —— 判据是 wrapper 的 stdout 为空即表示频道已收到。

频道 ID 存在 `~/.hermes/scripts/.etf_channel_id`（本地文件，**不入库**）——公开仓库只放机制，不放私人频道标识。`tg_push.py --chat` 支持指定目标会话，不传则维持原来的默认 DM 行为。

手动运行（与 cron 完全同路径）：

```bash
bash ~/.hermes/scripts/etf_check.sh      # 异常哨兵（平时静默）
bash ~/.hermes/scripts/etf_weekly.sh     # 周报
bash ~/.hermes/scripts/etf_monthly.sh    # 月报
```

试跑（跳过边沿状态/去重，无论是否异常都输出当前状态）：

```bash
cd /home/gyan/scripts/etf_skill && ETF_FORCE=1 python3 etf_alert.py
```

---

## 目录

### `etf_skill/` — 现行生产脚本

| 文件 | 说明 |
|------|------|
| `etf_alert.py` | **异常哨兵**（每日 cron 用，三层之一）。静默优先：①开市临停公告（区分高溢价期例行停复牌，措辞不过头）②极端溢价（≥暂停档边界或历史 P95，**边沿触发**，`alert_state.json` 记状态）③场外联接申购状态变化 ④费率变动 ⑤定投日决策（15 日按档位给出"今天买多少"，承接原日报唯一不可替代职责）。`ETF_FORCE=1` 试跑 |
| `etf_weekly.py` | **周报**（每周日 21:00，三层之一）。五段制：①纳指市场状态（估值/回撤/波动**分开陈述，不合并成"贵不贵"**）②ETF 价格与溢价（决策池比价 + 历史百分位，溢价专用判读措辞）③汇率与净值拆解（纳指 vs 美元人民币各自贡献，防误判）④持仓与定投（不展示"回本需要溢价"——成本是历史结果，不构成决策依据）⑤综合判断（风险/有利 + 动作 = 按既定档位执行）。Mag7 AI 估值收附录 |
| `etf_monthly.py` | **定投月报**（每月 16 日 20:00，三层之一）。只核对执行：本月投了吗/累计投入/市值浮动/下次计划；不回答"要不要改计划" |
| `etf_daily.py` | 数据管道（**日报已停用**）：原每日快报。被 alert/weekly/monthly 复用的取数与计算函数都在这里（fetch_quotes/fetch_navs/calc_premium/correct_nav/premium_stats/is_dca_day/pick_tier/plan_amount 等）。手动跑仍可出完整日报，但 cron 不再调用 |
| `dca_config.json` | 配置（gitignored，不入库）：月投基准、定投日、积压上限、溢价档位、佣金、决策池/监视池 |
| `dca_state.json` | 运行时生成（不入库）：积压资金、上次定投月份、定投记录 |
| `alert_state.json` | 运行时生成（不入库）：哨兵边沿状态（极端溢价是否已报过、申购状态快照） |
| `fee_cache.json` | 运行时生成（不入库）：东财费率页抓取缓存，每 7 天刷新，检测到费率变动会提示 |
| `etf_signals.py` | **择时信号**（自 legacy 恢复）：QQQ vs MA200 止盈信号 + 回撤加仓五档（资金池）。参数在 `dca_config.json` 的 `signals` 块 |
| `alloc_state.json` | 运行时生成（不入库）：待命金 / 风暴金余额、已触发档位、上次充值月 |
| `calc_premium_history.py` | 一次性工具：拉 513300 全量 K 线 + 历史净值，重算溢率分布 → `history_premium.csv`（非日常生产依赖） |
| `history_premium.csv` | 513300 历史溢率序列（2023-04 起，约 1400 行：date, close, nav, premium_pct） |

### `legacy/` — 已停用的早期实现（仅追溯，勿引用）

现行实现只有 `etf_skill/` 一套（日报 + 周报：多标的比价 + 溢价档位）。legacy 里的东西**全部已被取代，不再被任何 cron/脚本引用**：

| 文件 | 代际 | 与现行体系的关系 |
|------|------|------------------|
| `etf_check_v1.3_2026-05.py` | V1.3（2026-05） | 单标的 513300 巡检：新浪 K 线 / 东财净值 / 蛋卷 PE / Yahoo QQQ+VIX，含 QQQ MA200 止盈、回撤加仓档位、子弹余额（改常量维护）。**这些择时机制现行体系没有**——现用溢价档位 + 积压（`backlog`）替代 |
| `etf_check_2026-06.py` | 过渡版（2026-06） | 单标的 + btcdca 评分 + historyofmarket；已被多标的日报取代 |
| `etf_monitor/` | 实验版（2026-05） | 模块化分仓加仓 + 回撤档位（-8/-15/-22/-30/-40%，待命金/风暴金）+ 早盘/收盘简报 |
| `run_dca_brief.sh`、`run_dca_brief.hermes-wrapper.sh` | 2026-05 | 指向 `etf_monitor/dca_brief.py` 的入口，目标脚本已停用 |
| `etf_state.json` | 2026-06 | 单标的溢价状态（`high_premium_date`/`sold`/`paused`），当前无任何引用；现行状态文件是 `etf_skill/dca_state.json` |

> 若以后要用回撤加仓 / QQQ MA200 择时，从这里或 git 历史取——它们**未接入现行日报/周报**。

### `docs/`

| 文件 | 说明 |
|------|------|
| `marketgrep-api.md` | marketgrep.com `/api/summary` 接口逆向笔记 |
| `513300-premium-history.md` | 513300 溢价历史分析与结论 |
| `wrappers/` | Hermes cron wrapper 的副本（真实文件在 `~/.hermes/scripts/`） |

---

## 纳指回撤（QQQ）

`etf_daily.py` 末尾输出一节「📉 纳指回撤（QQQ）」（模块 `etf_signals.py`，数据源 Yahoo QQQ 日线，必须走 7890 代理 + 短 UA），**只有一行**：QQQ 现价 ｜ 自 52 周高点回撤 x%（高点相隔几个交易日）。

档位表 / 加仓池 / 触发提醒的**逻辑保留在代码里，但默认不输出**：开关是 `dca_config.json` 的 `signals.show_levels`（默认 `false`）。置 `true` 则恢复完整输出 —— 五档 `-8% → 300`、`-15% → 500`、`-22% → 500`、`-30% → 500`、`-40% → 500`，每月注入 1000 元的加仓池余额、触发时扣减余额并去重（回撤修复到 -8% 以内自动清空、视为新一轮）。恢复后它与月度定投是两笔独立的钱。

> **止盈信号（QQQ MA200，threshold 20/12/0）已于 2026-10-03 移除。** 用 1999–2026 全历史验证后不成立：`>20% 止盈` 的劣势完全由 2000–2002 泡沫期定义（2020–2026 反而比基准好 7pct），事件化后"上穿 20%"其后 12 个月 9/9 全部上涨；`跌破 MA200 = 熊市` 同样不成立（其后 12 个月 +10.3%，基准 +11.5%）。完整数据见 [`docs/qqq-ma200-validation.md`](docs/qqq-ma200-validation.md)。

> ⚠️ 加仓与溢价的张力：QDII 溢价常在下跌中扩大，「回撤触发加仓」与「溢价高 → 减半/暂停」会同时出现。当前只提示溢价偏高，不加硬约束。

---

## 数据源

| 来源 | 用途 |
|------|------|
| `qt.gtimg.cn/q=sh513390,sz159660,...` | 场内实时价，批量（GBK 编码） |
| `web.ifzq.gtimg.cn/appstock/app/fqkline` | 日 K：交易日历 + 20 日均成交额 |
| `api.fund.eastmoney.com/f10/lsjz` | 基金官方净值（需带 Referer/UA） |
| `fundf10.eastmoney.com/jjfl_{code}.html` | 管理费 + 托管费（日报每 7 天刷新） |
| `www.btcdca.me/nasdaq/api/score` | btcdca 定投评分（0-100，越高越贵；日报已不再使用） |
| `query1.finance.yahoo.com/v8/finance/chart/QQQ` | QQQ 日线（回撤加仓档位用；必须走代理 + 短 UA） |
| `historyofmarket.com/api/ndx/*` | NDX 前瞻 PE、收益拆解、滚动 5 年、VXN、回撤 |
| `www.marketgrep.com/api/summary` | VIX / RSI / 市场情绪 / 湍流 |

**溢率口径**：`收盘价(T) ÷ 官方净值(T 的前一个 A 股交易日) − 1`。QDII 净值按美股收盘计价，A 股 T 日收盘时可知的最新美股信息是美股 T-1 收盘，故 T 日价格与 T-1 净值配对（与券商 App / 腾讯行情显示值同口径）。09:20 盘前运行时用昨收；该净值未公布时退用更早净值并标注滞后交易日数。

**周报数据质量规则**（2026-11-05 起；2026-11-08 口径修正）：
- 数据源**三级新鲜度分级**：正常（有日期且在允许更新周期内）/ 需关注（成功但无日期戳，新鲜度无法核验——仅参考，不作当期判断）/ 不可用（缺失、异常或超更新周期——按数据缺口处理，不硬凑）。**获取成功 ≠ 数据可靠 ≠ 数据足够新**；①正文各行对陈旧数据内联挂 `⚠` 标记。
- **溢价三个日期必须分开看**：场内价格交易日 / 基金净值估值日（QDII 滞后 1~2 日）/ 纳指行情美股交易日；周日发布展示的是最近交易日快照，非周日实时。
- **溢价收缩风险量化**（与指数涨跌是两个独立风险）：若净值不变，溢价从 p 收缩至 t，场内价变化 = `(1+t)/(1+p)−1`（例：15%→0% 即 −13.0%，15%→5% 即 −8.7%）。纯算术情景，非预测，实际影响取决于净值、汇率与溢价的同步变化。
- **P 值样本构成披露**：分布基底 = 513300 全史收盘 CSV（至 2026-09 停更）+ 各基金近 120 日修正口径（premium_log）——对非 513300 标的是「QDII 溢价环境」分位参考，非本基金自身全史；**P100 = 现有样本最高区，非历史绝对极值**。
- 汇率指标是 **USD/CNY**：上涨 = 美元升值 = QDII 人民币净值增厚（正向）。
- 指数/汇率拆解用**乘法** `(1+n)×(1+f)−1`，时间区间美股收盘对齐同一区间；且是同期指数表现，非已公布净值变动（QDII 估值日滞后）。
- 百分位一律注明「参照该指标自身历史分布」；滚动收益为负的占比标注「历史频率，非未来概率」，并披露样本画像（窗口数/起止/计算频率——日频滚动窗口高度重叠，占比 ≠ 独立概率）。
- 指数回撤只报**分档区间**（轻微<10% / 中等 -10~-20% / 深 -20~-40% / 极端）+ 样本内最深处；历史极端回撤是事实记录，不构成本轮底部预期。
- AI 龙头估值：Forward PE 与隐含 EPS 增速同源同快照；增速 = trailing/forward−1 反推的**市价隐含值**，非分析师预测，预测周期未逐家核验——只做相对比较；对 513390 的意义是观察纳指100盈利支撑，不是选股。
- 持仓三态（有/明确无/数据不可用）+ 交叉一致性（position 有持仓但 dca_state 无记录 → 提示口径不可信）；持仓文件系统只读不写，空账本永不自动清零。
- 月报执行核验四态：成交（金额级，成交价原系统不记录如实标注）/ 未执行 / 休市顺延（给出应执行日）/ 无法核实（有标记无明细，不当作未执行）。累计只认执行记录。

**定投规则**（`dca_config.json`）：每月 15 日（遇休市顺延到下一个交易日）按决策池最低溢价标的执行。**金额恒为 `monthly_base_amount`（1000），不随溢价变动**——溢率只影响入场价，不影响每笔金额（2026-10-14 拍板废除档位制；`premium_tiers` 现只剩一个标准档，积压/加码代码保留但不再触发）。高溢率时要动的是**通道**（场外联接按净值成交，先查申购状态），不是金额。

**哨兵告警开关**（`dca_config.json` 的 `alerts` 块，缺省全开，缺的键回落默认值）：

```json
"alerts": {
  "halt_notice": true,            // 停牌/停复牌公告（事件去重：同基金同标题连续出现不重复报，标题变化才再报）
  "extreme_premium_pctile": 95,   // 溢价历史百分位 ≥ 此值报（边沿触发；档位制已废除，不用绝对阈值）
  "sub_status_change": true,      // 场外联接申购状态翻转
  "fee_change": true              // 费率变动
}
```

> 去重优先级：①公告 ID（新 ID 是必要条件）→ ②发布日期+基金代码（例行重申拦截）→
> ③标题变化（辅助依据，标题变才再报）。**已知局限**：停牌时段/复牌时间在正文 PDF 里
> （有反爬挑战页），正文级关键字段变化检测不可行——「同标题但停牌时段改了」检测不到；
> 补偿手段：`alerts.halt_remind_every_days: N`（N 天重申一次，0=完全静默）。

---

## 输出

- Telegram：stdout 由 cron `no_agent` 模式直接投递
- Obsidian 存档：`/media/gyan/INFO/information/AITrader/策略日报/`（vault 不可写时回退 `~/hermes/vault/`）

## 免责

个人研究用途，非投资建议。溢率/评分阈值均为个人设定，未经验证。
