"""判断溢价在压缩还是扩张：纳指 vs 513390 今日"""
import json, urllib.request

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

def kline(secid, lmt=8):
    u = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
         f"&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=0&end=20500101&lmt={lmt}")
    d = json.loads(get(u))
    out = []
    for k in ((d.get("data") or {}).get("klines") or []):
        p = k.split(",")
        out.append((p[0], float(p[1])))
    return out

print("=== 纳指100 指数（最近6个交易日）===")
ndx = kline("100.NDX")
for i, (d0, v) in enumerate(ndx[-6:]):
    prev = ndx[-6:][i-1][1] if i else None
    ch = f"{(v/prev-1)*100:+.2f}%" if prev else "—"
    print(f"  {d0}  {v:,.2f}  {ch}")

print("\n=== 513390 最近6个交易日 ===")
etf = kline("1.513390")
for i, (d0, v) in enumerate(etf[-6:]):
    prev = etf[-6:][i-1][1] if i else None
    ch = f"{(v/prev-1)*100:+.2f}%" if prev else "—"
    print(f"  {d0}  {v:.3f}  {ch}")

# 用 10-15 净值做基准（最新已公布）
NAV = 2.2511   # 2026-10-15
print(f"\n=== 以 10-15 净值 {NAV} 为基准的溢率 ===")
for d0, v in etf[-4:]:
    print(f"  {d0}  价 {v:.3f}  →  表观溢率 {(v/NAV-1)*100:+.2f}%")
