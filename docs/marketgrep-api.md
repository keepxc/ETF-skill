# MarketGrep — US Market Temperature API

Same author as historyofmarket.com (GREP24). Provides daily market environment snapshot.

Base: `https://www.marketgrep.com/`
Updated: Every US trading day at 20:00 ET (08:00 CST next day)
llms.txt: https://www.marketgrep.com/llms.txt (detailed API docs)

## Key Endpoint: `/api/summary`

Compact one-shot snapshot of US + global market conditions.

```json
{
  "us": {
    "updated_at": "2026-06-19T06:00:00Z",
    "exposure_score": 69.5,
    "exposure_level": "positive",
    "vix": 16.4,
    "dspx": 41.93,
    "cor1m": 8.02,
    "move": 69.36,
    "pct_from_52w_high_spy": -1.8,
    "regime": "risk_on",
    "data_quality": "live"
  },
  "global": {
    "exposure_score": 65.74,
    "exposure_level": "positive",
    "pct_from_52w_high_spy": -1.26,
    "regime": "risk_on"
  },
  "turbulence": {
    "state": "NORMAL",
    "state_color": "#6b8f7b",
    "position_size_pct": 100
  }
}
```

### Key Fields

| Field | Meaning | Current Value |
|-------|---------|--------------|
| `regime` | Market risk regime: `risk_on` / `risk_off` / `transition` | `risk_on` |
| `exposure_score` | 0-100, higher = more bullish | 69.5 |
| `exposure_level` | `positive` / `neutral` / `negative` | `positive` |
| `vix` | VIX level | 16.4 |
| `pct_from_52w_high_spy` | SPY distance from 52w high | -1.8% |
| `dspx` | Dispersion index (higher = more stock-level divergence) | 41.93 |
| `cor1m` | 1-month average correlation between SPX members | 8.02 |
| `move` | MOVE bond volatility index | 69.36 |
| `turbulence.state` | Market stress regime | `NORMAL` |
| `turbulence.position_size_pct` | Recommended position size | 100% |

## Other Useful Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/agent-context` | Plain-English summary + day-over-day delta (AI-friendly) |
| `/api/market-overview` | Full US dashboard: SPX/NDX/DJI/RUT breadth, sector exposure |
| `/api/turbulence` | Turbulence index time series |
| `/api/most-active` | Most-active US tickers with relative volume |
| `/api/sentiment-report` | WSB ticker sentiment |

## Integration Note

**Used in the daily report since 2026-06-23.** The `/api/summary` endpoint fuels the `🌡 市场:` line in the daily 513300 report.

### Rendering Logic

```python
# From etf_daily.py fetch_marketgrep():
u = response["us"]
t = response["turbulence"]

# Regime label
rl = "🔵 Risk ON" if "risk_on" in u["regime"] else "🔴 Risk OFF" if "risk_off" in u["regime"] else u["regime"]

# Dispersion
if u["dspx"] > 35:       disp = "分散度高"
elif u["dspx"] > 25:     disp = "分散中等"
else:                     disp = "集中度高"

# Correlation
if u["cor1m"] < 15:      cor_str = "个股分化"
elif u["cor1m"] < 30:    cor_str = "板块联动"
else:                     cor_str = "同涨同跌"

line = f"🌡 市场: {rl} ({u['exposure_score']}) | {disp} | {cor_str} | 湍流{t['state']}"
```

### DCA Interpretation

| MarketGrep signal | Meaning for DCA |
|-------------------|-----------------|
| Risk ON + high score | Normal environment, no reason to skip DCA |
| Risk OFF + low score | Caution — reduce or pause if also overvalued |
| High dispersion + low correlation | Stock-picking market — index DCA fine |
| Turbulence NORMAL | No systemic stress |
| Turbulence HIGH | Tail risk — consider pausing new entries |
