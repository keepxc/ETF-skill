"""513390 实际持仓 + 行业分布 —— 验证"纳指=美股科技"是否成立"""
import json, re, urllib.request

H = {"User-Agent": "Mozilla/5.0", "Referer": "http://fundf10.eastmoney.com/"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode("utf-8", "replace")

for code, nm in [("513390", "纳指100ETF博时"), ("513300", "纳斯达克ETF华夏")]:
    print(f"########## {code} {nm} ##########")
    # 前十大
    for yr, mo in [("2026","6"),("2026","3")]:
        try:
            raw = get(f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=20&year={yr}&month={mo}")
            t = re.sub(r"<[^>]+>", "|", raw); t = re.sub(r"[|\s]+", "|", t)
            i = t.find("股票代码")
            if i > 0:
                print(f"\n-- 前二十大 {yr}-{mo} --")
                print(t[i:i+1400])
                break
        except Exception as e:
            print(f"  {yr}-{mo} 失败 {e}")

    # 行业配置
    try:
        raw = get(f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=hytz&code={code}")
        t = re.sub(r"<[^>]+>", "|", raw); t = re.sub(r"[|\s]+", "|", t)
        i = t.find("行业类别")
        print(f"\n-- 行业配置 --")
        print(t[i:i+700] if i > 0 else t[:500])
    except Exception as e:
        print("  行业失败:", e)
    print()
