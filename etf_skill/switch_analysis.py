"""513390 vs 513330：切换成本 + 持仓加权溢价（腾讯K线 + 东财净值）"""
import json, urllib.request, time, statistics

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8", tries=4):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")
        except Exception as e:
            last = e; time.sleep(1.5)
    raise last

def kline_tx(code, start="2026-09-01"):
    mkt = "sh" if code.startswith("5") else "sz"
    u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,{start},2026-12-31,80,"
    d = json.loads(get(u))["data"][mkt + code]
    rows = d.get("day") or d.get("qfqday") or []
    return {r[0]: float(r[2]) for r in rows}

def navs(code):
    out = {}
    for pg in range(1, 3):
        raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE={code}&pageIndex={pg}&pageSize=100&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        ls = json.loads(raw).get("Datas") or []
        for x in ls:
            if x.get("FSRQ") and x.get("DWJZ"):
                try: out[x["FSRQ"]] = float(x["DWJZ"])
                except (TypeError, ValueError): pass
        if len(ls) < 100: break
    return out

for code, nm in [("513390","纳指100ETF博时"), ("513330","恒生互联网ETF华夏")]:
    try:
        px, nv = kline_tx(code), navs(code)
    except Exception as e:
        print(f"{code} 抓取失败: {e}"); continue
    ds = sorted(px)
    print(f"########## {code} {nm} ##########")
    print(f"  价格 {len(ds)} 天  净值 {len(nv)} 天")
    print(f"  {'日期':<12}{'收盘':>8}{'净值':>10}{'净值日':>12}{'溢率':>9}")
    out = []
    for d0 in ds:
        prev = [x for x in sorted(nv) if x < d0]
        if not prev: continue
        nd = prev[-1]
        pr = (px[d0]/nv[nd] - 1)*100
        out.append((d0, px[d0], pr))
        print(f"  {d0:<12}{px[d0]:>8.3f}{nv[nd]:>10.4f}{nd:>12}{pr:>8.2f}%")
    sep = [r[2] for r in out if r[0] < "2026-10-01"]
    oc  = [r[2] for r in out if r[0] >= "2026-10-01"]
    if sep:
        print(f"  → 九月：中位 {statistics.median(sep):+.2f}%  均值 {statistics.mean(sep):+.2f}%  区间 {min(sep):+.2f}% ~ {max(sep):+.2f}%")
    if oc:
        print(f"  → 十月：中位 {statistics.median(oc):+.2f}%  均值 {statistics.mean(oc):+.2f}%  区间 {min(oc):+.2f}% ~ {max(oc):+.2f}%")
    print()
