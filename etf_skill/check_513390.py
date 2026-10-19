"""查 513390（博时纳指100ETF）的场外联接 + 真实溢价"""
import json, urllib.request, urllib.parse

h = {"User-Agent": "Mozilla/5.0"}
def get(u, hd=None, enc="utf-8"):
    hh = dict(h)
    if hd:
        hh.update(hd)
    return urllib.request.urlopen(urllib.request.Request(u, headers=hh), timeout=20).read().decode(enc, "replace")

print("=== 搜索 博时纳斯达克100 / 纳指100ETF联接 ===")
for kw in ["博时纳斯达克100", "纳斯达克100ETF联接"]:
    print(f"--- {kw} ---")
    try:
        u = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=" + urllib.parse.quote(kw)
        d = json.loads(get(u))
        for item in (d.get("Datas") or [])[:15]:
            print(f"  {item.get('CODE')}  {item.get('NAME')}")
    except Exception as e:
        print("  失败:", e)

print("\n=== 513390 实时 ===")
raw = get("https://qt.gtimg.cn/q=sh513390", {"Referer": "https://gu.qq.com/"}, enc="gbk")
f = raw.split("~")
if len(f) > 30:
    print(f"  名称 {f[1]}  现价 {f[3]}  昨收 {f[4]}  时间 {f[30]}")

print("\n=== 513390 净值 ===")
d = json.loads(get("https://api.fund.eastmoney.com/f10/lsjz?fundCode=513390&pageIndex=1&pageSize=12",
                   {"Referer": "https://fund.eastmoney.com/513390.html"}))
lst = (d.get("Data") or {}).get("LSJZList", [])
for it in lst:
    print(f"  {it['FSRQ']}  {it['DWJZ']}  {it.get('JZZZL', '')}%")

print("\n=== 513300 对照 ===")
raw = get("https://qt.gtimg.cn/q=sh513300", {"Referer": "https://gu.qq.com/"}, enc="gbk")
f = raw.split("~")
print(f"  现价 {f[3]}  昨收 {f[4]}")
d = json.loads(get("https://api.fund.eastmoney.com/f10/lsjz?fundCode=513300&pageIndex=1&pageSize=5",
                   {"Referer": "https://fund.eastmoney.com/513300.html"}))
for it in (d.get("Data") or {}).get("LSJZList", [])[:5]:
    print(f"  {it['FSRQ']}  {it['DWJZ']}")
