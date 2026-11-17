"""Model-family support by RKLLM release, from Rockchip's changelog."""
import pytest

from npuzoo.models import family_for_name, family_for_arch, arch_key, supports, cmd_support
from npuzoo.inspect import check_claims, parse_name
from npuzoo.community import judge, NO, MAYBE, YES
from npuzoo.explain import arch_note


@pytest.mark.parametrize("name,key", [
    ("Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm", "qwen3"),
    ("Qwen3.5-2B_w8a8_rk3588.rkllm", "qwen3.5"),
    ("qwen3-vl-2b-instruct_w8a8_rk3588.rkllm", "qwen3-vl"),
    ("Qwen2.5-VL-3B", "qwen2.5-vl"),
    ("Qwen2.5-1.5B-Instruct", "qwen2"),
    ("gemma-3n-E2B-it", "gemma3n"),
    ("gemma-3-1b-it", "gemma3"),
    ("gemma-4-E2B-it_fp16_rk3588.rkllm", "gemma4"),
    ("Llama-3.2-1B-Instruct", "llama3"),
    ("TinyLlama-1.1B-Chat-v1.0", "llama"),
    ("SmolLM3-3B", "smollm3"),
    ("internvl3-1b_w8a8_rk3588", "internvl3"),
    ("MiniCPM4-0.5B", "minicpm4"),
    ("DeepSeek-OCR", "deepseek-ocr"),
])
def test_family_from_names(name, key):
    assert family_for_name(name)["key"] == key


def test_no_family_for_unknown_names():
    assert family_for_name("model.rkllm") is None
    assert family_for_name("my-ollama-bundle") is None     # "ollama" is not Llama


@pytest.mark.parametrize("arch,key", [
    ("Qwen3ForCausalLM", "qwen3"),
    ("Qwen2_5_VLForConditionalGeneration", "qwen2.5-vl"),
    ("QWenLMHeadModel", "qwen"),
    ("ChatGLMModel", "chatglm3"),
    ("Gemma3nForConditionalGeneration", "gemma3n"),
    ("PhiForCausalLM", "phi2"),
])
def test_family_from_architecture(arch, key):
    assert family_for_arch(arch)["key"] == key


def test_arch_key():
    assert arch_key("Qwen2_5_VLForConditionalGeneration") == "qwen25vl"
    assert family_for_arch("GPTNeoForCausalLM") is None


def test_supports():
    assert supports("1.1.4", "1.2.1") is False
    assert supports("1.2.1b1", "1.2.1") is True
    assert supports(None, "1.2.1") is None


def test_qwen3_on_an_old_runtime_fails():
    found = check_claims(parse_name("Qwen3-1.7B-rk3588-w8a8.rkllm"), board="rk3588", runtime="1.1.4",
                         family=family_for_name("Qwen3-1.7B"))
    assert any(f["status"] == "FAIL" and "1.2.1" in f["detail"] for f in found)


def test_impossible_toolkit_claim_is_flagged():
    found = check_claims(parse_name("Qwen3-1.7B-rk3588-w8a8-1.1.4.rkllm"), family=family_for_name("Qwen3"))
    assert any(f["status"] == "WARN" and "probably wrong" in f["detail"] for f in found)


def test_rk3562_needs_runtime_120():
    found = check_claims(parse_name("x-rk3562-w8a8.rkllm"), board="rk3562", runtime="1.1.4")
    assert any(f["check"] == "board" and f["status"] == "FAIL" for f in found)


def test_find_uses_the_family():
    e = {"repo": "a/Qwen3-1.7B-NPU", "path": "model-rk3588-w8a8.rkllm", "gated": False}
    assert judge(e, "rk3588", "1.1.4")[0] == NO
    assert judge(e, "rk3588", "1.2.1")[0] == MAYBE      # toolkit not in the name


def test_find_uses_base_model_when_names_say_nothing():
    e = {"repo": "a/npu-pack", "path": "m-rk3588-w8a8-1.2.1.rkllm", "base_model": "Qwen/Qwen3-1.7B", "gated": False}
    assert judge(e, "rk3588", "1.1.4")[0] == NO
    assert judge(e, "rk3588", "1.2.1")[0] == YES


def test_explain_names_the_release():
    note = " ".join(arch_note("ERROR: Not support Qwen3ForCausalLM!\n"))
    assert "Qwen3" in note and "1.2.1" in note
    assert "not in RKLLM's supported list" in " ".join(arch_note("ERROR: Not support GPTNeoForCausalLM!"))
    assert arch_note("nothing here") == []


def test_support_command(capsys):
    assert cmd_support("qwen3") == 0
    assert "1.2.1 or newer" in capsys.readouterr().out
    assert cmd_support("rk3562") == 0
    assert "1.2.0" in capsys.readouterr().out
    assert cmd_support("gpt-neo") == 1
    assert cmd_support() == 0
    out = capsys.readouterr().out
    assert "Gemma 4" in out and "RV1126B" in out


def test_compatibility_doc_matches_the_data():
    import pathlib
    from npuzoo.models import FAMILIES
    doc = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "compatibility.md").read_text()
    for _k, name, since, _p, _a in FAMILIES:
        assert "| %s | %s |" % (name, since or "listed in 1.3.1; first release not stated") in doc, name
