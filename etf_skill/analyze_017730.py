"""017730 深度：全量净值 + 持仓 + 档案 + 与指数对比"""
import json, re, urllib.request, datetime

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8", referer=None):
    h = dict(H)
    if referer: h["Referer"] = referer
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25).read().decode(enc, "replace")

CODE = "017730"

# 全量净值：多页
navs = {}
for pg in range(1, 15):
    try:
        raw = get(f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={CODE}&pageIndex={pg}&pageSize=50")
        d = json.loads(raw)
        ls = (d.get("Data") or {}).get("LSJZList") or []
    except Exception as e:
        print(f"page{pg} err {e}"); break
    print(f"page{pg} -> {len(ls)} 条")
    if not ls: break
    for x in ls:
        if x.get("DWJZ"):
            navs[x["FSRQ"]] = float(x["DWJZ"])
    if len(ls) < 50: break

ds = sorted(navs)
print(f"\n合计 {len(ds)} 条  范围 {ds[0]} ~ {ds[-1]}")
last_d, last_v = ds[-1], navs[ds[-1]]
print(f"最新 {last_d}  净值 {last_v}")

def ret(days):
    t = (datetime.date.fromisoformat(last_d) - datetime.timedelta(days=days)).isoformat()
    c = [d for d in ds if d <= t]
    return None if not c else (last_v / navs[c[-1]] - 1) * 100

for lb, d in [("1周",7),("1月",30),("3月",91),("6月",182),("1年",365),("成立以来",99999)]:
    r = ret(d)
    print(f"  {lb}: {r:+.2f}%" if r is not None else f"  {lb}: n/a")

# 高点回撤
peak_d = max(ds, key=lambda d: navs[d])
print(f"\n区间最高 {peak_d} {navs[peak_d]}  →  当前 {last_v}  回撤 {(last_v/navs[peak_d]-1)*100:+.2f}%")

# 逐月
import collections
bym = collections.OrderedDict()
for d in ds:
    bym.setdefault(d[:7], []).append(navs[d])
print("\n月末净值:")
prev = None
for m, v in bym.items():
    ch = f"{(v[-1]/prev-1)*100:+.2f}%" if prev else "—"
    print(f"  {m}  末值 {v[-1]:.4f}  月内变化 {ch}  (区间 {min(v):.4f}~{max(v):.4f})")
    prev = v[-1]

# 持仓
print("\n=== 持仓 (前十大) ===")
try:
    t = re.sub(r"<[^>]+>", "|", get(f"http://fundf10.eastmoney.com/ccmx_{CODE}.html"))
    t = re.sub(r"[|\s]+", "|", t)
    i = t.find("股票代码")
    print(t[i:i+900] if i > 0 else "未找到持仓表")
except Exception as e:
    print("持仓失败:", e)

# 基金档案
print("\n=== 档案 ===")
for u in [f"http://fundf10.eastmoney.com/jbgk_{CODE}.html", f"https://fund.eastmoney.com/{CODE}.html"]:
    try:
        t = re.sub(r"<[^>]+>", " ", get(u))
        t = re.sub(r"\s+", " ", t)
        for kw in ["基金全称", "基金简称", "基金类型", "成立日期", "资产规模", "基金管理人", "基金经理", "业绩比较基准", "跟踪标的"]:
            j = t.find(kw)
            if j > 0:
                print(f"  [{kw}] {t[j:j+90].strip()}")
    except Exception as e:
        print("  档案失败:", e)
