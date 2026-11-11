"""13 只场内纳指基金的横向体检：美元净值收益率 + 溢价 + 费率 + 现金比例趋势。

口径铁律（照《2026年场内13支纳指基金收益点评》的方法，已复现验证差 +0.32pct 全部来自
汇率口径：他用央行中间价，本模块用新浪即期）：

1. **收益率必须用美元净值**。人民币净值里含汇率共同项（2026 前十个月汇率 -4.5%，把
   12pct 的美元收益压成 7pct）；场内价格更糟——同期价格 13~21%（差 8pct），差的
   那 7pct 全是溢价变动，不是基金能力。用价格收益率选基金 = 追已经涨完的溢价。
2. **现金占净比取最新季报并显示四季度趋势**。现金堆积 = 拿到申购的钱但换不到外汇
   额度，是额度紧张的直接证据；静态平均值会掩盖方向（159501 从 3.74% 升到 7.62%，
   平均口径看起来只有 6.0%）。
3. 换仓判断按量纲统一后的机械规则，不给主观建议：**1pct 溢价 ≈ 10 年现金拖累**
   （现金差 1pct × 纳指年化 10%），所以溢价差 >2pct 时只看溢价，<0.5pct 才轮到
   比费率和现金。
"""
import datetime
import json

import etf_daily as daily

CN_NAME = {
    "513100": "国泰", "159941": "广发", "513300": "华夏", "159632": "华安",
    "159501": "嘉实", "159513": "大成", "159659": "招商", "159696": "易方达",
    "513390": "博时", "159660": "汇添富", "513870": "富国", "513110": "华泰柏瑞",
    "161130": "易方达LOF",
}
# 161130 是联接 LOF，按新规明年停止场内交易 → 数据照跑，但标注不可买
DELISTING = {"161130": "明年停场内"}


def _nav_window(code, target, back=20, fwd=4):
    """取 target 附近的净值窗口。东财 lsjz 的 startDate/endDate 生效，但一页固定只回 20 条
    （倒序）→ 必须按端点分别请求，不能拉一个大区间再翻第一页。"""
    d0 = datetime.date.fromisoformat(target)
    s = (d0 - datetime.timedelta(days=back)).isoformat()
    e = (d0 + datetime.timedelta(days=fwd)).isoformat()
    url = (f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}"
           f"&pageIndex=1&pageSize=20&startDate={s}&endDate={e}")
    raw = daily._get(url, referer=f"https://fund.eastmoney.com/{code}.html", timeout=15)
    out = {}
    for x in json.loads(raw).get("Data", {}).get("LSJZList", []):
        if x.get("DWJZ"):
            try:
                out[x["FSRQ"]] = float(x["DWJZ"])
            except (TypeError, ValueError):
                continue
    return out


def _pick(navs, target):
    c = [x for x in navs if x <= target]
    return max(c) if c else None


def _fx_at(fx, day):
    k = [x for x in fx if x <= day]
    return fx[max(k)] if k else None


def usd_return(code, start, end, fx):
    """(start, end] 区间的美元净值收益率（%）。返回 (ret, d0, d1) 或 (None, ..)"""
    navs = _nav_window(code, start)
    navs.update(_nav_window(code, end))
    a, b = _pick(navs, start), _pick(navs, end)
    if not (a and b) or a == b:
        return None, a, b
    fa, fb = _fx_at(fx, a), _fx_at(fx, b)
    if not (fa and fb):
        return None, a, b
    return ((navs[b] / fb) / (navs[a] / fa) - 1) * 100, a, b


def asset_alloc(code):
    """最新季报的股票/现金占净比 + 规模 + 近四季现金比例（旧→新）。解析失败返回 None。"""
    try:
        t = daily._get(f"https://fundf10.eastmoney.com/zcpz_{code}.html", timeout=15)
    except OSError:
        return None
    import re
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    # 报告期 股票占净比 债券占净比(可能 ---) 现金占净比 净资产（亿元）
    rows = re.findall(
        r"(20\d{2}-\d{2}-\d{2}) ([\d.]+)% (?:---|[\d.]+%) ([\d.]+)% ([\d.]+)", txt)
    if not rows:
        return None
    rows = rows[:5]
    latest = rows[0]
    return {
        "date": latest[0],
        "stock": float(latest[1]),
        "cash": float(latest[2]),
        "size": float(latest[3]),
        "cash_hist": [float(r[2]) for r in reversed(rows)],  # 旧→新
    }


