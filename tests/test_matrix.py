"""Conversion-matrix helpers, tested without rkllm-toolkit or a network."""
import importlib.util
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "pipeline" / "matrix" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conv = _load("convert_one")
coll = _load("collect")
inst = _load("install_toolkit")


# ------------------------------------------------------------ install plan

def _wheel(tmp_path, reqs):
    p = tmp_path / "rkllm_toolkit-1.3.1-cp310-cp310-linux_x86_64.whl"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("rkllm_toolkit-1.3.1.dist-info/METADATA",
                   "Metadata-Version: 2.2\nName: rkllm-toolkit\n" + "".join("Requires-Dist: %s\n" % r for r in reqs))
    return str(p)


def test_install_plan_pins_torch_family_and_gptq(tmp_path):
    whl = _wheel(tmp_path, ["numpy<=1.26.4,>=1.23.1", "torch==2.6.0", "torchvision==0.21.0",
                            "auto_gptq==0.7.1", "transformers==5.8.0"])
    torch, gptq = inst.plan(inst.requirements(whl))
    assert torch == ["torch==2.6.0", "torchvision==0.21.0"]
    assert gptq == "auto_gptq==0.7.1"


def test_install_plan_without_gptq(tmp_path):
    torch, gptq = inst.plan(inst.requirements(_wheel(tmp_path, ["torch==2.1.0"])))
    assert torch == ["torch==2.1.0"] and gptq is None


# ------------------------------------------------------------ convert helpers

def test_platform_args_follow_each_release_example():
    assert conv.platform_args("1.3.1", "rk3588", "w8a8") == ("RK3588", "W8A8")
    assert conv.platform_args("1.1.4", "rk3576", "w4a16_g128") == ("rk3576", "w4a16_g128")


def test_algorithm():
    assert conv.algorithm_for("1.3.1", "w4a16_g128") == "grq"
    assert conv.algorithm_for("1.1.4", "w4a16") == "normal"
    assert conv.algorithm_for("1.3.1", "w8a8") == "normal"


def test_fit_drops_unknown_kwargs():
    def old_build(do_quantization=True, quantized_dtype="w8a8", target_platform="rk3588"):
        pass
    kw, skipped = conv.fit(old_build, {"do_quantization": True, "quantized_dtype": "w8a8", "max_context": 4096})
    assert kw == {"do_quantization": True, "quantized_dtype": "w8a8"} and skipped == ["max_context"]


def test_fit_passes_all_to_kwargs_functions():
    def new_build(**kwargs):
        pass
    kw, skipped = conv.fit(new_build, {"a": 1, "b": 2})
    assert kw == {"a": 1, "b": 2} and skipped == []


def test_parse_child_success():
    out = "STAGE import\nSTAGE load\nPEAK_RSS_KB 1000\nSTAGE build\nPEAK_RSS_KB 7340032\nSTAGE export\nRESULT ok\n"
    info = conv.parse_child(out)
    assert info["ok"] and info["stage"] == "export" and info["peak_kb"] == 7340032


def test_parse_child_failure_keeps_stage_and_exception():
    out = ("STAGE import\nSTAGE load\nPEAK_RSS_KB 1000\nSTAGE build\n"
           "Traceback (most recent call last):\n  File \"x.py\", line 1\n"
           "\x1b[31mValueError: Unsupported model architecture: Foo\x1b[0m\n")
    info = conv.parse_child(out)
    assert not info["ok"] and info["stage"] == "build"
    assert info["error"] == "ValueError: Unsupported model architecture: Foo"


def test_parse_child_return_code():
    info = conv.parse_child("STAGE load\nRETURN -1 from load_huggingface\n")
    assert info["stage"] == "load" and "returned -1" in info["error"]


def test_install_failure_record(tmp_path):
    log = tmp_path / "install.log"
    log.write_text("Collecting torch==2.1.0\nERROR: No matching distribution found for torch==2.1.0\n")

    class A:
        install_log = str(log)
    rows = conv.install_failure(A, [("rk3588", "w8a8")])
    assert rows[0]["stage"] == "install" and "No matching distribution" in rows[0]["error"]


def test_main_install_failure_writes_json(tmp_path):
    log = tmp_path / "install.log"
    log.write_text("ERROR: boom\n")
    out = tmp_path / "r.json"
    conv.main(["--model", "Qwen/Qwen3-0.6B", "--toolkit", "1.1.4", "--install-log", str(log),
               "--targets", "rk3588:w8a8,rk3576:w4a16", "--out", str(out)])
    r = json.loads(out.read_text())
    assert r["toolkit"] in ("1.1.4",) and [x["stage"] for x in r["results"]] == ["install", "install"]


# ------------------------------------------------------------ collect

def _rec(model, tk, results):
    return {"model": model, "toolkit": tk, "date": "2026-11-17T20:00Z",
            "runner": {"cpus": 4, "mem_gb": 15.6, "python": "3.10.18", "torch": "2.6.0+cpu"},
            "results": results}


def test_collect_renders_table_and_failures(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    (d / "a.json").write_text(json.dumps(_rec("Qwen/Qwen3-0.6B", "1.3.1", [
        {"target": "rk3588", "dtype": "w8a8", "status": "ok", "bytes": 912_000_000, "seconds": 410,
         "peak_rss_gb": 6.2, "signature": "rkllm"},
        {"target": "rk3576", "dtype": "w4a16_g128", "status": "fail", "stage": "build",
         "error": "RuntimeError: out | of memory"}])))
    (d / "b.json").write_text(json.dumps(_rec("Qwen/Qwen3-0.6B", "1.1.4", [
        {"target": "rk3588", "dtype": "w8a8", "status": "fail", "stage": "install", "error": "ERROR: x"}])))
    (d / "junk.json").write_text("[]")
    js, md = tmp_path / "m.json", tmp_path / "m.md"
    assert coll.main([str(d), "--json", str(js), "--md", str(md)]) == 0
    text = md.read_text()
    assert "| Qwen/Qwen3-0.6B | 1.3.1 | ✓ 0.91 GB · 7 min · 6.2 GB RAM | ✗ build |" in text
    assert text.index("| 1.3.1 |") < text.index("| 1.1.4 |")          # newest toolkit first
    assert "out \\| of memory" in text                                  # pipes escaped
    assert "1 of 3 conversions produced a file" in text
    assert len(json.loads(js.read_text())["records"]) == 2


def test_collect_flags_wrong_signature():
    assert "unexpected file signature: unknown" in coll.cell(
        {"status": "ok", "bytes": 1, "seconds": 60, "signature": "unknown"})


def test_collect_nothing(tmp_path):
    assert coll.main([str(tmp_path), "--json", str(tmp_path / "j"), "--md", str(tmp_path / "m")]) == 1
