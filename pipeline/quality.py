#!/usr/bin/env python3
"""Measure what quantization costs you, not just whether the model runs.

Everyone in this ecosystem answers "does it run". Nobody publishes what the
output is worth afterwards. Two live examples from the rkllama tracker: a model
that emits garbage on one runtime version, and a w8a8_g128 conversion that stops
generating after 2-13 tokens. Both load fine. Both are useless.

This produces, for one model across several quantization configs:

  dtype          ppl     d_ppl    tok/s   early_stop   repeat   first_fail
  w8a8          11.42    +4.1%     6.2       0/40       0.01    -
  w8a8_g128     10.98    +0.1%     5.8       0/40       0.01    -
  w8a8_g256     11.10    +1.2%     6.0       3/40       0.04    tok 13

Run it on the board. It needs the model converted at each dtype first
(pipeline/convert_rkllm.py on an x86 host), and a reference ppl from the
unquantized model on any machine with enough RAM.

Status: harness only. No numbers in this repo are from this script yet — the
first run happens when hardware lands. Anything published from it will say which
board, which runtime, which driver, and at which clocks.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time

# Deterministic, boring prompts. The point is comparability across dtypes, not
# interesting output, so these stay fixed forever once published.
PROMPTS = [
    "List the first ten prime numbers, separated by commas.",
    "Translate to French: The library closes at six on weekdays.",
    "What is 17 multiplied by 23? Answer with the number only.",
    "Summarise in one sentence: water expands when it freezes.",
    "Complete the sequence: 2, 4, 8, 16,",
]

REPEAT_WINDOW = 12          # n-gram window for loop detection
MIN_TOKENS_OK = 16          # fewer than this on these prompts means early stop


def repetition_score(text):
    """Fraction of trailing text that is a repeated n-gram. 0 is clean, 1 is a loop."""
    toks = text.split()
    if len(toks) < REPEAT_WINDOW * 2:
        return 0.0
    tail = toks[-REPEAT_WINDOW:]
    hits = sum(1 for i in range(len(toks) - REPEAT_WINDOW)
               if toks[i:i + REPEAT_WINDOW] == tail)
    return min(1.0, (hits - 1) / max(1, len(toks) / REPEAT_WINDOW))


def perplexity(nll_sum, n_tokens):
    if not n_tokens:
        return None
    return math.exp(nll_sum / n_tokens)


def run_one(binary, model, prompt, max_tokens, logits=False):
    """Invoke the board-side demo and parse what it prints.

    The runtime exposes per-token logits for single-batch inference (it refuses
    only for multi-batch), so a real ppl is obtainable — but the exact flag
    depends on which demo binary you build. Left as a parameter rather than
    guessed: fill in `--logits` for your build, or run without it and rely on
    the behavioural metrics, which need no logits at all.
    """
    cmd = [binary, model, prompt, str(max_tokens)] + (["--logits"] if logits else [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        sys.exit("not found: %s — build the RKLLM demo first, or pass --binary" % binary)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "elapsed": time.time() - t0}
    elapsed = time.time() - t0
    out = p.stdout

    # tokens/s as the runtime reports it, if it does
    m = re.search(r"([\d.]+)\s*tokens?/s", out, re.I)
    tps = float(m.group(1)) if m else None

    nll = re.findall(r"nll[=:\s]+(-?[\d.]+)", out, re.I)
    ntok = len(re.findall(r"\btoken\b", out, re.I)) or None
    text = out

    return {
        "text": text,
        "elapsed": elapsed,
        "tokens_per_s": tps,
        "nll_sum": sum(float(x) for x in nll) if nll else None,
        "n_tokens": len(nll) if nll else ntok,
        "returncode": p.returncode,
        "stderr_tail": p.stderr[-400:] if p.returncode else "",
    }


def measure(binary, model, dtype, max_tokens, logits):
    rows, early, reps, nll_sum, n_tok, tps = [], 0, [], 0.0, 0, []
    first_fail = None
    for i, prompt in enumerate(PROMPTS):
        r = run_one(binary, model, prompt, max_tokens, logits)
        if r.get("error"):
            first_fail = first_fail or "prompt %d: %s" % (i, r["error"])
            rows.append(r)
            continue
        produced = len((r["text"] or "").split())
        if produced < MIN_TOKENS_OK:
            early += 1
            first_fail = first_fail or "prompt %d stopped at ~%d tokens" % (i, produced)
        reps.append(repetition_score(r["text"] or ""))
        if r["nll_sum"] is not None and r["n_tokens"]:
            nll_sum += r["nll_sum"]
            n_tok += r["n_tokens"]
        if r["tokens_per_s"]:
            tps.append(r["tokens_per_s"])
        rows.append(r)

    return {
        "dtype": dtype,
        "model": os.path.basename(model),
        "ppl": perplexity(nll_sum, n_tok),
        "tokens_per_s": round(sum(tps) / len(tps), 2) if tps else None,
        "early_stop": "%d/%d" % (early, len(PROMPTS)),
        "repetition": round(max(reps), 3) if reps else None,
        "first_fail": first_fail,
        "prompts": len(PROMPTS),
        "raw": rows,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+",
                    help="one .rkllm per dtype, named <something>_<dtype>.rkllm")
    ap.add_argument("--binary", default="./llm_demo", help="board-side RKLLM demo binary")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--logits", action="store_true",
                    help="demo build exposes per-token logits (enables real perplexity)")
    ap.add_argument("--reference-ppl", type=float,
                    help="unquantized perplexity on the same prompts, for the delta column")
    ap.add_argument("-o", "--out", default="quality.json")
    args = ap.parse_args()

    results = []
    for path in args.models:
        m = re.search(r"_(w\d+a\d+(?:_g\d+)?)", os.path.basename(path))
        dtype = m.group(1) if m else os.path.basename(path)
        sys.stderr.write("measuring %s ...\n" % dtype)
        results.append(measure(args.binary, path, dtype, args.max_tokens, args.logits))

    with open(args.out, "w") as f:
        json.dump({"reference_ppl": args.reference_ppl, "results": results}, f, indent=1)

    hdr = "%-14s %8s %8s %8s %12s %8s  %s" % (
        "dtype", "ppl", "d_ppl", "tok/s", "early_stop", "repeat", "first_fail")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        d = "-"
        if r["ppl"] and args.reference_ppl:
            d = "%+.1f%%" % ((r["ppl"] / args.reference_ppl - 1) * 100)
        print("%-14s %8s %8s %8s %12s %8s  %s" % (
            r["dtype"],
            "%.2f" % r["ppl"] if r["ppl"] else "-",
            d,
            r["tokens_per_s"] if r["tokens_per_s"] else "-",
            r["early_stop"],
            r["repetition"] if r["repetition"] is not None else "-",
            r["first_fail"] or "-"))
    print("\nwrote %s" % args.out)
    print("Publish these only with board, runtime, driver and clock governor stated.")


if __name__ == "__main__":
    main()
