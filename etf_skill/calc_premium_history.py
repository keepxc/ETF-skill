"""拉取 513300 全量历史 K 线 + 净值，计算历史溢率分布"""
import json, urllib.request, csv, sys
from datetime import datetime

def get(url, headers=None):
    h = {"User-Agent": "Mozilla/5.0"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")

# 1. 全量 K 线（按日期区间分页拉，每页 800，不复权——ETF无分红，价格=原始价）
all_k = []
end_date = ""
while True:
    if end_date:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh513300,day,2020-01-01,{end_date},800,"
    else:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh513300,day,,,800,"
    try:
        d = json.loads(get(url))
    except Exception as e:
        print(f"K线拉取失败 @{end_date}: {e}")
        break
    if not isinstance(d, dict):
        print(f"异常返回 @{end_date}: {str(d)[:100]}")
        break
    kline = d.get("data", {}).get("sh513300", {})
    rows = kline.get("day") or [] if isinstance(kline, dict) else []
    if not rows:
        # 试试带复权的
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh513300,day,2020-01-01,{end_date},800,qfq"
        d = json.loads(get(url))
        kline = d.get("data", {}).get("sh513300", {})
        rows = kline.get("qfqday") or [] if isinstance(kline, dict) else []
    if not rows:
        break
    all_k.extend(rows)
    print(f"  已拉取 {len(all_k)} 条，最早 {rows[0][0]}")
    if len(rows) < 800 or rows[0][0] <= "2020-01-10":
        break
    end_date = rows[0][0]  # 下次拉取早于当前最早日期

print(f"K线总数: {len(all_k)}")
print(f"K线范围: {all_k[0][0]} ~ {all_k[-1][0]}")

# 2. 全量历史净值（分页拉，接口固定每页20条）
navs = {}
page = 1
total = None
while True:
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode=513300&pageIndex={page}&pageSize=20"
    try:
        d = json.loads(get(url, {"Referer": "https://fund.eastmoney.com/513300.html"}))
    except Exception as e:
        print(f"净值拉取失败 page={page}: {e}")
        break
    data = d.get("Data") or {}
    lst = data.get("LSJZList", []) if isinstance(data, dict) else []
    if not lst:
        break
    if total is None:
        total = d.get("TotalCount", 0)
    for item in lst:
        navs[item["FSRQ"]] = float(item["DWJZ"])
    print(f"  净值 {len(navs)}/{total} 条，最新 {lst[0]['FSRQ']}")
    if len(navs) >= total:
        break
    page += 1
print(f"净值总数: {len(navs)}")
print(f"净值范围: {min(navs)} ~ {max(navs)}")

# 3. 合并计算溢率：用当日收盘价 / 当日净值 - 1（同日才有意义）
rows_out = []
for k in all_k:
    date, close = k[0], float(k[2])
    if date in navs:
        prem = (close / navs[date] - 1) * 100
        rows_out.append((date, close, navs[date], prem))

print(f"同日匹配: {len(rows_out)} 条")
if rows_out:
    prems = [r[3] for r in rows_out]
    prems.sort()
    n = len(prems)
    def pct(p):
        return prems[min(int(p*n), n-1)]
    print(f"\n=== 历史溢率分布 ({rows_out[0][0]} ~ {rows_out[-1][0]}) ===")
    print(f"  样本数: {n}")
    print(f"  最低: {min(prems):+.2f}%")
    print(f"  P10:  {pct(0.10):+.2f}%")
    print(f"  P25:  {pct(0.25):+.2f}%")
    print(f"  中位: {pct(0.50):+.2f}%")
    print(f"  P75:  {pct(0.75):+.2f}%")
    print(f"  P90:  {pct(0.90):+.2f}%")
    print(f"  P95:  {pct(0.95):+.2f}%")
    print(f"  P99:  {pct(0.99):+.2f}%")
    print(f"  最高: {max(prems):+.2f}%")
    # 8.6% 的分位
    above = sum(1 for x in prems if x >= 8.6)
    print(f"\n  溢率 >= 8.6% 的天数: {above} / {n} = {above/n*100:.1f}%")
    above5 = sum(1 for x in prems if x >= 5)
    print(f"  溢率 >= 5.0% 的天数: {above5} / {n} = {above5/n*100:.1f}%")
    # 保存 CSV
    with open("/home/gyan/scripts/etf_skill/history_premium.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close", "nav", "premium_pct"])
        w.writerows(rows_out)
    print("\n已保存 history_premium.csv")
