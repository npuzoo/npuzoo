#!/usr/bin/env python3
"""Convert a HF model to .rkllm and write a npuzoo package record.  (x86 only)

Usage:
  python convert_rkllm.py --model Qwen/Qwen3-1.7B --chip rk3588 --quant w8a8 --out ./build

The conversion itself is `npuzoo convert` (src/npuzoo/convert.py): the same
code path the conversion matrix exercises on every toolkit release. This
script adds what the registry needs: a package record with the source
revision, toolkit version, output file, size and SHA-256. Without
rkllm-toolkit installed (or with --dry-run) it writes the record with nulls,
so the rest of the pipeline can be developed off the conversion box.

Next steps: bench_on_board.sh on the board, then publish.py.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF repo id, e.g. Qwen/Qwen3-1.7B")
    ap.add_argument("--revision", default=None, help="commit or branch on the Hub (default: the latest)")
    ap.add_argument("--chip", default="rk3588", choices=["rk3588", "rk3588s", "rk3576", "rk3562", "rv1126b"])
    ap.add_argument("--quant", default="w8a8")
    ap.add_argument("--context", type=int, default=4096)
    ap.add_argument("--out", default="./build")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    from npuzoo.convert import cmd_convert, output_name
    from npuzoo.pc import collect_pc

    os.makedirs(a.out, exist_ok=True)
    name = a.model.split("/")[-1].lower().replace("_", "-")
    toolkit = collect_pc().get("toolkit")
    record = {
        "name": name,
        "source": {"repo": a.model, "revision": a.revision},
        "chip": a.chip, "backend": "rkllm", "quant": a.quant, "context": a.context,
        "toolkit": toolkit, "converted": None, "bytes": None, "sha256": None, "status": "dry-run",
        "date": datetime.date.today().isoformat(),
    }

    if toolkit is None or a.dry_run:
        print("[dry-run] would convert %s@%s → %s %s ctx=%d" % (a.model, a.revision or "latest", a.chip,
                                                               a.quant, a.context))
        if toolkit is None:
            print("[dry-run] rkllm-toolkit is not installed here; `npuzoo doctor --pc` says how to set it up.")
    else:
        if not os.path.isdir(a.model):
            from npuzoo.convert import remote_facts
            record["source"]["revision"] = remote_facts(a.model, a.revision).get("revision")
        code = cmd_convert(a.model, a.chip, dtype=a.quant, out_dir=a.out, context=a.context,
                           revision=record["source"]["revision"])
        if code != 0:
            return code
        out_file = os.path.join(a.out, output_name(a.model, a.chip, a.quant, toolkit))
        record.update(converted=out_file, status="converted", bytes=os.path.getsize(out_file),
                      sha256=sha256_of(out_file))

    rec_path = os.path.join(a.out, "%s.package.json" % name)
    with open(rec_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print("✓ package record → %s" % rec_path)
    print("next: run bench_on_board.sh on the board, then publish.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
