"""查 016055 申购状态 / 限购额度 / 规模"""
import json, re, urllib.request

h = {"User-Agent": "Mozilla/5.0"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20).read().decode(enc, "replace")

for code in ["016055", "016057", "015299"]:
    print(f"===== {code} =====")
    try:
        u = (f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo?FCODE={code}"
             "&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        d = json.loads(get(u))
        dt = d.get("Datas") or {}
        keys = ["SHORTNAME", "SGZT", "SHZT", "SSBCZ", "MINSG", "MAXSG", "ENDNAV",
                "ESTABDATE", "INDEXNAME", "JJJL", "BUY", "SALE"]
        shown = {k: dt[k] for k in keys if k in dt}
        for k, v in shown.items():
            print(f"  {k}: {v}")
        if not shown:
            print("  (无字段) 原始:", str(dt)[:300])
    except Exception as e:
        print("  API 失败:", e)
    try:
        t = re.sub(r"<[^>]+>", " ", get(f"https://fund.eastmoney.com/{code}.html"))
        t = re.sub(r"\s+", " ", t)
        for kw in ["限大额", "暂停申购", "申购状态", "起购", "跟踪标的"]:
            i = t.find(kw)
            if i > 0:
                print(f"  网页 {kw}: {t[max(0, i - 40):i + 70].strip()}")
    except Exception as e:
        print("  网页失败:", e)
