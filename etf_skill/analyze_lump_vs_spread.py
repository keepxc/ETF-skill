"""盈亏平衡：场内一次买入(付10%溢价) vs 场外5个月分批(0溢价) + NDX 滚动5月涨幅分布"""
import json, urllib.request

h = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=30).read().decode("utf-8", "replace")

print("=== NDX 滚动 5 个月(105交易日) 涨幅分布 ===")
try:
    d = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?interval=1d&range=30y"))
    r0 = d["chart"]["result"][0]
    vals = [c for c in r0["indicators"]["quote"][0]["close"] if c]
    rets = sorted(vals[i + 105] / vals[i] - 1 for i in range(len(vals) - 105))
    n = len(rets)
    def q(p): return rets[min(int(p * n), n - 1)]
    print(f"  样本 {n} 天")
    print(f"  P10 {q(.10)*100:+.1f}%  P25 {q(.25)*100:+.1f}%  中位 {q(.50)*100:+.1f}%  P75 {q(.75)*100:+.1f}%  P90 {q(.90)*100:+.1f}%")
    print(f"  最低 {rets[0]*100:+.1f}%   最高 {rets[-1]*100:+.1f}%")
    for th in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]:
        frac = sum(1 for x in rets if x >= th) / n
        print(f"  5个月内涨超 {th*100:>3.0f}% 的概率: {frac*100:5.1f}%")
except Exception as e:
    print("  NDX 失败:", e)

print("\n=== 盈亏平衡 ===")
CAP, PREM = 10000, 0.10
print(f"  前提: 10,000 元")
print(f"    A 场内 513390 一次买入 → 付 {PREM*100:.0f}% 溢价 = 白付 {CAP*PREM:,.0f} 元")
print(f"    B 场外 015299 分 5 期 → 0 溢价，每月 2,000")
print()
print(f"  {'5个月涨幅':<10}{'A 场内一次':<13}{'B 场外分批':<13}{'胜者':<7}{'差额'}")
for r in [-0.30, -0.20, -0.10, 0, 0.05, 0.10, 0.20, 0.30, 0.35, 0.40, 0.50, 0.70, 1.00]:
    m = (1 + r) ** 0.2 - 1 if r > -1 else 0
    a = CAP * (1 - PREM) * (1 + r)
    b = sum(2000 * (1 + m) ** (5 - i) for i in range(5))
    print(f"  {r*100:+6.0f}%     {a:>10,.0f}   {b:>10,.0f}   {'场内' if a > b else '场外':<7}{abs(a-b):>8,.0f}")

# 平衡点
lo, hi = 0.0, 2.0
for _ in range(60):
    mid = (lo + hi) / 2
    m = (1 + mid) ** 0.2 - 1
    a = CAP * (1 - PREM) * (1 + mid)
    b = sum(2000 * (1 + m) ** (5 - i) for i in range(5))
    if a > b:
        hi = mid
    else:
        lo = mid
print(f"\n  盈亏平衡点: 5个月涨幅 ≈ +{(lo+hi)/2*100:.0f}%  (年化 ≈ {((1+(lo+hi)/2)**2.4-1)*100:.0f}%)")
print(f"  即：NDX 需在 5 个月内涨过这个数，场内一次买入才划算")
