#!/usr/bin/env python3
"""Add `npuzoo bench` reports to bench/results.json and docs/benchmarks.md.

    python tools/collect_bench.py report.json [more.json ...]
    python tools/collect_bench.py --issue-body-env ISSUE_BODY --source https://github.com/.../issues/12

The second form is what .github/workflows/bench-results.yml runs when a
maintainer labels a benchmark issue `bench-accepted`: the report is taken
from the issue's ```json block. A report must have the fields `npuzoo
bench` writes; anything else is refused with the reason, and nothing is
written.

The page lists raw results, grouped by model file and sorted by chip and
date. It ranks nothing: no "fastest", no colours, no medals. Clock
governors are shown beside every row, because a result measured with the
clocks pinned is not comparable with one measured without.
"""
import argparse
import json
import os
import re
import sys

REQUIRED = ["npuzoo", "date", "chip", "runtime", "model", "workloads"]
FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)
MAX_FIELD = 80


class BadReport(ValueError):
    pass


def from_issue(body):
    """The JSON report inside an issue body (the form puts it in a ```json block)."""
    for block in FENCE.findall(body or ""):
        try:
            obj = json.loads(block)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    try:
        obj = json.loads(body or "")
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    raise BadReport("no JSON report found in the issue body")


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 else None


def clean(report, source=None):
    """Only the fields we publish, type-checked; raises BadReport."""
    missing = [k for k in REQUIRED if k not in report]
    if missing:
        raise BadReport("missing fields: %s" % ", ".join(missing))
    model = report.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("file"), str):
        raise BadReport("model must have a file name")
    sha = model.get("sha256")
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise BadReport("model.sha256 must be 64 hex characters")
    wl = report.get("workloads")
    if not isinstance(wl, dict) or not wl:
        raise BadReport("workloads is empty")

    def text(v):
        if v is None:
            return None
        s = re.sub(r"\s+", " ", str(v)).strip()
        return s[:MAX_FIELD] or None

    out = {
        "date": text(report["date"]), "npuzoo": text(report["npuzoo"]),
        "board": text(report.get("board")), "chip": text(report["chip"]), "kernel": text(report.get("kernel")),
        "npu_driver": text(report.get("npu_driver")), "runtime": text(report["runtime"]),
        "mem_gb": _num(report.get("mem_gb")),
        "cpu_governor": text(report.get("cpu_governor")), "npu_governor": text(report.get("npu_governor")),
        "model": {"file": text(model["file"]), "bytes": _num(model.get("bytes")), "sha256": sha},
        "load_s": _num(report.get("load_s")),
        "workloads": {},
        "source": text(source) if source else None,
    }
    for name in ("chat", "long-prompt"):
        w = wl.get(name)
        if isinstance(w, dict):
            out["workloads"][name] = {k: _num(w.get(k)) for k in
                                      ("runs", "prefill_tps", "generate_tps", "prefill_tokens", "generate_tokens",
                                       "memory_mb")}
    if not out["workloads"]:
        raise BadReport("no chat or long-prompt workload in the report")
    return out


def key(r):
    return (r["model"]["sha256"], r["chip"], r["runtime"], r.get("board"), r["date"])


def merge(results, new):
    """Add new records; one with the same file, chip, runtime, board and date replaces the old."""
    seen = {key(r): i for i, r in enumerate(results)}
    for r in new:
        k = key(r)
        if k in seen:
            results[seen[k]] = r
        else:
            seen[k] = len(results)
            results.append(r)
    return results


def _cell(v):
    if v is None or v == "":
        return "—"
    return str(v).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


FIXED = ("performance", "userspace")      # Rockchip's fix_freq scripts leave "userspace" with a set speed


def _pinned(r):
    govs = [g for g in (r.get("cpu_governor"), r.get("npu_governor")) if g]
    if not govs:
        return "not recorded"
    return "pinned" if all(any(f in g for f in FIXED) for g in govs) else "not pinned"


def render(results):
    lines = [
        "# Benchmarks",
        "",
        "Results people measured with `npuzoo bench` on their own boards and shared",
        "([how](../README.md)). Each row is one report, exactly as submitted: two",
        "workloads, the runtime's own counters, the median of three runs after a",
        "warm-up. Rows are not ranked. Clocks matter: Rockchip's published figures",
        "are measured with the clocks pinned, so compare a pinned row only with",
        "another pinned row.",
        "",
        "Raw data: [bench/results.json](../bench/results.json). To add yours, run",
        "`npuzoo bench your-model.rkllm` and open a",
        "[benchmark issue](https://github.com/npuzoo/npuzoo/issues/new?template=benchmark.yml).",
        "",
    ]
    if not results:
        lines.append("No results yet.")
        return "\n".join(lines) + "\n"
    by_file = {}
    for r in results:
        by_file.setdefault(r["model"]["file"], []).append(r)
    for name in sorted(by_file, key=str.lower):
        rows = sorted(by_file[name], key=lambda r: (r["chip"] or "", r["runtime"] or "", r["date"] or ""))
        sha = rows[0]["model"]["sha256"]
        lines += ["## %s" % _cell(name), "", "SHA-256 `%s`" % sha[:16] + "…", "",
                  "| Board | Chip | Runtime | NPU driver | Clocks | Chat: generate tok/s | Long prompt: prefill tok/s"
                  " | Memory (MB) | Load (s) | Date | Report |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            chat = r["workloads"].get("chat") or {}
            longp = r["workloads"].get("long-prompt") or {}
            mem = max([m for m in (chat.get("memory_mb"), longp.get("memory_mb")) if m is not None] or [None])
            src = "[link](%s)" % r["source"] if r.get("source", "") and r["source"].startswith("https://") else "—"
            lines.append("| %s |" % " | ".join(_cell(x) for x in (
                r.get("board"), r["chip"], r["runtime"], r.get("npu_driver"), _pinned(r),
                chat.get("generate_tps"), longp.get("prefill_tps"), mem, r.get("load_s"),
                (r.get("date") or "")[:10])) + " %s |" % src)
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("reports", nargs="*", help="JSON files written by npuzoo bench")
    ap.add_argument("--issue-body-env", help="read one report from the issue body in this environment variable")
    ap.add_argument("--source", help="link to where the report came from (the issue)")
    ap.add_argument("--results", default="bench/results.json")
    ap.add_argument("--md", default="docs/benchmarks.md")
    a = ap.parse_args(argv)

    try:
        new = []
        if a.issue_body_env:
            new.append(clean(from_issue(os.environ.get(a.issue_body_env, "")), a.source))
        for path in a.reports:
            with open(path, encoding="utf-8") as f:
                new.append(clean(json.load(f), a.source))
    except (BadReport, ValueError, OSError) as e:
        print("refused: %s" % e, file=sys.stderr)
        return 1
    results = []
    if os.path.exists(a.results):
        with open(a.results, encoding="utf-8") as f:
            results = json.load(f).get("results", [])
    results = merge(results, new)
    os.makedirs(os.path.dirname(a.results) or ".", exist_ok=True)
    with open(a.results, "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "results": results}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.makedirs(os.path.dirname(a.md) or ".", exist_ok=True)
    with open(a.md, "w", encoding="utf-8") as f:
        f.write(render(results))
    print("added %d report(s); %d in total" % (len(new), len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
