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


buckets = {"RED >20%": [], "YEL 12-20%": [], "GRN 0-12%": [], "BLU <=0%": []}
for i, v in enumerate(dev):
    if v is None:
        continue
    k = "RED >20%" if v > 20 else "YEL 12-20%" if v > 12 else "GRN 0-12%" if v > 0 else "BLU <=0%"
    buckets[k].append(i)


def stats(idx, n):
    vals = [fwd(i, n) for i in idx if fwd(i, n) is not None]
    if not vals:
        return "   n/a"
    win = sum(1 for v in vals if v > 0) / len(vals) * 100
    return f"{st.mean(vals):+7.1f}% /{st.median(vals):+7.1f}% /{win:4.0f}%"


tot = sum(len(v) for v in buckets.values())
print(f"样本 {tot} 交易日  {rows[200][0]} -> {rows[-1][0]}")
print(f"{'档位':<12}{'天数':>6}{'占比':>6} |   3个月 均值/中位/胜率   |   6个月  |   12个月")
for k, idx in buckets.items():
    print(f"{k:<12}{len(idx):>6}{len(idx) / tot * 100:>5.0f}% | {stats(idx, 63)} | {stats(idx, 126)} | {stats(idx, 252)}")


def events(name, test):
    ev = [i for i in range(1, len(dev)) if dev[i] is not None and dev[i - 1] is not None and test(dev[i - 1], dev[i])]
    print(f"\n[{name}] 共 {len(ev)} 次")
    for n, lab in [(63, "3个月"), (126, "6个月"), (252, "12个月")]:
        v = [fwd(i, n) for i in ev if fwd(i, n) is not None]
        if v:
            win = sum(1 for x in v if x > 0) / len(v) * 100
            print(f"  {lab}: 均值 {st.mean(v):+6.1f}%  中位 {st.median(v):+6.1f}%  胜率 {win:3.0f}%  (n={len(v)})")
    print("  时点:", ", ".join(str(rows[i][0]) for i in ev))


events("乖离从 <=20% 上穿到 >20%", lambda a, b: a <= 20 < b)
events("乖离从 <=12% 上穿到 >12%", lambda a, b: a <= 12 < b)
events("跌破 MA200（>0 -> <=0）", lambda a, b: a > 0 >= b)
