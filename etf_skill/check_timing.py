"""1) 10-16 净值是否已公布  2) 今日停牌与复牌时点  3) 当前 cron 配置"""
import json, urllib.request, time, subprocess

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8", tries=4):
    err = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")
        except Exception as e:
            err = e; time.sleep(1.5)
    raise err

print("=== 513390 已公布净值（最新8条）===")
d = json.loads(get("https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE=513390&pageIndex=1&pageSize=8&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"))["Datas"]
for x in d:
    print(f"  {x['FSRQ']}  {x['DWJZ']}")

print("\n=== 513300 已公布净值（最新5条）===")
d2 = json.loads(get("https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE=513300&pageIndex=1&pageSize=5&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"))["Datas"]
for x in d2:
    print(f"  {x['FSRQ']}  {x['DWJZ']}")

print("\n=== 513390 最新公告（停复牌）===")
try:
    g = json.loads(get("https://api.fund.eastmoney.com/f10/JJGG?fundcode=513390&pageIndex=1&pageSize=8&type=0"))
    for it in (g.get("Data") or [])[:8]:
        if any(k in it.get("TITLE","") for k in ["停","溢价"]):
            print(f"  {it.get('PUBLISHDATEDesc','')}  {it.get('TITLE','')[:64]}")
except Exception as e:
    print("  失败:", e)

print("\n=== 今日(10-19) 513390 分时首末 ===")
try:
    u = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=sh513390"
    m = json.loads(get(u))["data"]["sh513390"]["data"]["data"]
    print(f"  分时点数量 {len(m)}")
    for p in m[:5]:
        print(f"    {p}")
    print("    ...")
    for p in m[-3:]:
        print(f"    {p}")
except Exception as e:
    print("  失败:", e)

print("\n=== 当前 cron ===")
try:
    print(subprocess.run(["bash","-lc","crontab -l 2>/dev/null | grep -i etf"], capture_output=True, text=True).stdout or "  (crontab 无 etf 条目)")
except Exception as e:
    print("  失败:", e)