def collect(codes, fx=None, quotes=None, today=None):
    """返回每只基金的体检记录（失败项带 err，不中断整批）。

    **统一收益终点**：各只净值公布日不同（T+1 / T+2 混杂，实测有 11-09 和 11-10 两种），
    各取自己最新会让极差里混进 1 天纳指涨跌（跌幅 1% 的日子就足以造出假的「差异」）。
    先扫一遍各自最新净值日，取**最小值**作共同终点——宁可整体晚一天，也要可比。
    """
    today = today or datetime.date.today()
    fx = fx if fx is not None else (daily.fetch_fx_closes() or {})
    quotes = quotes if quotes is not None else daily.fetch_quotes(codes)
    ndx = daily.fetch_ndx_closes(20) or {}

    latest = {}
    for c in codes:
        try:
            nv = _nav_window(c, str(today), back=25)
            latest[c] = max(nv) if nv else None
        except (OSError, ValueError, KeyError):
            latest[c] = None
    known = [v for v in latest.values() if v]
    common = min(known) if known else str(today)

    ytd_start = f"{today.year - 1}-12-31"
    m12_start = (today - datetime.timedelta(days=365)).isoformat()

    out = []
    for c in codes:
        rec = {"code": c, "name": CN_NAME.get(c, c), "err": None, "nav_end": common,
               "nav_lag": latest.get(c)}
        try:
            r, a, b = usd_return(c, ytd_start, common, fx)
            rec["ytd"] = r
            rec["ytd_range"] = (a, b)
        except (OSError, ValueError, KeyError):
            rec["ytd"] = None
            rec["ytd_range"] = (None, None)
        try:
            r, a, b = usd_return(c, m12_start, common, fx)
            rec["y12"] = r
            rec["y12_range"] = (a, b)
        except (OSError, ValueError, KeyError):
            rec["y12"] = None
            rec["y12_range"] = (None, None)

        # 溢价（修正口径：净值按纳指+汇率折算到最新美股收盘日）
        rec["prem"] = None
        q = quotes.get(c)
        if q and q.get("price"):
            try:
                navs = daily.fetch_navs(c)  # 最近 20 条，够最新端点
                if navs:
                    nd0 = max(navs)
                    cn, _ref, _nr, _fr = daily.correct_nav(nd0, navs[nd0], ndx, fx)
                    if cn:
                        rec["prem"] = (q["price"] / cn - 1) * 100
                        rec["prem_nav_date"] = nd0
            except (OSError, ValueError, KeyError):
                pass
        rec["price"] = q.get("price") if q else None

        try:
            rec["fee"] = daily.fetch_fee(c)
        except (OSError, ValueError):
            rec["fee"] = None

        alloc = asset_alloc(c)
        if alloc:
            rec.update({"cash": alloc["cash"], "size": alloc["size"],
                        "cash_hist": alloc["cash_hist"], "alloc_date": alloc["date"]})
        else:
            rec["cash"] = rec["size"] = rec["cash_hist"] = rec["alloc_date"] = None

        if c in DELISTING:
            rec["err"] = DELISTING[c]
        out.append(rec)
    return out


def _trend(hist):
    """四季现金比例方向：↑↑ 连升 / ↑ 最新升 / ↓ 最新降 / —"""
    if not hist or len(hist) < 2:
        return "—"
    if len(hist) >= 3 and hist[-1] > hist[-2] > hist[-3]:
        return "↑↑"
    return "↑" if hist[-1] > hist[-2] else "↓"


def _pad(s, width):
    """按显示宽度补空格（中文占 2 列），否则 161130 的「易方达LOF」会把整张表挤歪"""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)
    return s + " " * max(0, width - w)


