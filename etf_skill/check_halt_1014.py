"""查 2026-10-14 停牌名单 + 513390 公告 + 最新溢价"""
import json, re, urllib.request

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

CANDS = ["513390","513300","513100","159941","159501","159660","513870","513110",
         "159632","159659","159696","159513","513500","159612","159655","513650",
         "159577","513850","513310","513290","513400","159509"]

print("=== 最新公告（含停牌/溢价）===")
for code in CANDS:
    try:
        raw = get(f"https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=6&type=0")
        d = json.loads(raw)
        lst = d.get("Data") or []
        hits = [x for x in lst if any(k in x.get("TITLE","") for k in ["停", "溢价"])]
        if hits:
            x = hits[0]
            print(f"{code}  {x.get('PUBLISHDATEDesc','')}  {x.get('TITLE','')[:60]}")
    except Exception as e:
        print(f"{code} 失败: {str(e)[:40]}")

print("\n=== 今日行情 + 最新净值 + 溢价 ===")
raw = get("https://qt.gtimg.cn/q=" + ",".join(("sh" if c.startswith("5") else "sz") + c for c in CANDS), enc="gbk")
qt = {}
for line in raw.strip().split(";"):
    f = line.split("~")
    if len(f) < 45: continue
    try:
        qt[f[2]] = {"name": f[1], "price": float(f[3]), "chg": float(f[32]),
                    "turn": float(f[38]), "scale": float(f[44]),
                    "amt": float(f[35].split("/")[2]) / 1e8}
    except Exception: pass

def nav(code):
    try:
        raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE={code}&pageIndex=1&pageSize=2&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        ls = json.loads(raw).get("Datas") or []
        return (ls[0].get("FSRQ"), float(ls[0]["DWJZ"])) if ls else (None, None)
    except Exception:
        return (None, None)

rows = []
for c in CANDS:
    i = qt.get(c, {})
    nd, nv = nav(c)
    pr = (i["price"]/nv - 1)*100 if (i.get("price") and nv) else None
    rows.append((c, i.get("name",""), i.get("price"), i.get("chg"), pr, i.get("turn"), i.get("scale"), i.get("amt"), nd))
rows = [r for r in rows if r[4] is not None]
rows.sort(key=lambda r: r[4])
print(f"{'代码':<8}{'名称':<20}{'价':>7}{'涨跌':>8}{'溢率':>8}{'换手':>8}{'规模亿':>8}{'成交亿':>8}{'净值日':>11}")
for r in rows:
    print(f"{r[0]:<8}{r[1][:18]:<20}{r[2]:>7.3f}{r[3]:>7.2f}%{r[4]:>7.2f}%{r[5]:>7.1f}%{r[6]:>8.1f}{r[7]:>8.2f}{str(r[8]):>11}")
