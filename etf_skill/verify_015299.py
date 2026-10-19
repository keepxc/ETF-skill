"""核实 015299/015300 的申购状态 + 最近公告"""
import json, re, urllib.request

h = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20).read().decode(enc, "replace")

print("=== 申购相关公告（带日期）===")
for code in ["015299", "015300"]:
    print(f"--- {code} ---")
    try:
        d = json.loads(get(f"https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=30&type=0"))
        for it in (d.get("Data") or []):
            t = it.get("TITLE", "")
            if any(k in t for k in ["申购", "限额", "大额", "暂停", "恢复"]):
                print(f"  {it.get('NOTICE_DATE', '')[:10]}  {t[:85]}")
    except Exception as e:
        print("  失败:", e)
    print()

print("=== 当前页面状态 ===")
for code in ["015299", "015300"]:
    try:
        t = re.sub(r"<[^>]+>", " ", get(f"https://fund.eastmoney.com/{code}.html"))
        t = re.sub(r"\s+", " ", t)
        i = t.find("交易状态")
        print(f"  {code}: {t[i:i + 100].strip()}")
    except Exception as e:
        print(f"  {code} 失败:", e)
