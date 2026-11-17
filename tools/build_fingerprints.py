#!/usr/bin/env python3
"""Rebuild src/npuzoo/data/runtime_fingerprints.json from the official runtimes.

The RKLLM runtime's log-message catalogue grew from 17 strings in v1.1.0 to 210
in v1.3.1. Because messages are only ever added, the presence of a message in a
log puts a floor under the runtime version that produced it — which lets
`npuzoo explain` date a log that carries no version line at all.

This downloads librkllmrt.so at every release tag and records, for each literal
message, the earliest release it appears in. ~95 MB of downloads; run it when a
new RKLLM release lands:

    python tools/build_fingerprints.py

Needs network access to raw.githubusercontent.com and the `strings` binary.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "npuzoo" / "data" / "runtime_fingerprints.json"

# oldest first; the order is what "introduced in" means
TAGS = ["1.1.0", "1.1.1", "1.1.2", "1.1.3", "1.1.4", "1.2.0",
        "1.2.1b1", "1.2.1", "1.2.2", "1.2.3", "1.3.0", "1.3.1"]

URL = ("https://raw.githubusercontent.com/airockchip/rknn-llm/release-v%s"
       "/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so")

MSG = re.compile(r"^[EW] rkllm: ")
MIN_STEM = 28          # shorter literals are not distinctive enough to date a log


def catalogue(path):
    out = subprocess.run(["strings", "-a", str(path)], capture_output=True, text=True).stdout
    return {line for line in out.splitlines() if MSG.match(line)}


def main():
    order = {t: i for i, t in enumerate(TAGS)}
    first = {}
    newest = set()
    with tempfile.TemporaryDirectory() as tmp:
        for tag in TAGS:
            dest = pathlib.Path(tmp) / (tag + ".so")
            sys.stderr.write("fetching %s ... " % tag)
            sys.stderr.flush()
            try:
                urllib.request.urlretrieve(URL % tag, dest)
            except Exception as e:
                sys.exit("failed on %s: %s" % (tag, e))
            msgs = catalogue(dest)
            sys.stderr.write("%d messages\n" % len(msgs))
            for m in msgs:
                first.setdefault(m, tag)
            newest = msgs

    stems = {}
    for msg, tag in first.items():
        if msg not in newest:
            continue                      # dropped since; useless as a fingerprint
        stem = msg.split(": ", 1)[1].split("%")[0].rstrip()
        if len(stem) < MIN_STEM:
            continue
        if stem not in stems or order[tag] < order[stems[stem]]:
            stems[stem] = tag

    data = {"versions": TAGS,
            "stems": sorted(([s, v] for s, v in stems.items()),
                            key=lambda r: (order[r[1]], r[0]))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print("wrote %s — %d fingerprints across %d releases"
          % (OUT.relative_to(ROOT), len(stems), len(TAGS)))


if __name__ == "__main__":
    main()
