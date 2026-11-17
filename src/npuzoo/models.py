"""Which model families and chips each RKLLM release supports.

Source: airockchip/rknn-llm CHANGELOG.md and README.md at release-v1.3.1
(2026-09-29). "since" is the first release whose changelog names the family
or platform. None means the README lists it as supported but no changelog
entry says when it arrived.

Toolkit and runtime ship together, so a family needs both: a toolkit that
can convert it and a runtime on the board that can run it, of that release
or newer.
"""
import re

SOURCE = "https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/CHANGELOG.md"
CHANGELOG_URL = SOURCE   # the name explain.py imports (the standalone bundle cannot rename imports)

# (key, display name, since, pattern for repo/file names, architecture keys)
# Order matters: the first pattern that matches a name wins, so the more
# specific names (qwen3.5, qwen3-vl) come before the general ones (qwen3).
# Architecture keys are config.json class names, lowercased, with
# ForCausalLM / ForConditionalGeneration / LMHeadModel / Model and
# non-alphanumerics removed: Qwen2_5_VLForConditionalGeneration -> qwen25vl.
FAMILIES = [
    ("qwen3.5", "Qwen3.5", "1.3.0", r"qwen[-_ ]?3[._]5(?!\d)", ["qwen35"]),
    ("qwen3-vl", "Qwen3-VL", "1.2.3", r"qwen[-_ ]?3[-_ ]?vl", ["qwen3vl"]),
    ("qwen2.5-vl", "Qwen2.5-VL", "1.2.0", r"qwen[-_ ]?2[._]5[-_ ]?vl", ["qwen25vl"]),
    ("qwen2-vl", "Qwen2-VL", None, r"qwen[-_ ]?2[-_ ]?vl", ["qwen2vl"]),
    ("qwen3", "Qwen3", "1.2.1", r"qwen[-_ ]?3(?![._]?\d)", ["qwen3"]),
    ("qwen2", "Qwen2 / Qwen2.5", "1.0.0", r"qwen[-_ ]?2", ["qwen2"]),
    ("qwen", "Qwen", "1.0.0", r"qwen", ["qwen"]),
    ("gemma4", "Gemma 4", "1.3.0", r"gemma[-_ ]?4", ["gemma4"]),
    ("gemma3n", "Gemma 3n", "1.2.2", r"gemma[-_ ]?3n", ["gemma3n"]),
    ("gemma3", "Gemma 3", "1.2.0", r"gemma[-_ ]?3", ["gemma3", "gemma3text"]),
    ("gemma2", "Gemma 2", "1.1.0", r"gemma[-_ ]?2", ["gemma2"]),
    ("gemma", "Gemma", "1.0.1", r"gemma", ["gemma"]),
    ("smollm3", "SmolLM3", "1.3.0", r"smollm[-_ ]?3", ["smollm3"]),
    ("smolvlm", "SmolVLM", None, r"smolvlm", []),
    ("internvl3.5", "InternVL3.5", "1.2.3", r"internvl[-_ ]?3[._]5", []),
    ("internvl3", "InternVL3", "1.2.2", r"internvl[-_ ]?3", []),
    ("internvl2", "InternVL2", "1.2.0", r"internvl[-_ ]?2", ["internvlchat"]),
    ("internlm2", "InternLM2", "1.0.1", r"internlm[-_ ]?2", ["internlm2"]),
    ("minicpm-v", "MiniCPM-V", None, r"minicpm[-_ ]?v", ["minicpmv"]),
    ("minicpm4", "MiniCPM4", "1.2.1", r"minicpm[-_ ]?4", []),
    ("minicpm3", "MiniCPM3", "1.1.0", r"minicpm[-_ ]?3", ["minicpm3"]),
    ("minicpm", "MiniCPM", "1.0.1", r"minicpm", ["minicpm"]),
    ("phi3", "Phi-3", "1.0.1", r"phi[-_ ]?3", ["phi3"]),
    ("phi2", "Phi-2", "1.0.0", r"phi[-_ ]?2", ["phi"]),
    ("chatglm3", "ChatGLM3", "1.0.1", r"chatglm[-_ ]?3", ["chatglm"]),
    ("telechat2", "TeleChat2", None, r"telechat[-_ ]?2", ["telechat2"]),
    ("rwkv7", "RWKV7", "1.2.1", r"rwkv[-_ ]?7", ["rwkv7"]),
    ("janus", "Janus", "1.2.0", r"janus", []),
    ("deepseek-ocr", "DeepSeek-OCR", "1.2.3", r"deepseek[-_ ]?ocr", ["deepseekocr"]),
    ("lfm2.5-vl", "LFM2.5-VL", "1.3.1", r"lfm[-_ ]?2[._]5[-_ ]?vl", []),
    ("spark-x2.5", "Spark-X2.5", "1.3.1", r"spark[-_ ]?x[-_ ]?2[._]5", []),
    ("llama3", "Llama 3", "1.1.0", r"(?<!o)llama[-_ ]?3", []),
    ("llama", "Llama / TinyLlama", "1.0.0", r"(?<!o)llama", ["llama"]),   # not "ollama"
]

