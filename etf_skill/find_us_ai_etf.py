"""关键词穷举 v2：修正代码正则 + 补关键词"""
import json, re, urllib.request, urllib.parse

H = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode("utf-8", "replace")

KWS = ["纳斯达克", "纳指", "标普500", "标普", "道琼斯", "海外科技", "全球科技",
       "纳斯达克科技", "纳斯达克生物", "信息科技", "人工智能", "美国", "美股",
       "中概互联", "恒生科技", "恒生互联网", "全球芯片", "半导体", "芯片",
       "云计算", "科技龙头", "数字经济", "中韩半导体", "亚太", "海外", "港美",
       "全球产业", "纳斯达克100", "科创", "软件", "通信", "消费电子"]

CODE_RE = re.compile(r"^(5[0-9]\d{4}|1[5-9]\d{4})$")
found = {}
for kw in KWS:
    try:
        u = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key=" + urllib.parse.quote(kw)
        d = json.loads(get(u))
        for it in (d.get("Datas") or []):
            c, n = it.get("CODE"), str(it.get("NAME") or "")
            if c and CODE_RE.match(c):
                found.setdefault(c, n)
    except Exception as e:
        print(f"{kw} 失败: {e}")

print(f"场内候选合计: {len(found)}\n")

def cat(n):
    if "纳斯达克科技" in n or "纳指科技" in n: return "A. 纳指科技(更纯AI)"
    if "纳斯达克生物" in n or "纳指生物" in n: return "B. 纳指生物科技"
    if "纳斯达克" in n or "纳指" in n: return "C. 纳指100"
    if "标普" in n:
        return "D. 标普信息科技" if ("信息科技" in n) else ("标普油气" if "油气" in n else "E. 标普500")
    if "道琼斯" in n: return "F. 道指"
    if "美国50" in n or "美国" in n: return "G. 美国宽基"
    if "中概" in n: return "H. 中概互联(中国)"
    if "恒生" in n: return "I. 恒生科技/互联网(中国)"
    if "中韩半导体" in n: return "J. 中韩半导体"
    if "半导体" in n or "芯片" in n: return "K. 半导体/芯片(A股为主)"
    if "人工智能" in n or "云计算" in n or "数字经济" in n: return "L. 国内AI(A股)"
    if "海外科技" in n or "全球科技" in n: return "M. 海外/全球科技(主动)"
    return "Z. 其他"

groups = {}
for c, n in found.items():
    groups.setdefault(cat(n), []).append((c, n))

for g in sorted(groups):
    print(f"== {g} ({len(groups[g])}) ==")
    for c, n in sorted(groups[g]):
        print(f"   {c}  {n}")
    print()
