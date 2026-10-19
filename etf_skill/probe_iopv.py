"""1) 找今日复牌时点  2) 试探 IOPV 数据源  3) 停牌公告日期序列"""
import json, urllib.request, time

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
def get(u, enc="utf-8", tries=3):
    err = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=20).read().decode(enc, "replace")
        except Exception as e:
            err = e; time.sleep(1)
    raise err

# 1) 复牌时点
print("=== 今日 513390 分时：找到第一个有成交量的分钟 ===")
m = json.loads(get("https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh513390"))["data"]["sh513390"]["data"]["data"]
prev_vol = 0
for p in m:
    parts = p.split(" ")
    if len(parts) >= 3:
        t0, price, vol = parts[0], float(parts[1]), float(parts[2])
        if vol > 0 and prev_vol == 0:
            print(f"  首次成交 {t0}  价 {price}  量 {vol}")
        prev_vol = vol
print(f"  收盘 {m[-1]}")

# 2) IOPV 试探
print("\n=== IOPV 试探 ===")
tests = [
    ("东财 push2 f78", "https://push2.eastmoney.com/api/qt/stock/get?secid=1.513390&fields=f43,f57,f58,f78,f79,f80,f169,f170"),
    ("东财 push2 全字段", "https://push2.eastmoney.com/api/qt/stock/get?secid=1.513390&fields=f1,f2,f3,f12,f13,f14,f43,f44,f45,f46,f47,f48,f60,f71,f84,f85,f92,f107,f116,f117,f152,f162,f167,f168,f169,f170,f171,f177"),
    ("新浪", "https://hq.sinajs.cn/list=sh513390"),
]
for nm, u in tests:
    try:
        h = dict(H); h["Referer"] = "https://finance.sina.com.cn"
        r = urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=15).read()
        try:
            txt = r.decode("utf-8")
        except Exception:
            txt = r.decode("gbk", "replace")
        print(f"  [{nm}] {txt[:400]}")
    except Exception as e:
        print(f"  [{nm}] 失败 {type(e).__name__}: {str(e)[:60]}")

# 3) 停牌公告日期
print("\n=== 513390 停复牌公告日期序列 ===")
g = json.loads(get("https://api.fund.eastmoney.com/f10/JJGG?fundcode=513390&pageIndex=1&pageSize=30&type=0"))
for it in (g.get("Data") or []):
    t = it.get("TITLE", "")
    if "停复牌" in t:
        print(f"  {it.get('PUBLISHDATEDesc','')}")