PLATFORMS = {"rk3588": "1.0.0", "rk3588s": "1.0.0", "rk3576": "1.0.0",
             "rk3562": "1.2.0", "rv1126b": "1.2.1"}

FEATURES = {
    "group-wise quantization (w4a16_g32/64/128, w8a8_g128/256/512)": "1.1.0",
    "GGUF conversion (q4_0, fp16)": "1.1.0",
    "GRQ int4 quantization": "1.2.0",
    "16K context": "1.2.0",
    "chat_template configuration": "1.2.0",
    "function calling": "1.2.1",
    "multiple EOS tokens": "1.3.0",
}

_SUFFIX = re.compile(r"(forcausallm|forconditionalgeneration|lmheadmodel|model)$")
_COMPILED = [(k, d, s, re.compile(p), a) for k, d, s, p, a in FAMILIES]


def _row(t):
    k, d, s, _p, a = t
    return {"key": k, "name": d, "since": s, "archs": a}


def family_for_name(name):
    """Family a repo or file name points to, or None. A guess from the name."""
    low = (name or "").lower()
    for t in _COMPILED:
        if t[3].search(low):
            return _row(t)
    return None


def arch_key(arch):
    key = re.sub(r"[^a-z0-9]", "", (arch or "").lower())
    return _SUFFIX.sub("", key)


def family_for_arch(arch):
    """Family for a config.json architecture class, e.g. Qwen3ForCausalLM."""
    key = arch_key(arch)
    for t in _COMPILED:
        if key in t[4]:
            return _row(t)
    return None


def ver(s):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


def supports(version, since):
    """True / False, or None when either side is unknown."""
    a, b = ver(version), ver(since)
    if a is None or b is None:
        return None
    return a >= b


def cmd_support(query=None):
    """Print the table, or the rows matching a model or chip name."""
    rows = [_row(t) for t in _COMPILED]
    q = (query or "").lower().strip()
    if q:
        if q in PLATFORMS:
            print("%s: RKLLM toolkit and runtime %s or newer." % (q.upper(), PLATFORMS[q]))
            return 0
        fam = family_for_name(q) or family_for_arch(q)
        if not fam:
            print("No RKLLM release names '%s'. Check the list: npuzoo support" % query)
            return 1
        rows = [fam]
    print("%-20s %s" % ("MODEL FAMILY", "TOOLKIT AND RUNTIME"))
    for r in rows:
        print("%-20s %s" % (r["name"], (r["since"] + " or newer") if r["since"]
                            else "listed in 1.3.1 (first release not stated)"))
    if not q:
        print("\n%-20s %s" % ("CHIP", "TOOLKIT AND RUNTIME"))
        for chip, since in PLATFORMS.items():
            print("%-20s %s or newer" % (chip.upper(), since))
    print("\nSource: Rockchip's changelog, %s" % SOURCE)
    return 0
