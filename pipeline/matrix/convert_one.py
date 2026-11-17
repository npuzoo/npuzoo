#!/usr/bin/env python3
"""Convert one Hugging Face model with the installed rkllm-toolkit, for several targets.

For every target it records whether the conversion worked, where it failed,
how long it took, peak memory, the output size and the output's signature.
Each target runs in its own child process, so a crash or an out-of-memory
kill becomes a recorded result instead of a lost job. The .rkllm files are
deleted after they are measured: the table is the product, not the files.

    python convert_one.py --model Qwen/Qwen3-0.6B \
        --targets rk3588:w8a8,rk3576:w8a8,rk3576:w4a16_g128 --out results/qwen3-0.6b.json

When the toolkit could not even be installed:

    python convert_one.py --model Qwen/Qwen3-0.6B --toolkit 1.1.4 \
        --install-log install.log --targets ... --out ...

Conversion only. Nothing here runs on a board.
"""
import argparse
import datetime
import hashlib
import inspect
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time

CORES = {"rk3588": 3, "rk3576": 2, "rk3562": 1, "rv1126b": 1}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PROGRESS = re.compile(r"^\s*\[[=> ]*\]\s*\d+/\d+")   # the toolkit's "[====>   ] 301/597 (50%)" bars
EXC = re.compile(r"^(?:[\w.]+\.)?(\w*(?:Error|Exception|Exit))\b:?\s*(.*)$")

# Calibration prompts: our own, neutral, half English and half Chinese, the
# mix of tasks the official example uses (QA, maths, code, translation).
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


# ------------------------------------------------------------ helpers

def ver(s):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def platform_args(toolkit, target, dtype):
    """Spell target and dtype the way that toolkit's own example does."""
    if ver(toolkit) >= (1, 2, 0):
        return target.upper(), dtype.upper()
    return target.lower(), dtype.lower()


def algorithm_for(toolkit, dtype):
    # The 1.2+ examples recommend 'grq' for w4a16; earlier releases had only 'normal'.
    if dtype.lower().startswith("w4a16") and ver(toolkit) >= (1, 2, 0):
        return "grq"
    return "normal"


def fit(fn, kwargs):
    """Only the keyword arguments this toolkit version's function accepts."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs, []
    params = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return kwargs, []
    keep = {k: v for k, v in kwargs.items() if k in params}
    return keep, sorted(set(kwargs) - set(keep))


def parse_child(text):
    """Stage reached, peak RSS (KB), ok flag, last exception line, tail."""
    clean = [ANSI.sub("", line).rstrip() for line in text.splitlines()]
    stage, peak, ok, err = None, None, False, None
    for line in clean:
        if line.startswith("STAGE "):
            stage = line.split(" ", 1)[1].strip()
        elif line.startswith("PEAK_RSS_KB "):
            try:
                peak = max(peak or 0, int(line.split()[1]))
            except ValueError:
                pass
        elif line.strip() == "RESULT ok":
            ok = True
        m = EXC.match(line.strip())
        if m and not line.startswith(("STAGE", "PEAK")):
            err = line.strip()
        elif line.startswith("RETURN "):
            err = "toolkit returned %s" % line.split(" ", 1)[1]
    tail = [line for line in clean if line.strip() and not line.startswith(("STAGE ", "PEAK_RSS_KB "))
            and not PROGRESS.match(line)][-30:]
    return {"stage": stage, "peak_kb": peak, "ok": ok, "error": err, "tail": tail}


def signature_of(path):
    with open(path, "rb") as f:
        head = f.read(4096)
    try:
        from npuzoo.inspect import sniff
        kind = sniff(head)
    except ImportError:
        kind = "rkllm" if head[:4] == bytes.fromhex("daeeb336") else "unknown"
    return kind, head[:8].hex()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------ child

def child(a):
    def peak():
        print("PEAK_RSS_KB %d" % resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, flush=True)

    print("STAGE import", flush=True)
    from rkllm.api import RKLLM
    llm = RKLLM()

    print("STAGE load", flush=True)
    kw, skipped = fit(llm.load_huggingface, dict(model=a.model_dir, model_lora=None, device="cpu",
                                                 dtype="float32", custom_config=None, load_weight=True))
    if skipped:
        print("note: this toolkit's load_huggingface has no %s" % ", ".join(skipped), flush=True)
    ret = llm.load_huggingface(**kw)
    peak()
    if ret != 0:
        print("RETURN %s from load_huggingface" % ret, flush=True)
        sys.exit(10)

    print("STAGE build", flush=True)
    target, dtype = platform_args(a.toolkit, a.target, a.dtype)
    kw, skipped = fit(llm.build, dict(
        do_quantization=True, optimization_level=1, quantized_dtype=dtype,
        quantized_algorithm=algorithm_for(a.toolkit, a.dtype), target_platform=target,
        num_npu_core=CORES[a.target.lower()], extra_qparams=None,
        dataset=a.dataset or None, hybrid_rate=0, max_context=4096))
    if skipped:
        print("note: this toolkit's build has no %s" % ", ".join(skipped), flush=True)
    ret = llm.build(**kw)
    peak()
    if ret != 0:
        print("RETURN %s from build" % ret, flush=True)
        sys.exit(11)

    print("STAGE export", flush=True)
    ret = llm.export_rkllm(a.export)
    peak()
    if ret != 0:
        print("RETURN %s from export_rkllm" % ret, flush=True)
        sys.exit(12)
    print("RESULT ok", flush=True)


# ------------------------------------------------------------ calibration

def calibrate(model_dir, out, max_new_tokens=48):
    """data_quant.json in the official format: chat-templated input + the model's own answer."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_dir, trust_remote_code=True, torch_dtype=torch.float32).eval()
    data = []
    for q in PROMPTS:
        try:
            text = tok.apply_chat_template([{"role": "user", "content": q}], tokenize=False, add_generation_prompt=True)
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
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return len(data)


