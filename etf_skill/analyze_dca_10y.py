"""10年定投视角：溢率成本 vs 场外费率"""
import csv, statistics, json, re, urllib.request, urllib.parse
from collections import defaultdict

CSV = "/home/gyan/scripts/etf_skill/history_premium.csv"
rows = []
with open(CSV) as f:
    for r in csv.DictReader(f):
        try:
            rows.append((r["date"], float(r["close"]), float(r["nav"]), float(r["premium_pct"])))
        except ValueError:
            continue
rows.sort()
print(f"数据范围 {rows[0][0]} ~ {rows[-1][0]}  ({len(rows)} 天)\n")

bym = defaultdict(list)
for d, c, n, p in rows:
    bym[d[:7]].append(p)

print("=== 月度溢率中位数（近 24 个月）===")
for m in sorted(bym)[-24:]:
    v = bym[m]
    print(f"  {m}  中位 {statistics.median(v):+6.2f}%   均值 {statistics.mean(v):+6.2f}%   n={len(v)}")

print("\n=== 半年度趋势 ===")
hy = defaultdict(list)
for m in sorted(bym):
    y, mo = m.split("-")
    hy[f"{y}H{1 if int(mo) <= 6 else 2}"].extend(bym[m])
for k in sorted(hy):
    v = hy[k]
    print(f"  {k}  中位 {statistics.median(v):+6.2f}%   n={len(v)}")

monthly_med = [statistics.median(bym[m]) for m in sorted(bym)]
print("\n=== 每月定投 1 次，历史平均付出溢率 ===")
print(f"  全历史:   {statistics.mean(monthly_med):+.2f}%")
for win in [12, 24, 36]:
    print(f"  近{win}个月: {statistics.mean(monthly_med[-win:]):+.2f}%")

print("\n=== 10 年定投模拟（500 元/月，年化 8%）===")
MONTHLY, YEARS, R = 500, 10, 0.08
months = YEARS * 12
def fv(monthly, months, r_annual):
    r_m = (1 + r_annual) ** (1 / 12) - 1
    return sum(monthly * (1 + r_m) ** (months - i) for i in range(1, months + 1))
base = fv(MONTHLY, months, R)
contrib = MONTHLY * months
print(f"  总投入: {contrib:,} 元")
print(f"  零溢价终值: {base:,.0f} 元   (盈利 {base-contrib:,.0f})")
for prem in [0.01, 0.02, 0.03, 0.04, 0.05]:
    v = fv(MONTHLY * (1 - prem), months, R)
    print(f"  平均溢率 {prem*100:.0f}%: 终值 {v:,.0f} 元   比零溢价少 {base-v:,.0f} 元 ({(base-v)/base*100:.2f}%)")

print("\n=== 场外联接基金费率 ===")
h = {"User-Agent": "Mozilla/5.0"}
for code in ["015299", "015300"]:
    try:
        txt = urllib.request.urlopen(urllib.request.Request(
            f"https://fund.eastmoney.com/pingzhongdata/{code}.js", headers=h), timeout=15).read().decode("utf-8", "replace")
        nm = re.search(r'fS_name = "([^"]*)"', txt)
        src = re.search(r'fund_sourceRate="([^"]*)"', txt)
        rate = re.search(r'fund_Rate="([^"]*)"', txt)
        print(f"  {code}  {nm.group(1) if nm else '?'}  申购费 原{src.group(1) if src else '-'}% → 现{rate.group(1) if rate else '-'}%")
    except Exception as e:
        print(f"  {code} 失败: {e}")

print("\n=== 搜索 华夏纳斯达克100 系列基金 ===")
try:
    u = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=" + urllib.parse.quote("华夏纳斯达克100")
    d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=15).read().decode("utf-8"))
    for item in (d.get("Datas") or [])[:12]:
        print(f"  {item.get('CODE')}  {item.get('NAME')}")
except Exception as e:
    print(f"  搜索失败: {e}")
