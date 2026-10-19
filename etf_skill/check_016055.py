"""016055 费率 + 假日期间 NDX 变动 → 真实溢价"""
import json, re, urllib.request, datetime

h = {"User-Agent": "Mozilla/5.0"}
def get(u, hd=None, enc="utf-8"):
    hh = dict(h)
    if hd:
        hh.update(hd)
    return urllib.request.urlopen(urllib.request.Request(u, headers=hh), timeout=20).read().decode(enc, "replace")

print("=== 博时联接费率 ===")
for code in ["016055", "016057"]:
    try:
        txt = get(f"https://fundf10.eastmoney.com/jjfl_{code}.html")
        t = re.sub(r"<[^>]+>", " ", txt)
        t = re.sub(r"\s+", " ", t)
        js = get(f"https://fund.eastmoney.com/pingzhongdata/{code}.js")
        nm = re.search(r'fS_name = "([^"]*)"', js)
        print(f"--- {code}  {nm.group(1) if nm else '?'} ---")
        for kw in ["管理费率", "托管费率", "销售服务费率", "申购费率"]:
            i = t.find(kw)
            if i > 0:
                print("  ", t[i:i + 75].strip())
    except Exception as e:
        print(code, "failed:", e)

print("\n=== NDX 假日期间变动（09-25 起）===")
try:
    d = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?interval=1d&range=1mo"))
    r0 = d["chart"]["result"][0]
    for t, c in zip(r0["timestamp"], r0["indicators"]["quote"][0]["close"]):
        if c:
            dd = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%m-%d")
            if dd >= "09-25":
                print(f"  {dd}  {c:,.2f}")
except Exception as e:
    print("  NDX 失败:", e)
