"""抓 513390 / 513300 / 159509 最新公告原文"""
import json, re, urllib.request

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

for code in ["513390", "513300", "159509"]:
    print(f"########## {code} ##########")
    try:
        d = json.loads(get(f"https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=10&type=0"))
        for it in (d.get("Data") or [])[:10]:
            t = it.get("TITLE", "")
            if any(k in t for k in ["停", "溢价"]):
                print(f"  {it.get('PUBLISHDATEDesc','')}  ID={it.get('ID')}  {t[:70]}")
                # 尝试抓正文
                for pat in [f"https://fund.eastmoney.com/gonggao/{code},{it['ID']}.html",
                            f"http://fund.eastmoney.com/gonggao/{code},{it['ID']}.html"]:
                    try:
                        body = get(pat)
                        txt = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
                        txt = re.sub(r"<[^>]+>", " ", txt)
                        txt = re.sub(r"\s+", " ", txt)
                        j = txt.find("停牌")
                        if j > 0:
                            print("     正文:", txt[max(0, j-260):j+300].strip())
                            break
                    except Exception:
                        pass
    except Exception as e:
        print("  失败:", str(e)[:60])
    print()
