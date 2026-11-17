"""npuzoo bench with the stand-in runtime from test_runner."""
import json

from npuzoo import bench, rkllm_rt as rt
from tests.test_runner import FakeLib


def test_summarise_takes_medians():
    perfs = [{"prefill_ms": 100.0, "prefill_tokens": 50, "generate_ms": 1000.0, "generate_tokens": 10, "memory_mb": 900.0},
             {"prefill_ms": 50.0, "prefill_tokens": 50, "generate_ms": 500.0, "generate_tokens": 10, "memory_mb": 950.0},
             {"prefill_ms": 25.0, "prefill_tokens": 50, "generate_ms": 2000.0, "generate_tokens": 10, "memory_mb": 920.0}]
    s = bench.summarise(perfs)
    assert s["prefill_tps"] == 1000.0 and s["generate_tps"] == 10.0 and s["memory_mb"] == 950.0 and s["runs"] == 3


def test_run_workloads_skips_warmup(capsys):
    lib = FakeLib("1.3")
    s = rt.Session(lib, "1.3", "/m.rkllm", ignore_eos=True)
    assert lib.param.ignore_eos_token
    res = bench.run_workloads(s, repeats=2)
    assert set(res) == {"chat", "long-prompt"} and res["chat"]["runs"] == 2
    assert sum(1 for c in lib.calls if c[0] == "run") == 6           # (1 warm-up + 2) x 2 workloads
    assert lib.calls[1][-1] == 128 and lib.calls[-1][-1] == 16      # per-run max_new_tokens (1.3)


def test_ignore_eos_is_skipped_on_12():
    lib = FakeLib("1.2")
    rt.Session(lib, "1.2", "/m.rkllm", ignore_eos=True)             # field does not exist there: no error


def test_report_shape(tmp_path):
    m = tmp_path / "m.rkllm"
    m.write_bytes(b"x" * 10)
    rep = bench.report({"chip": "rk3588", "runtime": "1.3.1", "governor": "ondemand", "load_s": 3.2},
                       {"chat": {"generate_tps": 12.0}}, str(m), bench.file_digest(str(m)))
    assert rep["model"]["bytes"] == 10 and len(rep["model"]["sha256"]) == 64
    json.dumps(rep)
