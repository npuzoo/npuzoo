"""npuzoo convert, with stand-ins for rkllm-toolkit and the conversion child."""
import json
import sys
import types

import pytest

from npuzoo import convert as cv
from npuzoo.inspect import parse_name, MIN_PLAUSIBLE_BYTES


def test_toolkit_spelling():
    assert cv.platform_args("1.3.1", "rk3588", "w8a8") == ("RK3588", "W8A8")
    assert cv.platform_args("1.1.4", "rk3588", "w8a8") == ("rk3588", "w8a8")
    assert cv.algorithm_for("1.2.3", "w4a16_g128") == "grq" and cv.algorithm_for("1.1.4", "w4a16") == "normal"
    assert cv.algorithm_for("1.3.1", "w8a8") == "normal"


def test_output_name_is_readable_by_inspect():
    name = cv.output_name("Qwen/Qwen3-1.7B", "rk3576", "w4a16_g128", "1.3.1")
    assert name == "Qwen3-1.7B_rk3576_w4a16_g128_rkllm-1.3.1.rkllm"
    claims = parse_name(name)
    assert claims["chip"] == "rk3576" and claims["dtype"] == "w4a16" and claims["group"] == "g128"
    assert claims["toolkit"] == "1.3.1"


def _model_dir(tmp_path, params=1_000_000, arch="Qwen3ForCausalLM", dtype="bfloat16"):
    d = tmp_path / "m"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"architectures": [arch], "torch_dtype": dtype}))
    (d / "model.safetensors").write_bytes(b"\0" * params * 2)
    return d


def test_model_facts(tmp_path):
    f = cv.model_facts(str(_model_dir(tmp_path, params=500_000)))
    assert f["architecture"] == "Qwen3ForCausalLM" and f["params_b"] == 0.0 and f["weights_bytes"] == 1_000_000


def test_preflight_stops_on_memory_and_family(monkeypatch):
    monkeypatch.setattr(cv, "swap_gb", lambda: 0.0)
    info = {"system": "Linux", "machine": "x86_64", "python": "3.10.12", "mem_gb": 16.0, "toolkit": "1.2.3",
            "requires": [], "installed": {}, "pkg_resources": True, "gpu": None, "disk_free_gb": 100}
    fatal, lines = cv.preflight(info, {"params_b": 1.7}, "1.2.3", "1.2.1")
    assert not fatal
    fatal, lines = cv.preflight(info, {"params_b": 4.0}, "1.2.3", None)       # 3 + 26 GB > 16 GB
    assert fatal and "memory" in lines[-1]
    fatal, lines = cv.preflight(info, {"params_b": 0.8}, "1.2.3", "1.3.0")    # Qwen3.5 on 1.2.3
    assert fatal and "1.3.0" in lines[-1]


class FakeRKLLM(object):
    calls = []

    def load_huggingface(self, model, model_lora=None, device="cpu", dtype="float32"):
        FakeRKLLM.calls.append(("load", model, dtype))
        return 0

    def build(self, do_quantization, optimization_level, quantized_dtype, quantized_algorithm,
              target_platform, num_npu_core, dataset=None, max_context=4096):
        FakeRKLLM.calls.append(("build", quantized_dtype, quantized_algorithm, target_platform, num_npu_core,
                                dataset, max_context))
        return 0

    def export_rkllm(self, path):
        with open(path, "wb") as f:
            f.write(bytes.fromhex("daeeb336") + b"\0" * 64)
        FakeRKLLM.calls.append(("export", path))
        return 0


def test_child_build_passes_only_what_the_release_accepts(tmp_path, monkeypatch, capsys):
    api = types.ModuleType("rkllm.api")
    api.RKLLM = FakeRKLLM
    monkeypatch.setitem(sys.modules, "rkllm", types.ModuleType("rkllm"))
    monkeypatch.setitem(sys.modules, "rkllm.api", api)
    FakeRKLLM.calls = []
    out = tmp_path / "x.rkllm"
    assert cv.child_build("/m", "rk3576", "w4a16_g128", "1.3.1", "/d.json", str(out), 2048) == 0
    assert FakeRKLLM.calls[1] == ("build", "W4A16_G128", "grq", "RK3576", 2, "/d.json", 2048)
    text = capsys.readouterr().out
    assert "RESULT ok" in text and "has no custom_config, load_weight" in text and "extra_qparams" in text


def _pc(toolkit="1.3.1"):
    return {"system": "Linux", "machine": "x86_64", "python": "3.10.12", "mem_gb": 64.0, "toolkit": toolkit,
            "requires": [], "installed": {}, "pkg_resources": True, "gpu": None, "disk_free_gb": 100}


def test_cmd_convert_local_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("npuzoo.pc.collect_pc", lambda: _pc())
    monkeypatch.setenv("NPUZOO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cv, "HOME", str(tmp_path / "home"))
    seen = []

    def fake_run(cmd, log):
        seen.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        with open(out, "wb") as f:
            f.write(bytes.fromhex("daeeb336"))
            f.truncate(MIN_PLAUSIBLE_BYTES + 1)          # sparse: big enough to look like a model
        return 0, 6.5
    monkeypatch.setattr(cv, "run_logged", fake_run)
    d = _model_dir(tmp_path)
    code = cv.cmd_convert(str(d), "rk3588", out_dir=str(tmp_path / "out"), calibrate=False)
    text = capsys.readouterr().out
    assert code == 0, text
    assert "✓ wrote" in text and "m_rk3588_w8a8_rkllm-1.3.1.rkllm" in text and "librkllmrt 1.3.1 or later" in text
    assert seen[0][3] == "build" and "--dataset" not in seen[0]


def test_cmd_convert_failure_goes_through_explain(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("npuzoo.pc.collect_pc", lambda: _pc("1.1.4"))
    monkeypatch.setattr(cv, "HOME", str(tmp_path / "home"))

    def fake_run(cmd, log):
        with open(log, "a") as f:
            f.write("E rkllm: Not support Qwen3ForCausalLM model architecture.\n")
        return 1, None
    monkeypatch.setattr(cv, "run_logged", fake_run)
    d = _model_dir(tmp_path, arch="Qwen2ForCausalLM")
    assert cv.cmd_convert(str(d), "rk3588", out_dir=str(tmp_path / "out"), calibrate=False) == 1
    text = capsys.readouterr().out
    assert "conversion failed" in text and "Full log" in text


def test_cmd_convert_refuses_unknown_chip_and_missing_toolkit(monkeypatch, capsys):
    assert cv.cmd_convert("Qwen/Qwen3-0.6B", "rk9999") == 2
    monkeypatch.setattr("npuzoo.pc.collect_pc", lambda: dict(_pc(), toolkit=None))
    assert cv.cmd_convert("Qwen/Qwen3-0.6B", "rk3588") == 1
    assert "not installed" in capsys.readouterr().out


def test_run_logged_streams_and_keeps_progress_bars_out_of_the_log(tmp_path, capsys):
    log = tmp_path / "c.log"
    code, peak = cv.run_logged([sys.executable, "-c",
                                "print('PEAK_RSS_KB 2097152'); print('[===>   ] 1/2 (50%)'); print('hello')"],
                               str(log))
    assert code == 0 and peak == 2.0
    assert "hello" in capsys.readouterr().out
    assert log.read_text() == "hello\n"