def render(codes, cfg=None, mv=None, today=None):
    """月报「基金体检」节的文本行。mv=持仓市值，用于把溢价差折算成钱。"""
    cfg = cfg or {}
    fc = cfg.get("fund_compare") or {}
    recs = collect(codes, today=today)
    ok = [r for r in recs if r.get("ytd") is not None]
    # 可交易集合：退市/停止场内交易的标的（161130）不参与溢价排名与换仓建议——
    # 它溢价低是 LOF 机制使然，按它给的「换过去」是买不到的方案。
    tradeable = [r for r in ok if r["code"] not in DELISTING]
    L = ["", "基金体检 · 13 只 ──────────────"]

    if not ok:
        L.append("  ⚠ 全部取数失败——本节跳过（不影响上面定投核对）")
        return L

    d1 = max((r["ytd_range"][1] or "" for r in ok), default="")
    date_str = f"{ok[0]['ytd_range'][0]} → {d1}"
    L.append(f"  口径 美元净值（剔汇率）· {date_str} · 各只净值公布日不同，统一取最晚公共日")
    L.append("       价格口径会把溢价变动算成收益（同期差 8pct），不用")
    L.append(f"  收益 年初至今最高 {max(ok, key=lambda r: r['ytd'])['name']} "
             f"{max(r['ytd'] for r in ok):+.1f}% · "
             f"最低 {min(ok, key=lambda r: r['ytd'])['name']} "
             f"{min(r['ytd'] for r in ok):+.1f}% · 极差 {max(r['ytd'] for r in ok) - min(r['ytd'] for r in ok):.1f}pct")
    L.append("")

    # 逐只一行：代码 名称 YTD 溢价 费率 现金(趋势) —— 按 YTD 降序
    for r in sorted(ok, key=lambda x: -x["ytd"]):
        ytd = f"{r['ytd']:+.1f}%"
        prem = f"{r['prem']:+.1f}%" if r.get("prem") is not None else "—"
        fee = f"{r['fee']:.2f}%" if r.get("fee") is not None else "—"
        cash = (f"{r['cash']:.1f}%{_trend(r.get('cash_hist'))}"
                if r.get("cash") is not None else "—")
        flag = f" ⚠{r['err']}" if r["code"] in DELISTING else ""
        L.append(f"  {r['code']} {_pad(r['name'], 10)}{ytd:>7} 溢价{prem:>7} "
                 f"费{fee:>6} 现金{cash:>7}{flag}")

    failed = [r["code"] for r in recs if r.get("ytd") is None]
    if failed:
        L.append(f"  ⚠ 取数失败 {len(failed)} 只 {','.join(failed)}——不参与本节判断")

    # ── 判读：量纲统一后给机械结论（只用可交易标的） ──
    L.append("")
    prems = [r["prem"] for r in tradeable if r.get("prem") is not None]
    if prems:
        spread = max(prems) - min(prems)
        ytd_spread = max(r["ytd"] for r in ok) - min(r["ytd"] for r in ok)
        L.append(f"  判读 净值极差 {ytd_spread:.1f}pct ≈ 费率量级；可交易标的溢价极差 {spread:.1f}pct "
                 f"→ 溢价是主变量（1pct 溢价 ≈ 10 年现金拖累）")
        pos_code = None
        try:
            posj = daily._load(daily.POS_PATH, None) or {}
            if posj.get("positions"):
                pos_code = posj["positions"][0].get("code")
        except (OSError, ValueError):
            pass
        cur = next((r for r in tradeable if r["code"] == pos_code), None)
        priced = [r for r in tradeable if r.get("prem") is not None]
        cheap = min(priced, key=lambda r: r["prem"]) if priced else None
        if cur and cur.get("prem") is not None and cheap and cheap["code"] != cur["code"]:
            diff = cur["prem"] - cheap["prem"]
            money = f" ≈ {diff / 100 * mv:,.0f} 元" if mv else ""
            head = (f"  换仓 最低 {cheap['code']} {cheap['name']} {cheap['prem']:+.1f}% · "
                    f"比 {cur['name']} 低 {diff:.1f}pct{money}")
            sw = fc.get("switch_prem_pct", 2.0)
            if diff > sw:
                L.append(head + " · 核对流动性后可考虑")
            elif diff > fc.get("tie_prem_pct", 0.5):
                L.append(head + f" · 不足 {sw}pct 门槛，不动")
            else:
                L.append(head + " · 已在第一梯队，不动")
            # 溢价的便宜要跟费率的贵对冲（单独成行，避免换仓行折成 3 行）
            fee_gap = (cheap.get("fee") or 0) - (cur.get("fee") or 0)
            if fee_gap > 0.001:
                L.append(f"  权衡 它费率高 {fee_gap:.2f}pct/年，"
                         f"单靠溢价优势需 {diff / fee_gap:.1f} 年回本")
        elif cur:
            L.append(f"  换仓 持仓 {cur['code']} 已是可交易标的中最低溢价，无换仓理由")
    L.append("  注 161130 为联接 LOF，按新规明年停止场内交易，收益照列但不可买")
    return L
