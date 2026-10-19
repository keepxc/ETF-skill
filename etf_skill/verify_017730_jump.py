"""017730 核实 2026Q2 净值跳变 + 份额/规模变化"""
import json, urllib.request, datetime

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode("utf-8", "replace")

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
# 找单日异常（>8% 涨幅）
print("=== 单日涨跌 > 6% 的日期 ===")
for i in range(1, len(ds)):
    ch = navs[ds[i]]/navs[ds[i-1]] - 1
    if abs(ch) > 0.06:
        print(f"  {ds[i]}  {ch*100:+.2f}%   ({navs[ds[i-1]]:.4f} → {navs[ds[i]]:.4f})")

print("\n=== 2026-05-15 ~ 2026-07-15 逐日 ===")
for d0 in ds:
    if "2026-05-15" <= d0 <= "2026-07-15":
        i = ds.index(d0)
        prev = f"{(navs[d0]/navs[ds[i-1]]-1)*100:+.2f}%" if i else "—"
        print(f"  {d0}  {navs[d0]:.4f}  {prev}")

print("\n=== 2026-06 前后月度 ===")
import collections
m = collections.OrderedDict()
for d0 in ds:
    m.setdefault(d0[:7], []).append((d0, navs[d0]))
for k, v in m.items():
    if k >= "2026-01":
        print(f"  {k}  首 {v[0][1]:.4f}  末 {v[-1][1]:.4f}  变化 {(v[-1][1]/v[0][1]-1)*100:+.2f}%")
