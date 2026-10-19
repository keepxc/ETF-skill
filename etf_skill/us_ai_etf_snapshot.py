"""美股AI方向场内ETF：实时溢价 + 费率 + 流动性"""
import json, re, urllib.request, datetime

H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36",
     "Referer": "https://fund.eastmoney.com/"}
def get(u, enc="utf-8"):
    return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25).read().decode(enc, "replace")

CANDS = {
    # 代码: (名称, 分类)
    "159509": ("纳指科技ETF景顺", "纳指科技"),
    "513390": ("纳指100ETF博时", "纳指100"),
    "513300": ("纳斯达克ETF华夏", "纳指100"),
    "513100": ("纳指ETF国泰", "纳指100"),
    "159941": ("纳指ETF广发", "纳指100"),
    "159501": ("纳指ETF嘉实", "纳指100"),
    "159660": ("纳指ETF汇添富", "纳指100"),
    "513870": ("纳指ETF富国", "纳指100"),
    "513110": ("纳指ETF华泰柏瑞", "纳指100"),
    "159632": ("纳斯达克ETF华安", "纳指100"),
    "159659": ("纳斯达克100ETF招商", "纳指100"),
    "159696": ("纳指ETF易方达", "纳指100"),
    "159513": ("纳斯达克100ETF大成", "纳指100"),
    "513500": ("标普500ETF博时", "标普500"),
    "159612": ("标普500ETF国泰", "标普500"),
    "159655": ("标普500ETF华夏", "标普500"),
    "513650": ("标普500ETF南方", "标普500"),
    "159577": ("美国50ETF汇添富", "美国50"),
    "513850": ("美国50ETF易方达", "美国50"),
    "513310": ("中韩半导体ETF华泰柏瑞", "中韩半导体"),
    "513290": ("纳指生物科技ETF汇添富", "纳指生物"),
    "513400": ("道琼斯ETF鹏华", "道指"),
}
def mkt(c):
    return "sh" if c.startswith(("5", "6")) else "sz"

# 1) 实时行情
q = {}
raw = get("https://qt.gtimg.cn/q=" + ",".join(mkt(c) + c for c in CANDS), enc="gbk")
for line in raw.strip().split(";"):
    f = line.split("~")
    if len(f) < 45: continue
    try:
        q[f[2]] = {"name": f[1], "price": float(f[3]), "prev": float(f[4]),
                   "amt": float(f[37]) / 1e4 if f[37] else None,   # 成交额(万)
                   "scale": float(f[44]) if len(f) > 44 and f[44] else None}
    except Exception:
        pass

# 2) 最新净值（用于溢价）
def last_nav(code):
    try:
        raw = get(f"https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList?FCODE={code}&pageIndex=1&pageSize=2&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0")
        ls = json.loads(raw).get("Datas") or []
        if ls:
            return ls[0].get("FSRQ"), float(ls[0]["DWJZ"])
    except Exception:
        pass
    return None, None

# 3) 费率
def fee(code):
    try:
        t = re.sub(r"<[^>]+>", " ", get(f"https://fundf10.eastmoney.com/jjfl_{code}.html"))
        t = re.sub(r"\s+", " ", t)
        m1 = re.search(r"管理费率\s*([\d.]+)%", t)
        m2 = re.search(r"托管费率\s*([\d.]+)%", t)
        if m1 and m2:
            return float(m1.group(1)) + float(m2.group(1))
    except Exception:
        pass
    return None

print(f"{'代码':<8}{'名称':<20}{'分类':<10}{'价':>7}{'净值':>8}{'净值日':>11}{'溢率':>8}{'费率':>7}{'成交(亿)':>10}")
rows = []
for c, (nm, cat) in CANDS.items():
    info = q.get(c, {})
    px = info.get("price")
    nd, nv = last_nav(c)
    f_ = fee(c)
    prem = (px / nv - 1) * 100 if (px and nv) else None
    rows.append((c, nm, cat, px, nv, nd, prem, f_, info.get("amt")))
    pxs = f"{px:.3f}" if px else "-"
    nvs = f"{nv:.4f}" if nv else "-"
    prs = f"{prem:+.2f}%" if prem is not None else "-"
    fs = f"{f_:.2f}%" if f_ is not None else "-"
    ams = f"{info['amt']/1e4:.2f}" if info.get("amt") else "-"
    print(f"{c:<8}{nm:<20}{cat:<10}{pxs:>7}{nvs:>8}{str(nd):>11}{prs:>8}{fs:>7}{ams:>10}")

print("\n按溢率排序:")
for r in sorted([x for x in rows if x[6] is not None], key=lambda x: x[6]):
    print(f"  {r[0]} {r[1]:<20} {r[6]:+.2f}%  费率 {r[7]:.2f}%/年  成交 {r[8]/1e4:.2f}亿" if r[8] else f"  {r[0]} {r[1]} {r[6]:+.2f}%")
