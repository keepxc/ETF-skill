"""纳指择时信号：QQQ vs MA200 止盈 + 回撤加仓档位（自 legacy 恢复）

出处
----
- 止盈信号   legacy/etf_check_v1.3_2026-05.py       dev200 阈值 20 / 12 / 0
- 回撤加仓   legacy/etf_monitor/nasdaq_drawdown.py  五档 + 待命金 / 风暴金 资金池

定位（与月度定投是两笔独立的钱）
----
  · 月度定投 = 溢价档位定额，走 etf_daily.plan_amount（本金按 dca_config 的 base/backlog）
  · 回撤加仓 = 从资金池（待命金 / 风暴金）出钱，本模块只做提示 + 去重，不自动交易
  · 止盈资金  → 入待命金（人工执行）
数据源：Yahoo Finance QQQ 日线（必须走 7890 代理）+ 腾讯 usQQQ 实时价。
参数集中在 dca_config.json 的 "signals" 块，本文件只留默认值兜底。
"""
import json, time, datetime, urllib.request
from pathlib import Path

HERE       = Path(__file__).resolve().parent
ALLOC_PATH = HERE / "alloc_state.json"
PROXY      = "http://127.0.0.1:7890"
UA         = "Mozilla/5.0"   # Yahoo 对完整浏览器 UA 会走 429 限流通道，短 UA 才通

# 与 legacy 一致的默认参数（可被 dca_config.json["signals"] 覆盖）
DEFAULTS = {
    "qqq_ma200": {"trim_pct": 20.0, "warn_pct": 12.0, "range": "2y"},
    "drawdown_levels": [
        {"level": 8,  "amount": 300, "source": "待命金"},
        {"level": 15, "amount": 500, "source": "待命金"},
        {"level": 22, "amount": 500, "source": "待命金+风暴金"},
        {"level": 30, "amount": 500, "source": "风暴金"},
        {"level": 40, "amount": 500, "source": "风暴金"},
    ],
    "monthly_reserve": 150,
    "monthly_storm": 50,
}

# 初始资金池（沿用 legacy/etf_monitor/nasdaq_state.json 的余额）
INIT_STATE = {"reserve_balance": 300, "storm_balance": 100, "triggered_levels": []}


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def cfg_signals(cfg):
    s = json.loads(json.dumps(DEFAULTS))
    user = (cfg or {}).get("signals") or {}
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


# ── 数据 ──────────────────────────────────────────────────

