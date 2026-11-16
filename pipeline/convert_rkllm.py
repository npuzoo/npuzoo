#!/usr/bin/env python3
"""Convert a HF model to .rkllm and emit a npuzoo package entry.  (x86 only)

Usage:
  python convert_rkllm.py --model Qwen/Qwen3-1.7B --chip rk3588 \
      --quant w8a8 --out ./build

Without rkllm-toolkit installed it runs in --dry-run mode automatically:
prints the plan, writes the package entry with nulls, so the rest of the
pipeline can be developed off the conversion box.

Records EVERYTHING version-pinned: toolkit, target chip, quant, source
revision. That record is the product.
"""
import argparse
import datetime
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF repo id, e.g. Qwen/Qwen3-1.7B")
    ap.add_argument("--revision", default="main")
    ap.add_argument("--chip", default="rk3588", choices=["rk3588", "rk3576"])
    ap.add_argument("--quant", default="w8a8")
    ap.add_argument("--context", type=int, default=4096)
    ap.add_argument("--out", default="./build")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    name = a.model.split("/")[-1].lower().replace("_", "-")
    record = {
        "name": name,
        "source": {"repo": a.model, "revision": a.revision},
        "chip": a.chip, "backend": "rkllm", "quant": a.quant, "context": a.context,
        "toolkit": None, "converted": None, "status": "dry-run",
        "date": datetime.date.today().isoformat(),
    }

    try:
        from rkllm.api import RKLLM  # type: ignore
        import rkllm  # type: ignore
        record["toolkit"] = getattr(rkllm, "__version__", "unknown")
    except ImportError:
        RKLLM = None

    if RKLLM is None or a.dry_run:
        print(f"[dry-run] would convert {a.model}@{a.revision} → {a.chip} {a.quant} ctx={a.context}")
        print("[dry-run] install rkllm-toolkit on an x86 Linux box to convert for real:")
        print("          pip install rkllm-toolkit  # from airockchip/rknn-llm releases")
    else:
        llm = RKLLM()
        print(f"loading {a.model}@{a.revision} …")
        ret = llm.load_huggingface(model=a.model)
        if ret != 0:
            sys.exit(f"load failed ({ret}) — likely unsupported architecture. "
                     "File this at github.com/npuzoo/npuzoo/issues with the full log.")
        print(f"building {a.quant} for {a.chip} …")
        ret = llm.build(do_quantization=True, optimization_level=1,
                        quantized_dtype=a.quant, target_platform=a.chip,
                        max_context=a.context)
        if ret != 0:
            sys.exit(f"build failed ({ret})")
        out_file = os.path.join(a.out, f"{name}-{a.chip}-{a.quant}.rkllm")
        ret = llm.export_rkllm(out_file)
        if ret != 0:
            sys.exit(f"export failed ({ret})")
        record["converted"] = out_file
        record["status"] = "converted"
        print(f"✓ {out_file}")

    rec_path = os.path.join(a.out, f"{name}.package.json")
    with open(rec_path, "w") as f:
        json.dump(record, f, indent=2)
    print(f"✓ package record → {rec_path}")
    print("next: run bench_on_board.sh on the board, then publish.py")


if __name__ == "__main__":
    main()
