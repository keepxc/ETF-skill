"""全市场扫描：纳指100相关场外基金的申购状态"""
import json, re, urllib.request, urllib.parse

h = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20).read().decode("utf-8", "replace")

seen = {}
for kw in ["纳斯达克100", "纳指100"]:
    try:
        u = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=" + urllib.parse.quote(kw)
        d = json.loads(get(u))
        for item in (d.get("Datas") or []):
            c, n = item.get("CODE"), (item.get("NAME") or "")
            if c and c not in seen:
                seen[c] = n
    except Exception as e:
        print(f"搜索 {kw} 失败: {e}")

print(f"共 {len(seen)} 只候选\n")
rows = []
for code, name in seen.items():
    try:
        t = re.sub(r"<[^>]+>", " ", get(f"https://fund.eastmoney.com/{code}.html"))
        t = re.sub(r"\s+", " ", t)
        i = t.find("交易状态")
        seg = t[i + 5:i + 80].strip() if i > 0 else ""
        m = re.search(r"上限([\d.]+)元", seg)
        limit = float(m.group(1)) if m else None
        if "暂停申购" in seg:
            status = "暂停"
        elif "限大额" in seg:
            status = "限大额"
        elif "开放申购" in seg:
            status = "开放"
        else:
            status = "?"
        rows.append((status, limit, code, name))
    except Exception as e:
        rows.append(("ERR", None, code, name))

order = {"开放": 0, "限大额": 1, "暂停": 2, "?": 3, "ERR": 4}
rows.sort(key=lambda r: (order.get(r[0], 9), -(r[1] or 0)))
for status, limit, code, name in rows:
    lim = f"上限 {limit:g} 元/日" if limit else "—"
    print(f"  {status:<6} {code}  {name[:36]:<38} {lim}")
