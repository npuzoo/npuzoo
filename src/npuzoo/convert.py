"""npuzoo convert — a Hugging Face model to a .rkllm file, on the x86 PC.

    npuzoo convert Qwen/Qwen3-1.7B --chip rk3588
    npuzoo convert ./my-finetune --chip rk3576 --dtype w4a16_g128

It does what the conversion matrix does on GitHub's CPU runners
(docs/conversion-matrix.md), for one model and one chip:

1. checks this machine the way `npuzoo doctor --pc` does, and whether the
   installed rkllm-toolkit knows the model's family (`npuzoo support`);
2. estimates peak memory from the model's size (about 3 GB plus 6.5 GB per
   billion parameters, measured in the matrix) and stops early if it will
   not fit;
3. downloads the model (or uses a local directory);
4. writes a small calibration set from eight neutral prompts, answered by
   the model itself, in the format of Rockchip's own example;
5. converts in a child process, spelling the chip, weight format and
   quantization algorithm the way that toolkit release expects, with the
   toolkit's output on screen and in a log;
6. checks the file it wrote, names it so `npuzoo inspect` and `find` can
   read its chip, format and toolkit version, and says what runtime the
   board needs.

If the conversion fails, the log goes through `npuzoo explain` straight away.
"""
import argparse
import datetime
import glob
import inspect as _inspect
import json
import os
import re
import resource
import subprocess
import sys
import threading
import time

HOME = os.path.expanduser(os.environ.get("NPUZOO_HOME", "~/.npuzoo"))

CHIPS = ("rk3588", "rk3588s", "rk3576", "rk3562", "rv1126b")
CORES = {"rk3588": 3, "rk3588s": 3, "rk3576": 2, "rk3562": 1, "rv1126b": 1}
DEFAULT_DTYPE = "w8a8"        # converts fastest on a CPU and works on every chip above

# Calibration prompts: our own, neutral, half English and half Chinese, the
# mix of tasks Rockchip's example uses (QA, maths, code, translation).
PROMPTS = [
    "What is the difference between a CPU, a GPU and an NPU? Answer in two sentences.",
    "请用三句话介绍一下长江。",
    "Write a Python function that returns the n-th Fibonacci number.",
    "一个水池有两个进水管，甲管单独注满需要 6 小时，乙管需要 3 小时。两管同时开，几小时注满？",
    "Translate into Chinese: The board has 16 GB of memory and an NPU with three cores.",
    "把这句话翻译成英文：今天下午三点在会议室开项目周会。",
    "List three things to check when a program runs out of memory.",
    "解释一下什么是量化，以及它为什么能让模型在小设备上运行。",
]

DOWNLOAD_PATTERNS = ["*.json", "*.safetensors", "*.py", "*.model", "*.txt", "*.tiktoken"]


# ------------------------------------------------------------ what each toolkit release expects

def ver(s):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def platform_args(toolkit, chip, dtype):
    """Chip and dtype spelled the way that release's own example spells them."""
    if ver(toolkit) >= (1, 2, 0):
        return chip.upper(), dtype.upper()
    return chip.lower(), dtype.lower()


def algorithm_for(toolkit, dtype):
    """1.2+ examples use 'grq' for w4a16; earlier releases only have 'normal'."""
    if dtype.lower().startswith("w4a16") and ver(toolkit) >= (1, 2, 0):
        return "grq"
    return "normal"


def fit(fn, kwargs):
    """Only the keyword arguments this release's function accepts, and the ones dropped."""
    try:
        sig = _inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs, []
    params = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return kwargs, []
    keep = {k: v for k, v in kwargs.items() if k in params}
    return keep, sorted(set(kwargs) - set(keep))


def output_name(model, chip, dtype, toolkit):
    """<model>_<chip>_<dtype>_rkllm-<toolkit>.rkllm: what inspect and find read back."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(model.rstrip("/"))).strip("-") or "model"
    return "%s_%s_%s_rkllm-%s.rkllm" % (base, chip.lower(), dtype.lower(), toolkit or "unknown")


# ------------------------------------------------------------ the model's size and family

def model_facts(model_dir):
    """Parameter count (billions, from the weight files) and architecture, from a local snapshot."""
    cfg = {}
    try:
        with open(os.path.join(model_dir, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    weights = sum(os.path.getsize(p) for p in glob.glob(os.path.join(model_dir, "**", "*.safetensors"),
                                                       recursive=True))
    width = {"float32": 4, "float16": 2, "bfloat16": 2}.get(str(cfg.get("torch_dtype") or "bfloat16"), 2)
    archs = cfg.get("architectures") or []
    return {"params_b": round(weights / width / 1e9, 2) if weights else None,
            "architecture": archs[0] if archs else None, "weights_bytes": weights}


def remote_facts(repo):
    """Same as model_facts, before downloading: sizes from the Hub's file list."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo, files_metadata=True)
    weights = sum((s.size or 0) for s in info.siblings or [] if s.rfilename.endswith(".safetensors"))
    cfg = getattr(info, "config", None) or {}
    archs = cfg.get("architectures") or []
    return {"params_b": round(weights / 2 / 1e9, 2) if weights else None,      # Hub weights are 16-bit, mostly
            "architecture": archs[0] if archs else None, "weights_bytes": weights, "revision": info.sha}


