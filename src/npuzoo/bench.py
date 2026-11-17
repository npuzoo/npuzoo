"""npuzoo bench — the same few runs on every board, reported the same way.

Two workloads: a short prompt with a long answer (generation speed, what a
chat feels like) and a long prompt with a short answer (prefill speed, what
retrieval and long context feel like). Each runs once to warm up and then
REPEATS times; the median is reported. Numbers are the runtime's own
counters (RKLLMPerfStat), with the clock governors recorded next to them,
because vendor figures are measured with clocks pinned and yours may not be.

The JSON it writes is meant to be shared: paste it into the benchmark issue
form so the next person with the same board sees real numbers.
"""
import hashlib
import json
import os
import platform
import statistics
import sys
import time

from . import __version__
from .rkllm_rt import tokens_per_second, RuntimeError_
from .runner import open_session, SetupError

SHORT = "Write a detailed story about a lighthouse keeper who finds a message in a bottle."
# about 500 tokens of neutral text, the same on every run
LONG_UNIT = ("The NPU on a single-board computer runs quantized neural networks with far less power than "
             "the CPU. Converting a model means choosing a weight format, calibrating, and matching the "
             "toolkit to the runtime on the board. ")
LONG = LONG_UNIT * 12 + "Summarise the text above in one sentence."

WORKLOADS = [
    {"name": "chat", "prompt": SHORT, "max_new_tokens": 128},
    {"name": "long-prompt", "prompt": LONG, "max_new_tokens": 16},
]


def file_digest(path, chunk=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def summarise(perfs):
    """Median prefill / generate tok/s and peak memory over several runs."""
    rates = [tokens_per_second(p) for p in perfs if p]
    pre = [r[0] for r in rates if r[0]]
    gen = [r[1] for r in rates if r[1]]
    mem = [p["memory_mb"] for p in perfs if p and p.get("memory_mb")]
    return {
        "runs": len(perfs),
        "prefill_tps": round(statistics.median(pre), 2) if pre else None,
        "generate_tps": round(statistics.median(gen), 2) if gen else None,
        "prefill_tokens": perfs[-1]["prefill_tokens"] if perfs and perfs[-1] else None,
        "generate_tokens": perfs[-1]["generate_tokens"] if perfs and perfs[-1] else None,
        "memory_mb": max(mem) if mem else None,
    }


def run_workloads(session, repeats=3, out=sys.stdout):
    results = {}
    for w in WORKLOADS:
        perfs = []
        for i in range(repeats + 1):            # the first run warms up and is not counted
            res = session.generate(w["prompt"], max_new_tokens=w["max_new_tokens"])
            if i:
                perfs.append(res["perf"])
            out.write(".")
            out.flush()
        results[w["name"]] = summarise(perfs)
    out.write("\n")
    return results


def report(meta, results, model_path, digest):
    return {
        "npuzoo": __version__,
        "date": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
        "board": meta.get("board"), "chip": meta.get("chip"), "kernel": meta.get("kernel"),
        "npu_driver": meta.get("npu_driver"), "runtime": meta.get("runtime"), "mem_gb": meta.get("mem_gb"),
        "cpu_governor": meta.get("governor"), "npu_governor": meta.get("npu_governor"),
        "model": {"file": os.path.basename(model_path), "bytes": os.path.getsize(model_path), "sha256": digest},
        "load_s": meta.get("load_s"),
        "workloads": results,
        "python": platform.python_version(),
    }


def cmd_bench(model, repeats=3, lib_path=None, force=False, context=4096, out_path=None):
    try:
        session, meta = open_session(model, lib_path, force, context, max_new_tokens=128, temperature=0.8,
                                     ignore_eos=True)
    except (SetupError, RuntimeError_, OSError) as e:
        print("✗ %s" % e)
        return 1
    try:
        print("Benchmarking (%d runs per workload after one warm-up) " % repeats, end="")
        results = run_workloads(session, repeats)
    except RuntimeError_ as e:
        print("\n✗ %s" % e)
        return 1
    finally:
        session.close()
    rep = report(meta, results, meta["model"], file_digest(meta["model"]))
    print("\n%-12s %14s %14s %10s" % ("WORKLOAD", "PREFILL tok/s", "GENERATE tok/s", "MEMORY"))
    for name, r in results.items():
        print("%-12s %14s %14s %8s MB" % (name, r["prefill_tps"], r["generate_tps"], r["memory_mb"]))
    gov = meta.get("governor") or "?"
    if "performance" not in gov:
        print("\nClocks are not pinned (CPU governor %s): these are everyday numbers. Rockchip's published"
              " figures are measured after its fix_freq script; run it to compare like with like." % gov)
    out_path = out_path or "npuzoo-bench-%s-%s-%s.json" % (
        os.path.splitext(rep["model"]["file"])[0], rep["chip"] or "unknown", rep["runtime"] or "unknown")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("\nSaved %s — please share it: https://github.com/npuzoo/npuzoo/issues/new?template=benchmark.yml"
          % out_path)
    return 0