# ------------------------------------------------------------ parent

def runner_facts():
    mem = None
    try:
        with open("/proc/meminfo") as f:
            mem = round(int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) / 1048576, 1)
    except Exception:
        pass
    facts = {"cpus": os.cpu_count(), "mem_gb": mem, "python": platform.python_version()}
    try:
        import torch
        facts["torch"] = torch.__version__
    except Exception:
        facts["torch"] = None
    return facts


def toolkit_version():
    try:
        from importlib.metadata import version
        return version("rkllm-toolkit")
    except Exception:
        return None


def last_error(text):
    lines = [ANSI.sub("", line).strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if EXC.match(line) or line.startswith("ERROR:"):
            return line
    return lines[-1] if lines else None


def install_failure(a, targets):
    text = open(a.install_log, encoding="utf-8", errors="replace").read() if os.path.exists(a.install_log) else ""
    err = last_error(text)
    tail = [ANSI.sub("", line).rstrip() for line in text.splitlines() if line.strip()][-30:]
    return [{"target": t, "dtype": d, "status": "fail", "stage": "install", "error": err, "log_tail": tail}
            for t, d in targets]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", help="Hugging Face repo id")
    ap.add_argument("--targets", default="rk3588:w8a8,rk3576:w8a8,rk3576:w4a16_g128")
    ap.add_argument("--out")
    ap.add_argument("--work", default="/tmp/npuzoo-convert")
    ap.add_argument("--toolkit", help="toolkit version (read from the install when present)")
    ap.add_argument("--install-log", help="record an install failure from this log instead of converting")
    ap.add_argument("--timeout", type=int, default=150 * 60, help="seconds per target")
    # child mode
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--model-dir", help=argparse.SUPPRESS)
    ap.add_argument("--target", help=argparse.SUPPRESS)
    ap.add_argument("--dtype", help=argparse.SUPPRESS)
    ap.add_argument("--dataset", help=argparse.SUPPRESS)
    ap.add_argument("--export", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.child:
        return child(a)

    targets = [tuple(t.split(":")) for t in a.targets.split(",") if t]
    record = {
        "model": a.model, "revision": None,
        "toolkit": toolkit_version() or a.toolkit,
        "date": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
        "runner": runner_facts(), "calibration": None, "results": [],
    }

    if a.install_log:
        record["results"] = install_failure(a, targets)
        return write(record, a.out)

    os.makedirs(a.work, exist_ok=True)
    model_dir = os.path.join(a.work, "model")
    try:
        from huggingface_hub import HfApi, snapshot_download
        record["revision"] = HfApi().model_info(a.model).sha
        snapshot_download(a.model, local_dir=model_dir, revision=record["revision"],
                          allow_patterns=["*.json", "*.safetensors", "*.py", "*.model", "*.txt", "*.tiktoken"])
    except Exception as e:
        record["results"] = [{"target": t, "dtype": d, "status": "fail", "stage": "download",
                              "error": "%s: %s" % (type(e).__name__, e)} for t, d in targets]
        return write(record, a.out)

    dataset = os.path.join(a.work, "data_quant.json")
    try:
        n = calibrate(model_dir, dataset)
        record["calibration"] = "%d prompts, answers generated by the model itself" % n
    except Exception as e:
        dataset = None
        record["calibration"] = "none (%s: %s)" % (type(e).__name__, str(e)[:200])

    for target, dtype in targets:
        export = os.path.join(a.work, "%s-%s.rkllm" % (target, dtype))
        cmd = [sys.executable, os.path.abspath(__file__), "--child", "--model-dir", model_dir,
               "--target", target, "--dtype", dtype, "--export", export, "--toolkit", record["toolkit"] or ""]
        if dataset:
            cmd += ["--dataset", dataset]
        print("== %s %s %s" % (a.model, target, dtype), flush=True)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors="replace", timeout=a.timeout)
            out, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as e:
            out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
            code = "timeout"
        seconds = round(time.time() - t0)
        sys.stdout.write(out[-20000:])
        info = parse_child(out)
        res = {"target": target, "dtype": dtype, "algorithm": algorithm_for(record["toolkit"], dtype),
               "seconds": seconds,
               "peak_rss_gb": round(info["peak_kb"] / 1048576, 2) if info["peak_kb"] else None}
        if info["ok"] and code == 0 and os.path.exists(export):
            kind, head = signature_of(export)
            res.update(status="ok", bytes=os.path.getsize(export), signature=kind, head=head,
                       sha256=sha256_of(export))
        else:
            if code == "timeout":
                stage, err = "timeout", "no result after %d minutes" % (a.timeout // 60)
            elif isinstance(code, int) and code < 0:
                stage, err = info["stage"], "killed by signal %d (likely out of memory)" % -code
            else:
                stage, err = info["stage"], info["error"]
            res.update(status="fail", stage=stage, error=err, log_tail=info["tail"])
        record["results"].append(res)
        if os.path.exists(export):
            os.remove(export)

    shutil.rmtree(model_dir, ignore_errors=True)
    return write(record, a.out)


def write(record, out):
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in record.items() if k != "results"}, ensure_ascii=False))
    for r in record["results"]:
        print("  %-7s %-11s %s%s" % (r["target"], r["dtype"], r["status"],
                                     "" if r["status"] == "ok" else " at %s: %s" % (r.get("stage"), r.get("error"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
