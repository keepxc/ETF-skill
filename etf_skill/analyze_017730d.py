"""017730 vs NDX/沪深300 对比 + 重仓股走势（东财接口）"""
import json, re, urllib.request, datetime, statistics

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://quote.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

def kline(secid, beg="20230101"):
    u = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
         f"&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=1&beg={beg}&end=20500101")
    d = json.loads(get(u))
    k = ((d.get("data") or {}).get("klines") or [])
    out = {}
    for row in k:
        p = row.split(",")
        out[p[0]] = float(p[1])
    return out

# 1) 净值
navs = {}
for pg in range(1, 12):
    raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE=017730&pageIndex={pg}&pageSize=100&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
    ls = (json.loads(raw).get("Datas") or [])
    for x in ls:
        if x.get("FSRQ") and x.get("DWJZ"):
            try: navs[x["FSRQ"]] = float(x["DWJZ"])
            except Exception: pass
    if len(ls) < 100: break
ds = sorted(navs)
last_d, last_v = ds[-1], navs[ds[-1]]

# 2) 指数
idx = {}
for secid, nm in [("100.NDX","NDX 纳指100"), ("100.SPX","SPX 标普500"),
                  ("1.000300","沪深300"), ("100.HSI","恒生")]:
    try:
        idx[nm] = kline(secid)
        print(f"{nm}: {len(idx[nm])} 条")
    except Exception as e:
        print(f"{nm} 失败: {e}")

print(f"\n基金: {len(ds)} 条, 最新 {last_d} {last_v}")
print(f"\n{'对比':<16}{'窗口':<10}{'相关性':<9}{'β':<8}{'基金':<11}{'指数':<11}{'超额'}")
for nm, series in idx.items():
    common = sorted(set(navs) & set(series))
    if len(common) < 40:
        print(f"{nm}: 重叠 {len(common)} 天，跳过"); continue
    for win in (30, 60, 120, 250):
        s = common[-(win+1):]
        if len(s) < 20: continue
        fr = [navs[s[i+1]]/navs[s[i]]-1 for i in range(len(s)-1)]
        ir = [series[s[i+1]]/series[s[i]]-1 for i in range(len(s)-1)]
        mf, mi = statistics.mean(fr), statistics.mean(ir)
        cov = sum((a-mf)*(b-mi) for a,b in zip(fr,ir))/len(fr)
        sf, si = statistics.pstdev(fr), statistics.pstdev(ir)
        corr = cov/(sf*si) if sf and si else float("nan")
        beta = cov/(si*si) if si else float("nan")
        cf = navs[s[-1]]/navs[s[0]]-1; ci = series[s[-1]]/series[s[0]]-1
        print(f"{nm:<16}{len(s):<10}{corr:<9.2f}{beta:<8.2f}{cf*100:<11.2f}{ci*100:<11.2f}{(cf-ci)*100:+.2f}pct")

# 3) 重仓股
print("\n=== 重仓股走势 ===")
hs = [("105.MU","美光"),("105.AMD","超威"),("105.KLAC","科磊"),("106.TSM","台积电"),
      ("105.AVGO","博通"),("105.QCOM","高通"),("105.MPWR","MPS"),("105.NVDA","英伟达"),
      ("105.SNPS","新思"),("1.688256","寒武纪"),("1.688361","中科飞测"),("1.688498","源杰科技"),
      ("0.300502","新易盛"),("0.002463","沪电股份"),("1.688220","翱捷科技"),("116.01347","华虹宏力")]
rows = []
for secid, nm in hs:
    try:
        s = kline(secid)
        dts = sorted(s)
        if len(dts) < 30: 
            print(f"  {nm}: 数据少 {len(dts)}"); continue
        def chg(n):
            if len(dts) < n+1: return None
            return (s[dts[-1]]/s[dts[-1-n]]-1)*100
        rows.append((nm, chg(5), chg(10), chg(21), chg(63)))
    except Exception as e:
        print(f"  {nm} 失败 {e}")
print(f"\n  {'名称':<10}{'近5日':>9}{'近10日':>9}{'近1月':>9}{'近3月':>9}")
for nm, a, b, c, d in rows:
    f = lambda x: f"{x:+8.2f}%" if x is not None else "     n/a"
    print(f"  {nm:<10}{f(a)}{f(b)}{f(c)}{f(d)}")

# 4) 基金分季度
import collections
q = collections.OrderedDict()
for d0 in ds:
    y, m = int(d0[:4]), int(d0[5:7])
    q.setdefault(f"{y}Q{(m-1)//3+1}", []).append(navs[d0])
print("\n季度表现:")
prev = None
for k, v in q.items():
    ch = f"{(v[-1]/prev-1)*100:+.2f}%" if prev else "—"
    print(f"  {k}  末值 {v[-1]:.4f}  {ch}")
    prev = v[-1]
