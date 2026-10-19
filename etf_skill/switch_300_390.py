"""513300 -> 513390 切换成本核算（九月实际数据）"""
import json, urllib.request, time, statistics

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8", tries=4):
    err = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")
        except Exception as e:
            err = e; time.sleep(1.5)
    raise err

def kline_tx(code, start="2026-09-01"):
    mkt = "sh" if code.startswith("5") else "sz"
    u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,{start},2026-12-31,80,"
    d = json.loads(get(u))["data"][mkt + code]
    return {r[0]: float(r[2]) for r in (d.get("day") or d.get("qfqday") or [])}

def navs(code):
    out = {}
    for pg in range(1, 3):
        raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE={code}&pageIndex={pg}&pageSize=100&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        for x in (json.loads(raw).get("Datas") or []):
            if x.get("FSRQ") and x.get("DWJZ"):
                try: out[x["FSRQ"]] = float(x["DWJZ"])
                except (TypeError, ValueError): pass
    return out

res = {}
for code, nm in [("513300","纳斯达克ETF华夏"), ("513390","纳指100ETF博时")]:
    px, nv = kline_tx(code), navs(code)
    rows = []
    for d0 in sorted(px):
        prev = [x for x in sorted(nv) if x < d0]
        if prev:
            nd = prev[-1]
            rows.append((d0, px[d0], (px[d0]/nv[nd]-1)*100))
    sep = [r[2] for r in rows if r[0] < "2026-10-01"]
    oc  = [r[2] for r in rows if r[0] >= "2026-10-01"]
    res[code] = (rows, statistics.median(sep) if sep else None,
                 statistics.median(oc) if oc else None, sep, oc)
    print(f"=== {code} {nm} ===")
    for d0, v, pr in rows:
        print(f"  {d0}  {v:.3f}  溢率 {pr:+6.2f}%")
    if sep: print(f"  九月: 中位 {statistics.median(sep):+.2f}%  均值 {statistics.mean(sep):+.2f}%  区间 {min(sep):+.2f}%~{max(sep):+.2f}%")
    if oc:  print(f"  十月: 中位 {statistics.median(oc):+.2f}%  均值 {statistics.mean(oc):+.2f}%  区间 {min(oc):+.2f}%~{max(oc):+.2f}%")
    print()

p300 = res["513300"][1]; p390 = res["513390"][1]
print("=== 切换的溢价得�失（1 元现金口径）===")
if p300 is not None and p390 is not None:
    nav_sold  = 1 / (1 + p300/100)
    nav_bought= 1 / (1 + p390/100)
    print(f"  卖出 513300（溢价 {p300:+.2f}%）→ 1 元现金对应 NAV {nav_sold:.4f}")
    print(f"  买入 513390（溢价 {p390:+.2f}%）→ 1 元现金买到 NAV {nav_bought:.4f}")
    print(f"  NAV 得失 = {(nav_bought-nav_sold)/nav_sold*100:+.2f}%")
    print(f"  即每 10,000 元切换：{10000*(nav_bought-nav_sold)/nav_sold:+,.0f} 元")
print("\n费率：513300 0.80%/年  →  513390 0.65%/年   改善 0.15pct/年")
