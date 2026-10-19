"""修正成交额解析 + 交叉验证 159509 溢价 + 检查标普信息科技LOF申购状态"""
import json, re, urllib.request

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

# 1) 看 gtimg 原始字段，定位成交额
raw = get("https://qt.gtimg.cn/q=sh513390,sz159509,sh513310", enc="gbk")
for line in raw.strip().split(";"):
    if not line.strip(): continue
    f = line.split("~")
    print(f"--- {f[2]} {f[1]}  共 {len(f)} 字段 ---")
    for i in range(min(len(f), 50)):
        if f[i]:
            print(f"   [{i}] {f[i]}")
    print()

# 2) 交叉验证 159509 溢价（用东财行情页）
print("=== 159509 交叉验证 ===")
try:
    t = re.sub(r"<[^>]+>", " ", get("https://fund.eastmoney.com/159509.html"))
    t = re.sub(r"\s+", " ", t)
    for kw in ["交易状态", "溢价", "净值", "基金规模"]:
        i = t.find(kw)
        if i > 0:
            print(f"  {kw}: {t[i:i+110].strip()}")
except Exception as e:
    print("  失败:", e)

# 3) 标普信息科技 LOF 161128 申购状态
print("\n=== 161128 易方达标普信息科技(QDII-LOF)A ===")
try:
    t = re.sub(r"<[^>]+>", " ", get("https://fund.eastmoney.com/161128.html"))
    t = re.sub(r"\s+", " ", t)
    i = t.find("交易状态")
    print("  ", t[i:i+120].strip() if i > 0 else "未找到")
except Exception as e:
    print("  失败:", e)

# 4) 用 kline 计算真实成交额（近5日均）
def turnover(code):
    mkt = "sh" if code.startswith("5") else "sz"
    u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,10,"
    try:
        d = json.loads(get(u))["data"][mkt + code]
        rows = d.get("day") or []
        amts = [float(r[5]) * 100 * float(r[2]) for r in rows]  # 手*100*价
        return sum(amts) / len(amts) / 1e8 if amts else None
    except Exception:
        return None

print("\n=== 近 10 日均成交额 ===")
for c in ["159509","513390","513300","513100","159941","159501","159660","513870",
          "513110","159632","159659","159696","159513","513500","159612","159655",
          "513650","159577","513850","513310","513290","513400"]:
    tv = turnover(c)
    print(f"  {c}  {tv:.2f} 亿" if tv else f"  {c}  n/a")