def _http(url, use_proxy=True, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    handlers = ({"http": PROXY, "https": PROXY} if use_proxy else {})
    op = urllib.request.build_opener(urllib.request.ProxyHandler(handlers))
    with op.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_qqq_closes(rng="2y"):
    """Yahoo QQQ 日线收盘序列。必须走代理（直连 403）；短 UA 避免 429；429 时重试。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/QQQ?interval=1d&range={rng}"
    last = RuntimeError("Yahoo QQQ 请求失败")
    for attempt in range(3):
        try:
            d = json.loads(_http(url, use_proxy=True))
            closes = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [c for c in closes if c]
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def fetch_qqq_realtime():
    """腾讯 usQQQ 实时价（失败返回 None，调用方降级用日线收盘）。"""
    try:
        raw = _http("https://qt.gtimg.cn/q=usQQQ", timeout=10)
        f = raw.split("~")
        return {"price": float(f[3]), "prev_close": float(f[4]),
                "change_pct": float(f[32]) if len(f) > 32 and f[32] else None}
    except Exception:
        return None


# ── 信号计算 ──────────────────────────────────────────────

def ma200_signal(closes, trim_pct=20.0, warn_pct=12.0):
    if len(closes) < 200:
        return None
    ma = sum(closes[-200:]) / 200
    dev = (closes[-1] - ma) / ma * 100
    if dev > trim_pct:
        sig = f"🔴 乖离 {dev:+.2f}%，考虑止盈波段仓"
    elif dev > warn_pct:
        sig = f"🟡 乖离 {dev:+.2f}%，偏高，持有观望"
    elif dev > 0:
        sig = f"🟢 乖离 {dev:+.2f}%，正常"
    else:
        sig = f"🔵 乖离 {dev:+.2f}%，价格低于 MA200（熊市信号）"
    return {"ma200": round(ma, 2), "dev": round(dev, 2), "signal": sig}


def drawdown(closes, lookback=252):
    w = closes[-lookback:]
    high, cur = max(w), w[-1]
    return {"high": round(high, 2), "current": round(cur, 2),
            "dd": round((cur - high) / high * 100, 2),
            "days_since_high": len(w) - 1 - w.index(high)}


def topup(state, sig_cfg):
    """每月充值待命金/风暴金（幂等）"""
    month = datetime.date.today().strftime("%Y-%m")
    if state.get("last_topup_month") == month:
        return False
    state["reserve_balance"] = state.get("reserve_balance", 0) + sig_cfg["monthly_reserve"]
    state["storm_balance"]   = state.get("storm_balance", 0) + sig_cfg["monthly_storm"]
    state["last_topup_month"] = month
    return True


def check_triggers(dd_pct, state, levels):
    already = set(state.get("triggered_levels", []))
    return [lv for lv in levels if dd_pct <= -lv["level"] and lv["level"] not in already]


def reset_if_recovered(dd_pct, state, levels):
    """回撤修复到最小档位以内 → 清空已用档位，视为新一轮（原版没有，这里补上）"""
    if not levels:
        return False
    floor = min(l["level"] for l in levels)
    if dd_pct > -floor and state.get("triggered_levels"):
        state["triggered_levels"] = []
        return True
    return False


# ── 输出 ──────────────────────────────────────────────────

def _bar(pct, width=15):
    filled = int(max(0.0, min(1.0, pct / 100)) * width)
    return "█" * filled + "░" * (width - filled)


def render_sections(cfg, best=None):
    """返回日报用的两节文本（list[str]）。任一数据源失败只影响本节。"""
    sig_cfg = cfg_signals(cfg)
    state = _load(ALLOC_PATH, {"reserve_balance": INIT_STATE["reserve_balance"],
                              "storm_balance": INIT_STATE["storm_balance"],
                              "triggered_levels": [], "last_topup_month": None})
    L, dirty = [], False

    try:
        closes = fetch_qqq_closes(sig_cfg["qqq_ma200"].get("range", "2y"))
        ma = ma200_signal(closes, sig_cfg["qqq_ma200"].get("trim_pct", 20.0),
                          sig_cfg["qqq_ma200"].get("warn_pct", 12.0))
        dd = drawdown(closes)
        rt = fetch_qqq_realtime()
        price = rt["price"] if rt else dd["current"]
        chg = f"（{rt['change_pct']:+.2f}%）" if rt and rt.get("change_pct") is not None else ""

        L += ["", "=" * 48, "  📈 纳指止盈信号（QQQ vs MA200）", "=" * 48]
        if ma is None:
            L.append("  ⚠ QQQ 日线不足 200 根，无法计算 MA200")
        else:
            L.append(f"  QQQ {price:.2f}{chg}   MA200 {ma['ma200']:.2f}")
            L.append(f"  {ma['signal']}")
        L.append(f"  自 52 周高点回撤 {dd['dd']:+.2f}%（高点 {dd['high']:.2f}，{dd['days_since_high']} 个交易日前）")
        if ma and ma["dev"] > sig_cfg["qqq_ma200"].get("trim_pct", 20.0):
            L.append("  ★ 触发止盈阈值：卖出波段仓，回款入待命金（人工执行）")

        # ── 回撤加仓档位 ──
        levels = sig_cfg["drawdown_levels"]
        if topup(state, sig_cfg):
            dirty = True
        if reset_if_recovered(dd["dd"], state, levels):
            dirty = True
        L += ["", "=" * 48, "  📉 回撤加仓档位（资金池）", "=" * 48]
        for lv in levels:
            used = lv["level"] in state.get("triggered_levels", [])
            hit = dd["dd"] <= -lv["level"]
            mark = " ✅已用" if used else (" 🔔触发" if hit else "")
            L.append(f"  -{lv['level']}% [{_bar(abs(dd['dd']) / lv['level'] * 100)}] "
                     f"{lv['amount']}元（{lv['source']}）{mark}")
        L.append(f"  💰 待命金 {state.get('reserve_balance', 0)} 元 | "
                 f"风暴金 {state.get('storm_balance', 0)} 元 | "
                 f"合计 {state.get('reserve_balance', 0) + state.get('storm_balance', 0)} 元")

        trig = check_triggers(dd["dd"], state, levels)
        if trig:
            L.append("  🚨 档位触发（与月度定投是两笔钱）：")
            for t in trig:
                tgt = f"{best['code']} {best['name']}（当前溢价 {best['prem']:+.2f}%）" if best else "决策池最优标的"
                L.append(f"    ⚡ 跌 {t['level']}% → 从{t['source']}转 {t['amount']} 元，买入 {tgt}")
                state.setdefault("triggered_levels", []).append(t["level"])
            if best and best["prem"] >= 10:
                L.append("    注意：当前溢价偏高，加仓成本里含这块溢价")
            dirty = True
        else:
            nxt = next((lv for lv in levels if dd["dd"] > -lv["level"]), None)
            if nxt:
                gap = nxt["level"] - abs(dd["dd"])
                L.append(f"  下一档 -{nxt['level']}%（还差 {gap:.2f} 个点）→ {nxt['amount']}元（{nxt['source']}）")
        L.append("  联动：止盈资金 → 入待命金；回撤触发 → 从池中出钱加仓（人工执行）")
    except Exception as e:
        L += ["", "【择时信号】数据获取失败：%s: %s" % (type(e).__name__, str(e)[:80])]

    if dirty:
        state["last_update"] = datetime.datetime.now().isoformat(timespec="seconds")
        _save(ALLOC_PATH, state)
    return L
