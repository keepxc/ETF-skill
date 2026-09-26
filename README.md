# ETF 监控脚本（513300 纳指 ETF 定投）

A 股场内 **513300 纳斯达克ETF华夏** 的定投监控与每日/每周简报工具集。
由本机 Hermes cronjob 驱动，输出推送到 Telegram 并写 Obsidian 存档。

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
| `etf_check.py` | 旧版综合简报（早期版本，保留参考） |
| —— 见根目录 `etf_check.py` | **V1.3 巡检版**（2026-05，数据源：新浪 K 线/东财净值/蛋卷 PE/Yahoo QQQ+VIX，含子弹余额逻辑）。远端仓库遗留文件，保留未删 |
| `calc_premium_history.py` | 拉全量 K 线 + 历史净值，算历史溢率分布 → `history_premium.csv` |
| `history_premium.csv` | 513300 历史溢率序列（2023-04 起，约 1400 行：date, close, nav, premium_pct） |
| `etf_state.json` | 溢价/暂停状态（`high_premium_date` / `sold` / `paused`） |

### `etf_monitor/` — 早期定投策略实验（模块化）

分仓加仓 + 溢价控制 + 回撤档位的完整策略实现，后来精简成 `etf_skill/etf_daily.py`。

| 文件 | 说明 |
|------|------|
| `etf513300.py` | 数据工具：实时价 / K 线 / MA（httpx） |
| `nasdaq_dca.py` | 定投策略：溢价阈值（>3% 不买）、月投额、加仓判定 |
| `nasdaq_drawdown.py` | 回撤追踪 + 分仓档位（-8%/-15%/-22%/-30%/-40%，待命金/风暴金） |
| `dca_brief.py` | 定投早盘简报（含回撤追踪 + 分仓加仓） |
| `daily_brief.py` / `close_report.py` | 早盘简报 / 收盘报告 |
| `send_via_hermes.py` | 通过 `hermes send_message` 推 Telegram |
| `nasdaq_state.json` | 待命金/风暴金余额与已触发档位 |

### `docs/`

| 文件 | 说明 |
|------|------|
| `marketgrep-api.md` | marketgrep.com `/api/summary` 接口逆向笔记 |
| `513300-premium-history.md` | 513300 溢价历史分析与结论 |
| `wrappers/` | Hermes cron wrapper 的副本（真实文件在 `~/.hermes/scripts/`） |

---

## 数据源

| 来源 | 用途 |
|------|------|
| `qt.gtimg.cn/q=sh513390,sz159660,...` | 场内实时价，批量（GBK 编码） |
| `web.ifzq.gtimg.cn/appstock/app/fqkline` | 日 K：交易日历 + 20 日均成交额 |
| `api.fund.eastmoney.com/f10/lsjz` | 基金官方净值（需带 Referer/UA） |
| `fundf10.eastmoney.com/jjfl_{code}.html` | 管理费 + 托管费（日报每 7 天刷新） |
| `www.btcdca.me/nasdaq/api/score` | btcdca 定投评分（0-100，越高越贵；日报已不再使用） |
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
