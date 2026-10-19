"""一次性核实全部纳指100场外通道的最新申购公告 + 页面状态"""
import json, re, urllib.request

h = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20).read().decode("utf-8", "replace")

codes = {
    "015299": "华夏联接A", "015300": "华夏联接C",
    "018043": "天弘指数A", "018044": "天弘指数C",
    "160213": "国泰纳斯达克100",
    "016452": "南方指数A", "000834": "大成联接A",
    "040046": "华安联接A", "270042": "广发联接A",
    "016055": "博时联接A",
}
for code, name in codes.items():
    try:
        d = json.loads(get(f"https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=30&type=0"))
        lst = d.get("Data") or []
        rel = [it for it in lst if any(k in it.get("TITLE", "") for k in ["申购", "大额", "限额", "恢复"])]
        t = re.sub(r"<[^>]+>", " ", get(f"https://fund.eastmoney.com/{code}.html"))
        t = re.sub(r"\s+", " ", t)
        i = t.find("交易状态")
        st = t[i + 5:i + 48].strip() if i > 0 else "?"
        print(f"{code}  {name}")
        print(f"    页面状态 : {st}")
        if rel:
            print(f"    最新申购公告: {rel[0].get('PUBLISHDATEDesc', '')}  {rel[0].get('TITLE', '')[:66]}")
        print()
    except Exception as e:
        print(f"{code}  {name}  失败: {e}\n")
