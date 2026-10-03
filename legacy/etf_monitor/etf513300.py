"""ETF 513300 (纳斯达克ETF华夏) 数据获取工具"""
import httpx

ETF_CODE = "513300"


def _get_json(url: str) -> dict:
    with httpx.Client(timeout=10) as c:
        return c.get(url).json()


def _get_text(url: str) -> str:
    with httpx.Client(timeout=10) as c:
        return c.get(url).text


def realtime() -> dict:
    """获取实时行情 — 腾讯 qt 接口"""
    url = f"https://qt.gtimg.cn/q=sh{ETF_CODE}"
    text = _get_text(url)
    fields = text.split("~")
    # 找 "现价/成交量/成交额" 组合字段
    amount = 0
    for f in fields:
        parts = f.split("/")
        if len(parts) == 3:
            try:
                amount = float(parts[2])
                break
            except ValueError:
                continue
    return {
        "code": fields[2],
        "name": fields[1],
        "price": float(fields[3]),
        "prev_close": float(fields[4]),
        "open": float(fields[5]),
        "volume": int(fields[6]) if fields[6] else 0,
        "high": float(fields[33]) if len(fields) > 33 and fields[33] else float(fields[3]),
        "low": float(fields[34]) if len(fields) > 34 and fields[34] else float(fields[3]),
        "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] else 0,
        "change_amt": float(fields[31]) if len(fields) > 31 and fields[31] else 0,
        "amount": amount,  # 元
        "time": fields[30] if len(fields) > 30 else "",
    }


def klines(n: int = 20) -> list[dict]:
    """获取最近 n 根日K — 腾讯财经 API"""
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param=sh{ETF_CODE},day,,,{n},qfq")
    raw = _get_json(url)["data"][f"sh{ETF_CODE}"]["day"]
    result = []
    for parts in raw:
        result.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
        })
    return result


def ma(klines_data: list[dict], period: int = 5) -> float | None:
    """计算 MA"""
    if len(klines_data) < period:
        return None
    closes = [k["close"] for k in klines_data[-period:]]
    return sum(closes) / period
