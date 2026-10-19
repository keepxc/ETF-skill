"""分析：历史上在高溢率时买入，后续收益如何"""
import csv, statistics

PATH = "/home/gyan/scripts/etf_skill/history_premium.csv"
rows = []
with open(PATH) as f:
    for r in csv.DictReader(f):
        try:
            rows.append((r["date"], float(r["close"]), float(r["nav"]), float(r["premium_pct"])))
        except ValueError:
            continue
rows.sort()
print(f"数据范围: {rows[0][0]} ~ {rows[-1][0]}  ({len(rows)} 个交易日)")

prems = sorted(r[3] for r in rows)
n = len(prems)
def q(p): return prems[min(int(p * n), n - 1)]
print(f"溢率分布: 中位 {q(0.5):+.2f}% | P90 {q(0.9):+.2f}% | P95 {q(0.95):+.2f}% | P99 {q(0.99):+.2f}% | 最高 {prems[-1]:+.2f}%")
print()

for thresh in [8.0, 10.0]:
    hits = [i for i, r in enumerate(rows) if r[3] >= thresh]
    print(f"=== 溢率 >= {thresh}% 的买入日 (n={len(hits)}) ===")
    if not hits:
        print()
        continue
    print(f"  日期: {', '.join(rows[i][0] for i in hits[:12])}{' ...' if len(hits) > 12 else ''}")
    for horizon in [20, 60, 120]:
        nav_rets, price_rets, prem_after = [], [], []
        for i in hits:
            j = i + horizon
            if j < len(rows):
                nav_rets.append(rows[j][2] / rows[i][2] - 1)
                price_rets.append(rows[j][1] / rows[i][1] - 1)
                prem_after.append(rows[j][3])
        if nav_rets:
            print(f"  {horizon:>3}交易日后: 净值 中位{statistics.median(nav_rets)*100:+.1f}% 均值{statistics.mean(nav_rets)*100:+.1f}%"
                  f" | 价格(场内持有) 中位{statistics.median(price_rets)*100:+.1f}%"
                  f" | 溢率回落至 {statistics.median(prem_after):+.1f}% (n={len(nav_rets)})")
    print()

print("=== 高溢率后的回归速度 (阈 8%) ===")
hits = [i for i, r in enumerate(rows) if r[3] >= 8.0]
for horizon in [5, 10, 20, 40]:
    after = [rows[i + horizon][3] for i in hits if i + horizon < len(rows)]
    if after:
        print(f"  {horizon:>3}交易日后: 溢率中位 {statistics.median(after):+.2f}%  (样本 {len(after)})")