def swap_gb():
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"SwapTotal:\s+(\d+)", f.read())
        return round(int(m.group(1)) / 1048576, 1) if m else 0.0
    except OSError:
        return 0.0


# ------------------------------------------------------------ child steps (run in their own process)

def child_calibrate(model_dir, out, max_new_tokens=48):
    """data_quant.json in the official format: chat-templated input + the model's own answer."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True,
                                                 torch_dtype=torch.float32).eval()
    data = []
    for i, q in enumerate(PROMPTS, 1):
        try:
            text = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False,
                                           add_generation_prompt=True)
        except Exception:
            text = q
        try:
            ids = tok(text, return_tensors="pt")
            with torch.no_grad():
                out_ids = model.generate(**ids, max_new_tokens=max_new_tokens, do_sample=False)
            answer = tok.decode(out_ids[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        except Exception:
            answer = ""
        data.append({"input": text, "target": answer})
        print("calibration %d/%d" % (i, len(PROMPTS)), flush=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return 0


def child_build(model_dir, chip, dtype, toolkit, dataset, export, context):
    def peak():
        print("PEAK_RSS_KB %d" % resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, flush=True)

    print("STAGE import", flush=True)
    from rkllm.api import RKLLM
    llm = RKLLM()
    print("STAGE load", flush=True)
    kw, skipped = fit(llm.load_huggingface, dict(model=model_dir, model_lora=None, device="cpu",
                                                 dtype="float32", custom_config=None, load_weight=True))
    if skipped:
        print("note: this toolkit's load_huggingface has no %s" % ", ".join(skipped), flush=True)
    ret = llm.load_huggingface(**kw)
    peak()
    if ret != 0:
        print("RETURN %s from load_huggingface" % ret, flush=True)
        return 10
    print("STAGE build", flush=True)
    target, qdtype = platform_args(toolkit, chip, dtype)
    kw, skipped = fit(llm.build, dict(
        do_quantization=True, optimization_level=1, quantized_dtype=qdtype,
        quantized_algorithm=algorithm_for(toolkit, dtype), target_platform=target,
        num_npu_core=CORES[chip], extra_qparams=None, dataset=dataset or None, hybrid_rate=0,
        max_context=int(context)))
    if skipped:
        print("note: this toolkit's build has no %s" % ", ".join(skipped), flush=True)
    ret = llm.build(**kw)
    peak()
    if ret != 0:
        print("RETURN %s from build" % ret, flush=True)
        return 11
    print("STAGE export", flush=True)
    ret = llm.export_rkllm(export)
    peak()
    if ret != 0:
        print("RETURN %s from export_rkllm" % ret, flush=True)
        return 12
    print("RESULT ok", flush=True)
    return 0


def _child_main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["calibrate", "build"])
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out")
    ap.add_argument("--chip")
    ap.add_argument("--dtype")
    ap.add_argument("--toolkit")
    ap.add_argument("--dataset")
    ap.add_argument("--context", type=int, default=4096)
    a = ap.parse_args(argv)
    if a.step == "calibrate":
        return child_calibrate(a.model_dir, a.out)
    return child_build(a.model_dir, a.chip, a.dtype, a.toolkit, a.dataset, a.out, a.context)


# ------------------------------------------------------------ parent

_PROGRESS = re.compile(r"^\s*\[[=> ]*\]\s*\d+/\d+")


def run_logged(cmd, log, env=None):
    """Run cmd with its output on screen and appended to log; (returncode, peak RSS in GB)."""
    peak_kb = 0
    with open(log, "a", encoding="utf-8") as lf:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             errors="replace", bufsize=1, env=env)
        for line in p.stdout:
            if line.startswith("PEAK_RSS_KB "):
                try:
                    peak_kb = max(peak_kb, int(line.split()[1]))
                except ValueError:
                    pass
                continue
            sys.stdout.write(line)
            sys.stdout.flush()
            if not _PROGRESS.match(line):
                lf.write(line)
        code = p.wait()
    return code, round(peak_kb / 1048576, 1) if peak_kb else None


def preflight(info, facts, toolkit, family_since, out=sys.stdout):
    """Problems that will certainly stop a conversion, as (fatal, lines)."""
    from .pc import diagnose_pc, PC_FAIL, conversion_peak_gb
    lines, fatal = [], False
    for c in diagnose_pc(info):
        if c["status"] == PC_FAIL:
            fatal = True
            lines.append("✗ %s: %s" % (c["name"], c["detail"]) + (("\n   ↳ fix: %s" % c["fix"]) if c.get("fix") else ""))
    if family_since and toolkit and ver(toolkit) < ver(family_since):
        fatal = True
        lines.append("✗ model family: rkllm-toolkit %s cannot convert this model; support was added in %s.\n"
                     "   ↳ fix: install rkllm-toolkit %s or later (see `npuzoo support`)."
                     % (toolkit, family_since, family_since))
    if facts.get("params_b") and info.get("mem_gb"):
        need = conversion_peak_gb(facts["params_b"])
        have = info["mem_gb"] + swap_gb()
        if need > have:
            fatal = True
            lines.append("✗ memory: about %.0f GB needed at the peak for %.1fB parameters; this machine has "
                         "%.0f GB of memory and swap.\n   ↳ fix: add swap, or use a machine with more memory."
                         % (need, facts["params_b"], have))
        elif need > info["mem_gb"]:
            lines.append("! memory: about %.0f GB needed; %.0f GB of memory, so it will use swap and be slow."
                         % (need, info["mem_gb"]))
    return fatal, lines


def cmd_convert(model, chip, dtype=None, out_dir=".", context=4096, calibrate=True, force=False,
                work=None):
    from .pc import collect_pc
    from .models import family_for_name, family_for_arch
    chip = chip.lower()
    if chip not in CHIPS:
        print("✗ --chip must be one of: %s" % ", ".join(CHIPS))
        return 2
    dtype = (dtype or DEFAULT_DTYPE).lower()
    info = collect_pc()
    toolkit = info.get("toolkit")
    if not toolkit:
        print("✗ rkllm-toolkit is not installed in this Python.")
        print("   ↳ fix: see `npuzoo doctor --pc`; the wheel is in airockchip/rknn-llm under rkllm-toolkit/packages.")
        return 1

    local = os.path.isdir(model)
    try:
        if local:
            facts = model_facts(model)
        else:
            facts = remote_facts(model)
    except Exception as e:
        print("✗ cannot read %s: %s: %s" % (model, type(e).__name__, e))
        return 1
    fam = (family_for_arch(facts["architecture"]) if facts.get("architecture") else None) or family_for_name(model)
    print("Converting %s for %s (%s) with rkllm-toolkit %s" % (model, chip.upper(), dtype, toolkit))
    if facts.get("params_b"):
        print("   about %.1fB parameters%s" % (facts["params_b"],
                                               (", %s" % facts["architecture"]) if facts.get("architecture") else ""))
    fatal, lines = preflight(info, facts, toolkit, fam["since"] if fam else None)
    for line in lines:
        print(line)
    if fatal and not force:
        print("Stopped before converting (use --force to try anyway).")
        return 1

    work = work or os.path.join(HOME, "convert")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = os.path.join(HOME, "logs", "convert-%s.log" % stamp)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    if local:
        model_dir = os.path.abspath(model)
    else:
        from huggingface_hub import snapshot_download
        model_dir = os.path.join(work, "hf", model.replace("/", "--"))
        print("Downloading %s ..." % model)
        snapshot_download(model, local_dir=model_dir, revision=facts.get("revision"),
                          allow_patterns=DOWNLOAD_PATTERNS)

    me = [sys.executable, "-m", "npuzoo.convert"]
    dataset = None
    t0 = time.time()
    if calibrate:
        dataset = os.path.join(work, "data_quant-%s.json" % stamp)
        print("Writing a calibration set (the model answers %d prompts) ..." % len(PROMPTS))
        code, _ = run_logged(me + ["calibrate", "--model-dir", model_dir, "--out", dataset], log)
        if code != 0 or not os.path.exists(dataset):
            print("! calibration failed; converting without a dataset (quality may be lower).")
            dataset = None

    export = os.path.join(out_dir, output_name(model, chip, dtype, toolkit))
    print("Converting (the toolkit's own output follows) ...")
    cmd = me + ["build", "--model-dir", model_dir, "--out", export, "--chip", chip, "--dtype", dtype,
                "--toolkit", toolkit, "--context", str(context)]
    if dataset:
        cmd += ["--dataset", dataset]
    code, peak = run_logged(cmd, log)
    minutes = (time.time() - t0) / 60
    if code != 0 or not os.path.exists(export):
        if code is not None and code < 0:
            print("\n✗ the conversion was killed (signal %d), most likely for running out of memory." % -code)
        else:
            print("\n✗ the conversion failed. What the log says:\n")
        from .explain import cmd_explain
        cmd_explain(log)
        print("\nFull log: %s" % log)
        return 1

    from .inspect import inspect_file, FAIL
    findings = inspect_file(export)
    bad = [f for f in findings if f.get("status") == FAIL]
    size = os.path.getsize(export) / 1e9
    print("\n✓ wrote %s  (%.2f GB, %.0f min%s)" % (export, size, minutes,
                                                   ", peak %.1f GB" % peak if peak else ""))
    if bad:
        for f in bad:
            print("✗ %s: %s" % (f.get("check"), f.get("detail")))
        return 1
    print("   The board needs librkllmrt %s or later; the same version is safest (`npuzoo doctor` shows yours)."
          % toolkit)
    print("   On the board:  npuzoo run %s" % os.path.basename(export))
    return 0


if __name__ == "__main__":
    sys.exit(_child_main(sys.argv[1:]))
