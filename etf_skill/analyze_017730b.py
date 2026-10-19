"""017730 全量净值(老API) + 前十大持仓 + 与 NDX/沪深300 对比"""
import json, re, urllib.request, datetime

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "http://fundf10.eastmoney.com/"}
def get(u, enc="utf-8", referer=None):
    h = dict(H)
    if referer: h["Referer"] = referer
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25).read().decode(enc, "replace")

CODE = "017730"

# 老式 lsjz API
navs = {}
for pg in range(1, 12):
    try:
        raw = get(f"http://fund.eastmoney.com/f10/F10DataApi.aspx?type=lsjz&code={CODE}&page={pg}&per=49")
    except Exception as e:
        print("lsjz err", pg, e); break
    rows = re.findall(r"<tr>.*?</tr>", raw, re.S)
    n = 0
    for r in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if len(cells) >= 2:
            d0 = re.sub(r"<[^>]+>", "", cells[0]).strip()
            v0 = re.sub(r"<[^>]+>", "", cells[1]).strip()
            if re.match(r"\d{4}-\d{2}-\d{2}", d0) and re.match(r"^[\d.]+$", v0):
                navs[d0] = float(v0); n += 1
    print(f"page{pg}: +{n}")
    if n == 0:
        break

ds = sorted(navs)
print(f"\n合计 {len(ds)} 条  {ds[0] if ds else '?'} ~ {ds[-1] if ds else '?'}")
if ds:
    last_d, last_v = ds[-1], navs[ds[-1]]
    print(f"最新 {last_d} {last_v}")

    def ret(days):
        t = (datetime.date.fromisoformat(last_d) - datetime.timedelta(days=days)).isoformat()
        c = [d for d in ds if d <= t]
        return None if not c else (last_v / navs[c[-1]] - 1) * 100
    for lb, d in [("1周",7),("1月",30),("3月",91),("6月",182),("1年",365),("2年",730),("成立以来",99999)]:
        r = ret(d)
        print(f"  {lb}: {r:+.2f}%" if r is not None else f"  {lb}: n/a")

    # 年度/季度
    import collections
    q = collections.OrderedDict()
    for d0 in ds:
        y, m = int(d0[:4]), int(d0[5:7])
        q.setdefault(f"{y}Q{(m-1)//3+1}", []).append(navs[d0])
    print("\n季度末:")
    prev = None
    for k, v in q.items():
        ch = f"{(v[-1]/prev-1)*100:+.2f}%" if prev else "—"
        print(f"  {k}  {v[-1]:.4f}  {ch}")
        prev = v[-1]

# 前十大持仓
print("\n=== 前十大持仓 ===")
for yr, mo in [("2026","6"),("2026","3"),("2025","12")]:
    try:
        raw = get(f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={CODE}&topline=10&year={yr}&month={mo}")
        txt = re.sub(r"<[^>]+>", "|", raw)
        txt = re.sub(r"[|\s]+", "|", txt)
        if "股票代码" in txt:
            i = txt.find("股票代码")
            print(f"-- {yr}-{mo} --")
            print(txt[i:i+700])
            print()
    except Exception as e:
        print(f"{yr}-{mo} 失败: {e}")

# 行业配置
print("\n=== 行业配置 ===")
try:
    raw = get(f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=hytz&code={CODE}")
    txt = re.sub(r"<[^>]+>", "|", raw); txt = re.sub(r"[|\s]+", "|", txt)
    i = txt.find("行业类别")
    print(txt[i:i+600] if i > 0 else txt[:400])
except Exception as e:
    print("行业失败:", e)
