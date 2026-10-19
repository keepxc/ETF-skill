"""513300 历史溢价恢复时间分析：实际数据"""
import json, re, urllib.request, urllib.parse, datetime, statistics

h = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25).read().decode("utf-8", "replace")

# 1. 拿 513300 最近200条净值
navs = []
u = "https://api.fund.eastmoney.com/f10/lsjz?fundCode=513300&pageIndex=1&pageSize=200"
d = json.loads(get(u))
ls = d.get("Data", {}).get("LSJZList", [])
print(f"513300 历史净值条数: {len(ls)}")
for x in ls[:8]:
    print("sample nav:", x)
print()

# 2. 找历史溢价数据
# 东财有基金历史净值接口，但需要价格；试试取 513300 近两年每日价格
# 先用 ETF 官方行情/华夏基金
# 36氪/微博/财富网/天天基金/行情通
# 取近一天最近的200个价格交易日
# 如果没有历史价格，找 513300 历史净值 + 近期价格手动构建

# 4. 计算溢价历史分布
values = [float(x["DWJZ"]) for x in ls]
dates = [x["FSRQ"] for x in ls]
print("时间范围:", dates[0], "至", dates[-1])
print("近30日净值变化:", [f"{dates[i]} {values[i]:.4f}" for i in range(len(values)-30, len(values))])
