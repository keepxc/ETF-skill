# ETF 监控脚本（纳指 100 场内 ETF 定投）

纳指 100 场内 ETF 的**多标的比价 + 溢价档位定投**监控，附每日 / 每周简报。
由本机 Hermes cronjob 驱动，输出推送到 Telegram。

> 决策池与档位见 `etf_skill/dca_config.json`（现为 513390 / 513870 / 159660；早期版本只做单标的 513300，见 `legacy/`）。

> ⚠️ 本仓库的**文件就位于生产路径** `/home/gyan/scripts/`，不是拷贝。
> 修改后 git 会跟踪；cron 直接跑的就是这里的文件。

---

## 每日/每周任务（Hermes cronjob）

| 任务名 | 调度 (CST) | 入口 wrapper | 实际脚本 |
|--------|-----------|--------------|----------|
| ETF 513300 每日快报 | `20 9 * * 1-5` | `~/.hermes/scripts/etf_check.sh` | `etf_skill/etf_daily.py` |
| 纳指深度周报 | `30 9 * * 1` | `~/.hermes/scripts/etf_weekly.sh` | `etf_skill/etf_weekly.py` |

wrapper 内容只有两行，例如：

```bash
#!/bin/bash
cd /home/gyan/scripts/etf_skill && python3 etf_daily.py
```

手动运行（与 cron 完全同路径）：

```bash
bash ~/.hermes/scripts/etf_check.sh      # 每日快报
bash ~/.hermes/scripts/etf_weekly.sh     # 深度周报
```

---

## 目录

### `etf_skill/` — 现行生产脚本

| 文件 | 说明 |
|------|------|
| `etf_daily.py` | **日报**（当前 cron 用）。决策池多标的比价 → 按溢价档位给出定投金额与标的；监视池低溢价/费率变动提示；PE/VIX/市场状态 |
| `dca_config.json` | 日报配置：月投基准、定投日、积压上限、溢价档位、佣金、决策池/监视池 |
| `dca_state.json` | 运行时生成（不入库）：积压资金、上次定投月份、定投记录 |
| `fee_cache.json` | 运行时生成（不入库）：东财费率页抓取缓存，每 7 天刷新，检测到费率变动会提示 |
| `etf_weekly.py` | **周报**。NDX PE / 收益拆解 / 滚动 5 年 / VXN / 回撤 / Mag7 AI 估值 六维全景 |
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

## 回撤加仓档位（资金池）

`etf_daily.py` 末尾输出一节回撤加仓档位（模块 `etf_signals.py`，2026-10 自 `legacy/etf_monitor/nasdaq_drawdown.py` 恢复）：

- 按 QQQ 自 52 周高点的回撤给档位：`-8% → 300`、`-15% → 500`、`-22% → 500`、`-30% → 500`、`-40% → 500`，从待命金 / 风暴金出钱
- **资金池没有月度充值**（月度定投是每月 1000 基准、不拆分，legacy 的「150/50 月充值」已移除）：来源是止盈回款 + 人工注入，余额手工维护
- 同一档位触发一次后记 `✅已用`，回撤修复到 `-8%` 以内自动清空、视为新一轮（这条重置逻辑是恢复时补的，原版没有）
- 数据源：Yahoo Finance QQQ 日线（必须走 7890 代理；**短 UA**，完整浏览器 UA 会被 429）

参数全在 `dca_config.json` 的 `signals` 块（改参数不用动代码）。**它与月度定投互不替代**：定投按溢价档位定额，加仓从资金池出钱，是两笔独立的钱。

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

**定投规则**（`dca_config.json`）：每月 15 日（遇休市顺延到下一个交易日）按决策池最低溢价定档：`<6%` 投 max(1500, 1000+全部积压)、`6–10%` 投 1000、`10–14%` 投 500、`>14%` 暂停；少投部分计入积压，上限 5000。

---

## 输出

- Telegram：stdout 由 cron `no_agent` 模式直接投递
- Obsidian 存档：`/media/gyan/INFO/information/AITrader/策略日报/`（vault 不可写时回退 `~/hermes/vault/`）

## 免责

个人研究用途，非投资建议。溢率/评分阈值均为个人设定，未经验证。
