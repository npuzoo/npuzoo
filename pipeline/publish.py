#!/usr/bin/env python3
"""Merge package records + bench results into the registry index, render model cards.

Usage: python publish.py --build ./build --bench bench_results.jsonl --out index.json
"""
import argparse
import glob
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="./build")
    ap.add_argument("--bench", default="bench_results.jsonl")
    ap.add_argument("--out", default="index.json")
    ap.add_argument("--cards", default="./cards")
    a = ap.parse_args()

    benches = {}
    if os.path.exists(a.bench):
        for line in open(a.bench):
            if line.strip():
                b = json.loads(line)
                benches[os.path.basename(b["model_file"])] = b

    tmpl = open(os.path.join(os.path.dirname(__file__), "..", "templates", "MODEL_CARD.md")).read()
    os.makedirs(a.cards, exist_ok=True)

    packages = []
    for rec_path in sorted(glob.glob(os.path.join(a.build, "*.package.json"))):
        rec = json.load(open(rec_path))
        bench = benches.get(os.path.basename(rec.get("converted") or ""), {})
        npu, cpu = bench.get("npu_tps"), bench.get("cpu_tps")
        recommend = "pending"
        if npu and cpu:
            recommend = "npu" if npu >= cpu else "cpu"
        pkg = {
            "name": rec["name"], "chip": rec["chip"], "backend": rec["backend"],
            "quant": rec["quant"], "context": rec["context"],
            "requires": {"toolkit": rec.get("toolkit")},
            "files": rec.get("files", []),
            "bench": {k: bench.get(k) for k in ("npu_tps", "cpu_tps", "board", "npu_driver", "date")},
            "recommend": recommend,
            "source": rec["source"],
        }
        packages.append(pkg)
        card = tmpl
        flat = {**pkg, **pkg["bench"], **pkg["source"], "toolkit": rec.get("toolkit")}
        for k, v in flat.items():
            if not isinstance(v, (dict, list)):
                card = card.replace("{{%s}}" % k, str(v if v is not None else "—"))
        open(os.path.join(a.cards, f'{rec["name"]}.md'), "w").write(card)

    json.dump({"schema": 1, "packages": packages}, open(a.out, "w"), indent=2)
    print(f"✓ {a.out}: {len(packages)} package(s); cards → {a.cards}/")


if __name__ == "__main__":
    main()
