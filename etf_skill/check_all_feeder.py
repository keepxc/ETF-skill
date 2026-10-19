"""查所有纳指100场外联接的申购状态"""
import re, urllib.request

h = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20).read().decode("utf-8", "replace")

codes = {
    "016055": "博时纳斯达克100联接A", "016057": "博时纳斯达克100联接C",
    "015299": "华夏纳斯达克100联接A", "015300": "华夏纳斯达克100联接C",
    "000834": "大成纳斯达克100联接A", "008971": "大成纳斯达克100联接C",
    "040046": "华安纳斯达克100联接A", "014978": "华安纳斯达克100联接C",
    "270042": "广发纳斯达克100联接A", "006479": "广发纳斯达克100联接C",
}
for code, name in codes.items():
    try:
        t = re.sub(r"<[^>]+>", " ", get(f"https://fund.eastmoney.com/{code}.html"))
        t = re.sub(r"\s+", " ", t)
        i = t.find("交易状态")
        seg = t[i:i + 110].strip() if i > 0 else "(未找到交易状态)"
        print(f"{code}  {name}")
        print(f"    {seg}\n")
    except Exception as e:
        print(f"{code}  {name}  失败: {e}\n")
