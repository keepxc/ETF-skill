"""开盘时点逻辑测试：冻结时钟跑 main()，验证 停牌/正常/去重 三条路径"""
import datetime as _dt, importlib.util, io, json, sys, contextlib
from pathlib import Path

HERE = Path("/home/gyan/scripts/etf_skill")
sys.path.insert(0, str(HERE))


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


def load():
    spec = importlib.util.spec_from_file_location("etf_daily_t", HERE / "etf_daily.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.datetime = _dt          # 注入假时钟
    return m


def run(label, when):
    FakeDateTime.frozen = when
    (HERE / "run_state.json").unlink(missing_ok=True)
    m = load()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main()
    out = buf.getvalue()
    st = json.loads((HERE / "run_state.json").read_text()) if (HERE / "run_state.json").exists() else {}
    head = out.splitlines()[2:4] if out else ["(无输出)"]
    print(f"── {label}  {when:%m-%d %H:%M:%S}")
    print(f"   输出行数 {len(out.splitlines())}  run_state={st}")
    for h in head:
        print("   ", h.strip())


run("A 临停日 09:30", _dt.datetime(2026, 10, 20, 9, 30, 5))
run("B 临停日 10:32（兜底任务）", _dt.datetime(2026, 10, 20, 10, 32, 30))

# C 去重：10:32 跑过一次后再跑一次
FakeDateTime.frozen = _dt.datetime(2026, 10, 20, 10, 33, 0)
m = load()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    m.main()
print(f"── C 同一天再跑一次  10:33:00")
print(f"   输出行数 {len(buf.getvalue().splitlines())}（应为 0 = 静默去重）")

(HERE / "run_state.json").unlink(missing_ok=True)
print("\n[清理] run_state.json 已删除（真实推送未发生）")
