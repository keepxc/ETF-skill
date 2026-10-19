"""017730 完整净值 + 与NDX/沪深300对比 + 重仓股近期走势"""
import json, re, urllib.request, datetime, statistics, io, csv

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

# 1) 全量净值 —— 移动端 API
navs = {}
for pg in range(1, 12):
    try:
        raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE=017730&pageIndex={pg}&pageSize=100&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        d = json.loads(raw)
        ls = (d.get("Datas") or [])
    except Exception as e:
        print("nav api err", pg, e); break
    print(f"page{pg} -> {len(ls)}")
    for x in ls:
        d0, v = x.get("FSRQ"), x.get("DWJZ")
        if d0 and v:
            try: navs[d0] = float(v)
            except Exception: pass
    if len(ls) < 100:
        break

ds = sorted(navs)
print(f"\n净值合计 {len(ds)} 条  {ds[0] if ds else '?'} ~ {ds[-1] if ds else '?'}")

# 2) 指数数据（stooq）
def stooq(sym):
    raw = get(f"https://stooq.com/q/d/l/?s={sym}&i=d")
    out = {}
    for row in csv.DictReader(io.StringIO(raw)):
        try:
            out[row["Date"]] = float(row["Close"])
        except Exception: pass
    return out

ndx = stooq("^ndx"); spx = stooq("^spx")
print(f"NDX {len(ndx)}  SPX {len(spx)}")

if ds:
    last_d, last_v = ds[-1], navs[ds[-1]]
    print(f"\n最新净值 {last_d} {last_v}")

    def ret(days):
        t = (datetime.date.fromisoformat(last_d) - datetime.timedelta(days=days)).isoformat()
        c = [d for d in ds if d <= t]
        return None if not c else (last_v / navs[c[-1]] - 1) * 100
    print("\n基金各期收益:")
    for lb, d in [("1周",7),("1月",30),("3月",91),("6月",182),("1年",365),("2年",730),("3年",1095),("成立以来",99999)]:
        r = ret(d)
        print(f"  {lb}: {r:+.2f}%" if r is not None else f"  {lb}: n/a")

    # 与指数对比（共同日期）
    for name, idx in [("NDX", ndx), ("SPX", spx)]:
        common = sorted(set(navs) & set(idx))
        if len(common) < 40:
            print(f"\n{name}: 重叠仅 {len(common)} 天"); continue
        print(f"\n=== vs {name} (重叠 {len(common)} 天) ===")
        for win in (30, 60, 120, 250):
            s = common[-(win+1):]
            if len(s) < 20: continue
            f_r = [navs[s[i+1]]/navs[s[i]]-1 for i in range(len(s)-1)]
            i_r = [idx[s[i+1]]/idx[s[i]]-1 for i in range(len(s)-1)]
            mf, mi = statistics.mean(f_r), statistics.mean(i_r)
            cov = sum((a-mf)*(b-mi) for a,b in zip(f_r,i_r))/len(f_r)
            sf, si = statistics.pstdev(f_r), statistics.pstdev(i_r)
            corr = cov/(sf*si) if sf and si else float("nan")
            cf = navs[s[-1]]/navs[s[0]]-1; ci = idx[s[-1]]/idx[s[0]]-1
            # beta
            beta = cov/(si*si) if si else float("nan")
            print(f"  近{len(s)}交易日: 相关 {corr:+.2f}  β {beta:+.2f} | 基金 {cf*100:+.2f}% vs {name} {ci*100:+.2f}% → 超额 {(cf-ci)*100:+.2f}pct")

# 3) 重仓股近期走势
print("\n=== 重仓股近期走势 ===")
holdings = [("MU","美光"),("AMD","超威"),("KLAC","科磊"),("TSM","台积电"),("AVGO","博通"),
            ("QCOM","高通"),("MPWR","MPS"),("NVDA","英伟达"),("SNPS","新思"),
            ("688256.SS","寒武纪"),("688361.SS","中科飞测"),("688498.SS","源杰科技"),
            ("300502.SZ","新易盛"),("002463.SZ","沪电股份"),("688220.SS","翱捷科技")]
for sym, nm in holdings:
    try:
        s = stooq(sym.lower())
        if len(s) < 30: 
            print(f"  {nm} {sym}: 数据少({len(s)})"); continue
        dts = sorted(s)[-30:]
        c0, c1 = s[dts[0]], s[dts[-1]]
        print(f"  {nm:8s} {sym:12s} 近30日 {(c1/c0-1)*100:+7.2f}%   ({dts[0]} → {dts[-1]})")
    except Exception as e:
        print(f"  {nm} {sym}: 失败 {e}")
