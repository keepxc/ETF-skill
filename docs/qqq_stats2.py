import json, statistics as st, datetime

d = json.load(open("/tmp/qqq_d.json"))
r = d["chart"]["result"][0]
rows = [(datetime.date.fromtimestamp(t), c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]
closes = [c for _, c in rows]
dev = [None] * len(closes)
for i in range(199, len(closes)):
    ma = sum(closes[i - 199:i + 1]) / 200
    dev[i] = (closes[i] - ma) / ma * 100


def fwd(i, n):
    return (closes[i + n] / closes[i] - 1) * 100 if i + n < len(closes) else None


def agg(idx, n):
    v = [fwd(i, n) for i in idx if fwd(i, n) is not None]
    if not v:
        return None
    return st.mean(v), st.median(v), sum(1 for x in v if x > 0) / len(v) * 100, len(v)


def line(lab, idx, n):
    a = agg(idx, n)
    if not a:
        return f"{lab}: n/a"
    return f"{lab}: 均值 {a[0]:+6.1f}%  中位 {a[1]:+6.1f}%  胜率 {a[2]:3.0f}%  (n={a[3]})"


valid = [i for i, v in enumerate(dev) if v is not None]

print("== 基准线（所有交易日，无条件持有）==")
for n, lab in [(63, "3个月"), (126, "6个月"), (252, "12个月")]:
    print("  " + line(lab, valid, n))

print("\n== 相对基准（12 个月，档位均值 - 基准均值）==")
base12 = agg(valid, 252)[0]
for name, lo, hi in [(">20%", 20, 1e9), ("12-20%", 12, 20), ("0-12%", 0, 12), ("<=0%", -1e9, 0)]:
    idx = [i for i in valid if lo < dev[i] <= hi]
    a = agg(idx, 252)
    if a:
        print(f"  {name:<8} {a[0]:+6.1f}%  (差 {a[0]-base12:+5.1f}pct, 胜率 {a[2]:3.0f}%)")

print("\n== 事件化（同簇去重：相邻事件间隔 <63 交易日合并）==")
for name, test in [("上穿 20%", lambda a, b: a <= 20 < b), ("跌破 MA200", lambda a, b: a > 0 >= b)]:
    ev = [i for i in range(1, len(dev)) if dev[i] is not None and dev[i - 1] is not None and test(dev[i - 1], dev[i])]
    dedup, last = [], -10**9
    for i in ev:
        if i - last >= 63:
            dedup.append(i)
            last = i
    print(f"  [{name}] 原始 {len(ev)} 次 → 去簇后 {len(dedup)} 次")
    for n, lab in [(63, "3个月"), (126, "6个月"), (252, "12个月")]:
        print("    " + line(lab, dedup, n))
    print("    时点:", ", ".join(str(rows[i][0]) for i in dedup))

print("\n== 分时段稳定性（各档位 12 个月均值）==")
for lo_y, hi_y, tag in [(1999, 2009, "1999-2009"), (2010, 2019, "2010-2019"), (2020, 2026, "2020-2026")]:
    seg = [i for i in valid if lo_y <= rows[i][0].year <= hi_y]
    print(f"  {tag}: 基准 {agg(seg,252)[0]:+6.1f}%", end="")
    for name, lo, hi in [(">20%", 20, 1e9), ("12-20%", 12, 20), ("0-12%", 0, 12), ("<=0%", -1e9, 0)]:
        idx = [i for i in seg if lo < dev[i] <= hi]
        a = agg(idx, 252)
        print(f" | {name} {a[0]:+6.1f}%(n={a[3]})" if a else f" | {name} n/a", end="")
    print()
