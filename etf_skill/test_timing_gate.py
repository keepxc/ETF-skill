"""test_timing_gate.py — 开盘时点/停牌/去重 三条路径的回归（慢集，不进 hook）。

2026-11-01 两个修正（都是踩出来的）：
1. **不再碰生产 run_state.json**。原来它 `unlink()` 真文件、结束时再写回备份；
   一旦超时被 kill，"写回"那步就不执行 → 生产去重锚点直接消失（当天实测丢了，
   手工重建为 `{}`）。现在把 `m.RUN_STATE` 指到临时目录，生产文件一个字节都不动。
2. **加 90 秒硬超时**。main() 会拉行情，网络慢时会挂到天荒地老 ——
   测试卡死比测试变红更坏（会一直占着 gate）。超时即判失败。
"""
import contextlib
import datetime as _dt
import importlib.util
import io
import json
import signal
import sys
import tempfile
from pathlib import Path

HERE = Path("/home/gyan/scripts/etf_skill")
sys.path.insert(0, str(HERE))

CASE_TIMEOUT = 300         # 每个场景硬上限：09:30 那条要拉 5 只 ETF 净值，实测可到 ~245s
_TMPDIR = tempfile.TemporaryDirectory(prefix="etf_test_state_")
TMP_RS = Path(_TMPDIR.name) / "run_state.json"
PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if detail and not cond else ""))


class FakeDateTime(_dt.datetime):
    frozen = _dt.datetime(2026, 10, 20, 9, 30, 5)

    @classmethod
    def now(cls, tz=None):
        return cls.frozen


class FakeDate(_dt.date):
    @classmethod
    def today(cls):
        return FakeDateTime.frozen.date()


_dt.datetime = FakeDateTime
_dt.date = FakeDate


def _alarm(signum, frame):
    raise TimeoutError(f"单场景超过 {CASE_TIMEOUT}s（多半是拉行情卡住）")


def load():
    spec = importlib.util.spec_from_file_location("etf_daily_t", HERE / "etf_daily.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    setattr(m, "datetime", _dt)          # 注入假时钟
    setattr(m, "RUN_STATE", TMP_RS)     # 关键：状态文件指向临时目录，不碰生产
    return m


def _guarded(m):
    """跑一次 main()，带硬超时 + 输出捕获。返回 (输出, 错误)。"""
    buf = io.StringIO()
    err = None
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(CASE_TIMEOUT)
    try:
        with contextlib.redirect_stdout(buf):
            m.main()
    except TimeoutError as e:
        err = str(e)
    except Exception as e:                  # noqa: BLE001 —— 崩了也要有判据
        err = f"{type(e).__name__}: {e}"
    finally:
        signal.alarm(0)
    return buf.getvalue(), err


def run(label, when):
    """冻结时钟跑一次，返回 (输出, 落盘的 run_state, 错误)。"""
    FakeDateTime.frozen = when
    TMP_RS.unlink(missing_ok=True)
    m = load()
    out, err = _guarded(m)
    st = json.loads(TMP_RS.read_text()) if TMP_RS.exists() else {}
    print(f"── {label}  {when:%m-%d %H:%M:%S}   输出行数 {len(out.splitlines())}  run_state={st}")
    if err:
        print(f"   ⚠ {err}")
    return out, st, err


print("== A 临停日 09:30（开盘停牌 → 应只登记 defer）==")
out_a, st_a, err_a = run("A", _dt.datetime(2026, 10, 20, 9, 30, 5))
check("A 不超时/不崩", err_a is None, err_a or "")
check("A 有输出", len(out_a.splitlines()) > 0, "无输出")
# 实测（2026-11-01）：09:30 遇休市会照发（「休市，价格为最近收盘」），并落 sent。
# 真正要锁的是「只要跑过就必须落 sent」——漏了它同一天会被反复推送。
check("A 落 sent=当天（否则当天会被重复推送）", st_a.get("sent") == "2026-10-20", str(st_a))

print("== B 临停日 10:32（兜底任务 → 应真跑并标记 sent）==")
out_b, st_b, err_b = run("B", _dt.datetime(2026, 10, 20, 10, 32, 30))
check("B 不超时/不崩", err_b is None, err_b or "")
check("B 有输出（复牌价至少一行）", len(out_b.splitlines()) > 0, "无输出")
check("B 标记 sent=当天", st_b.get("sent") == "2026-10-20", str(st_b))

print("== C 同一天再跑（去重 → 必须静默零输出）==")
FakeDateTime.frozen = _dt.datetime(2026, 10, 20, 10, 33, 0)
m = load()
out_c, err_c = _guarded(m)
check("C 不超时/不崩", err_c is None, err_c or "")
check("C 静默零输出（当日已推过）", out_c.strip() == "", repr(out_c[:120]))

print("== E 非交易日（周日 → 静默顺延，不落 sent）==")
out_e, st_e, err_e = run("E", _dt.datetime(2026, 10, 25, 9, 30, 5))
check("E 不超时/不崩", err_e is None, err_e or "")
check("E 静默零输出（休市不推残缺日报）", out_e.strip() == "", repr(out_e[:120]))
check("E 不落 sent（否则下个交易日被去重吃掉）", st_e.get("sent") is None, str(st_e))

print("== F 净值源故障 10:32（顺延，不发半成品日报）==")
FakeDateTime.frozen = _dt.datetime(2026, 11, 2, 10, 32, 30)
TMP_RS.unlink(missing_ok=True)
m = load()


def _boom(code):
    raise TimeoutError("mock: 净值源超时")


m.fetch_navs = _boom
out_f, err_f = _guarded(m)
st_f = json.loads(TMP_RS.read_text()) if TMP_RS.exists() else {}
check("F 不超时/不崩", err_f is None, err_f or "")
check("F 静默零输出（数据不全不发）", out_f.strip() == "", repr(out_f[:120]))
check("F 不落 sent（留给后面的班次重试）", st_f.get("sent") is None, str(st_f))

print("== D 生产文件没被动过 ==")
prod = HERE / "run_state.json"
check("生产 run_state.json 存在（测试不得删除它）", prod.exists(), str(prod))
if prod.exists():
    print(f"   生产文件当前内容：{prod.read_text().strip()[:120]}")

_TMPDIR.cleanup()
print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
sys.exit(1 if FAIL else 0)
