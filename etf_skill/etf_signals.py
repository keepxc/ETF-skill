"""回撤加仓档位（加仓池）—— 自 legacy/etf_monitor/nasdaq_drawdown.py 恢复

定位
----
  · 月度定投 = 每月 1000 基准、按溢价档位定额（不拆分），走 etf_daily.plan_amount
  · 回撤加仓 = 从「加仓池」出钱：**每月注入 1000**（可配），跌到档位时按金额扣减
  · 本模块只做提示 + 记账（去重、余额不足提示），不自动交易
数据源：Yahoo Finance QQQ 日线（必须走 7890 代理）。
参数集中在 dca_config.json 的 "signals" 块，本文件只留默认值兜底。

历史说明
----
原一并恢复的「QQQ vs MA200 止盈信号」已于 2026-10-03 移除：
用 QQQ 1999-2026 全历史验证后不成立（见 docs/qqq-ma200-validation.md）。
"""
import json, time, datetime, urllib.request
from pathlib import Path

HERE       = Path(__file__).resolve().parent
ALLOC_PATH = HERE / "alloc_state.json"
PROXY      = "http://127.0.0.1:7890"
UA         = "Mozilla/5.0"   # Yahoo 对完整浏览器 UA 会走 429 限流通道，短 UA 才通

# 默认参数（可被 dca_config.json["signals"] 覆盖）
DEFAULTS = {
    "show_levels": False,            # False = 只输出 QQQ 回撤一行；True = 恢复完整档位/加仓池
    "monthly_inject": 1000,          # 每月注入加仓池的金额
    "drawdown_levels": [
        {"level": 8,  "amount": 300, "source": "加仓池"},
        {"level": 15, "amount": 500, "source": "加仓池"},
        {"level": 22, "amount": 500, "source": "加仓池"},
        {"level": 30, "amount": 500, "source": "加仓池"},
        {"level": 40, "amount": 500, "source": "加仓池"},
    ],
}

INIT_STATE = {"pool_balance": 0, "triggered_levels": []}


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state():
    """读状态；兼容旧的 reserve/storm 两分池结构（合并为 pool_balance）"""
    st = _load(ALLOC_PATH, None)
    if not isinstance(st, dict):
        return dict(INIT_STATE, triggered_levels=[])
    if "pool_balance" not in st:
        st["pool_balance"] = st.get("reserve_balance", 0) + st.get("storm_balance", 0)
    st.setdefault("triggered_levels", [])
    return st


def cfg_signals(cfg):
    s = json.loads(json.dumps(DEFAULTS))
    for k, v in ((cfg or {}).get("signals") or {}).items():
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


# ── 信号计算 ──────────────────────────────────────────────

def drawdown(closes, lookback=252):
    w = closes[-lookback:]
    high, cur = max(w), w[-1]
    return {"high": round(high, 2), "current": round(cur, 2),
            "dd": round((cur - high) / high * 100, 2),
            "days_since_high": len(w) - 1 - w.index(high)}


def inject_monthly(state, cfg):
    """每月注入加仓池（幂等）"""
    amount = cfg.get("monthly_inject") or 0
    month = datetime.date.today().strftime("%Y-%m")
    if not amount or state.get("last_inject_month") == month:
        return False
    state["pool_balance"] = state.get("pool_balance", 0) + amount
    state["last_inject_month"] = month
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
    """返回日报用的一节文本（list[str]）。数据源失败只影响本节。"""
    sig_cfg = cfg_signals(cfg)
    state = load_state()
    L, dirty = [], False

    try:
        closes = fetch_qqq_closes("2y")
        dd = drawdown(closes)

        levels = sig_cfg["drawdown_levels"]
        pool = state.get("pool_balance", 0)
        show_levels = bool(sig_cfg.get("show_levels", False))
        if show_levels:
            if inject_monthly(state, sig_cfg):
                dirty = True
            if reset_if_recovered(dd["dd"], state, levels):
                dirty = True
            pool = state.get("pool_balance", 0)

        L += ["", "=" * 48, "  📉 纳指回撤（QQQ）", "=" * 48]
        L.append(f"  QQQ {dd['current']:.2f}｜自 52 周高点 {dd['high']:.2f} 回撤 {dd['dd']:+.2f}%"
                 f"（高点 {dd['days_since_high']} 个交易日前）")

        if show_levels:
            for lv in levels:
                used = lv["level"] in state.get("triggered_levels", [])
                hit = dd["dd"] <= -lv["level"]
                mark = " ✅已用" if used else (" 🔔触发" if hit else "")
                L.append(f"  -{lv['level']}% [{_bar(abs(dd['dd']) / lv['level'] * 100)}] {lv['amount']}元{mark}")
            L.append(f"  💰 加仓池 {pool} 元（每月注入 {sig_cfg.get('monthly_inject', 0)} 元）")

            trig = check_triggers(dd["dd"], state, levels)
            if trig:
                L.append("  🚨 档位触发（与月度定投是两笔钱）：")
                for t in trig:
                    tgt = f"{best['code']} {best['name']}（当前溢价 {best['prem']:+.2f}%）" if best else "决策池最优标的"
                    if pool >= t["amount"]:
                        state["pool_balance"] = pool - t["amount"]
                        pool -= t["amount"]
                        note = f"，池余 {pool} 元"
                    else:
                        note = "（池内余额不足，需另行出资）"
                    L.append(f"    ⚡ 跌 {t['level']}% → 买入 {t['amount']} 元 {tgt}{note}")
                    state.setdefault("triggered_levels", []).append(t["level"])
                if best and best["prem"] >= 10:
                    L.append("    注意：当前溢价偏高，加仓成本里含这块溢价")
                dirty = True
            else:
                nxt = next((lv for lv in levels if dd["dd"] > -lv["level"]), None)
                if nxt:
                    gap = nxt["level"] - abs(dd["dd"])
                    L.append(f"  下一档 -{nxt['level']}%（还差 {gap:.2f} 个点）→ {nxt['amount']}元")
    except Exception as e:
        L += ["", "【回撤加仓】数据获取失败：%s: %s" % (type(e).__name__, str(e)[:80])]

    if dirty:
        state["last_update"] = datetime.datetime.now().isoformat(timespec="seconds")
        _save(ALLOC_PATH, state)
    return L
