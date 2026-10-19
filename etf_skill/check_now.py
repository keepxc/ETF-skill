"""确认当前时间 + 513390 最新行情与净值"""
import json, urllib.request, datetime

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

print("系统时间:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A"))

raw = get("https://qt.gtimg.cn/q=sh513390,sh513300,sh513100", enc="gbk")
for line in raw.strip().split(";"):
    f = line.split("~")
    if len(f) < 45: continue
    print(f"\n{f[2]} {f[1]}")
    print(f"  现价 {f[3]}   昨收 {f[4]}   今开 {f[5]}   涨跌 {f[32]}%")
    print(f"  最高 {f[33]}   最低 {f[34]}   成交额 {float(f[35].split('/')[2])/1e8:.2f}亿")
    print(f"  数据时间戳 {f[30]}")

print("\n=== 最新净值 ===")
for c in ["513390","513300","513100"]:
    try:
        d = json.loads(get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE={c}&pageIndex=1&pageSize=3&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0"))
        for x in (d.get("Datas") or [])[:3]:
            print(f"  {c}  {x.get('FSRQ')}  {x.get('DWJZ')}")
    except Exception as e:
        print(f"  {c} 失败 {e}")
