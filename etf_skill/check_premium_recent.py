"""513390 近两周溢价轨迹：官方口径 + 纳指修正口径，及加仓线换算"""
import importlib.util, json, datetime

spec = importlib.util.spec_from_file_location("d", "/home/gyan/scripts/etf_skill/etf_daily.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

CODE = "513390"
now = datetime.datetime.now()
today = now.date()
print(f"现在 {now:%Y-%m-%d %H:%M} {['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]}")

q = d.fetch_quotes([CODE])[CODE]
print(f"实时: {q['name']} 价 {q['price']} 昨收 {q['prev_close']} 量 {q['vol']:.0f}手 时间戳 {q['ts']}")

cal = [r[0] for r in d.fetch_kline(CODE, 60)]
k = d.fetch_kline(CODE, 20)
navs = d.fetch_navs(CODE)
ndx = d.fetch_ndx_closes()

print(f"\n净值最新 3 条: {sorted(navs.items())[-3:]}")
print(f"纳指最新 3 个已完成交易日: {list(ndx.items())[-3:]}\n")

print("日期        收盘   净值(日期)      官方溢率   纳指修正溢率  NDX")
for date, close, _ in k[-10:]:
    pr = d.calc_premium(close, date, navs, cal)
    if not pr:
        print(f"{date}  {close:.3f}  净值缺失")
        continue
    est, ref, _ndx_ret, _fx_ret = d.correct_nav(pr["nav_date"], pr["nav"], ndx, d.fetch_fx_closes())
    corr = f"{(close/est-1)*100:+7.2f}%" if (est and ref != pr["nav_date"]) else "     —  "
    nd = f"{ndx[ref]:.0f}" if (est and ref in ndx) else ""
    print(f"{date}  {close:.3f}  {pr['nav']:.4f}({pr['nav_date'][5:]})  "
          f"{pr['prem']:+7.2f}%   {corr}       {nd}")

# 当前持仓
pos = json.loads(open("/home/gyan/scripts/etf_skill/position.json").read())
p = pos["positions"][0]
px = q["price"]
nav_now = sorted(navs.items())[-1]
prem_now = (px / nav_now[1] - 1) * 100
mv = p["shares"] * px
cost_total = p["shares"] * p["cost"]
print(f"\n持仓 {p['shares']} 股 @ {p['cost']}")
print(f"  现价 {px:.3f}  市值 {mv:,.0f}  盈亏 {mv-cost_total:+,.0f}（{(mv/cost_total-1)*100:+.2f}%）")
print(f"  官方溢率 {prem_now:+.2f}%（净值 {nav_now[0]} {nav_now[1]:.4f}）")

# 加仓线换算
tg = pos["trigger"]
print(f"\n触发线:")
for label, thr in [("加仓线 add_below_prem", tg["add_below_prem"]), ("警戒线 watch_above_prem", tg["watch_above_prem"])]:
    print(f"  {label} {thr:.0f}% → 净值 {nav_now[1]:.4f} 对应价格 {nav_now[1]*(1+thr/100):.3f}"
          f"（现价还需 {(nav_now[1]*(1+thr/100)/px-1)*100:+.1f}%）")

# 历史分位
import csv
hist = []
try:
    with open("/home/gyan/scripts/etf_skill/history_premium.csv") as f:
        for row in csv.DictReader(f):
            try: hist.append(float(row["premium"]))
            except Exception: pass
    hist.sort()
    n = len(hist)
    print(f"\n历史溢率分位（{n} 个交易日，2020-10 起）:")
    for v in hist:
        pass
    def q_(p): return hist[min(n-1, int(p*n))]
    print(f"  P10 {q_(.10):+.2f}%  P25 {q_(.25):+.2f}%  中位 {q_(.50):+.2f}%  P75 {q_(.75):+.2f}%  P90 {q_(.90):+.2f}%")
    below = sum(1 for v in hist if v < prem_now) / n * 100
    print(f"  当前 {prem_now:+.2f}% 处于第 {below:.0f} 百分位")
except Exception as e:
    print("历史分位失败:", e)
