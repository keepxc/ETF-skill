"""全市场场内ETF清单 -> 筛跨境/美股方向"""
import json, urllib.request, re

H = {"User-Agent": "Mozilla/5.0"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode("utf-8", "replace")

rows = []
for pn in range(1, 15):
    u = ("https://push2.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&po=0&np=1&fltt=2&invt=2&fid=f12"
         "&fs=b:MK0021,b:MK0022,b:MK0023,b:MK0024&fields=f12,f14,f2,f3,f5,f6,f20,f21") % pn
    try:
        d = json.loads(get(u))
    except Exception as e:
        print("err", pn, e); break
    diff = ((d.get("data") or {}).get("diff") or [])
    if not diff:
        break
    for x in diff:
        rows.append(x)
    if len(diff) < 200:
        break

print(f"场内基金/ETF 总数: {len(rows)}")

# 关键词筛跨境/美股相关
KW = ["纳斯达克", "纳指", "标普", "道琼斯", "美国", "美股", "海外", "全球", "中概", "恒生科技",
      "恒生互联网", "恒生", "港", "亚洲", "日经", "德国", "法国", "东南亚", "沙特", "越南", "印度"]
hits = []
for x in rows:
    nm = str(x.get("f14") or "")
    if any(k in nm for k in KW):
        hits.append(x)

print(f"命中跨境相关: {len(hits)}\n")
hits.sort(key=lambda x: -(x.get("f6") or 0))
print(f"{'代码':<9}{'名称':<22}{'现价':>8}{'涨跌':>8}{'成交额(亿)':>11}{'规模(亿)':>10}")
for x in hits:
    code = x.get("f12"); nm = str(x.get("f14"))
    px = x.get("f2"); ch = x.get("f3"); amt = x.get("f6"); mcap = x.get("f20")
    amt = f"{amt/1e8:.2f}" if isinstance(amt, (int, float)) else "-"
    mcap = f"{mcap/1e8:.1f}" if isinstance(mcap, (int, float)) else "-"
    print(f"{code:<9}{nm:<22}{str(px):>8}{str(ch):>8}{amt:>11}{mcap:>10}")
