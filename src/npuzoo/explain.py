"""npuzoo explain — paste an RKLLM/RKNN log, get the diagnosis.

Useful with no hardware at all: the knowledge base in known_issues.py is
built from logs people posted publicly, so this works on anyone's log.

    npuzoo explain board.log
    ./demo ... 2>&1 | npuzoo explain
"""
import sys

from .known_issues import scan, looks_healthy, REPO, BLOCKER, PROBLEM, NOISE

EXPLAIN_ICON = {BLOCKER: "✗", PROBLEM: "!", NOISE: "·"}
EXPLAIN_LABEL = {BLOCKER: "blocker", PROBLEM: "problem", NOISE: "noise"}


def _versions(text):
    """Pull the version lines the runtime prints at init, if they are there."""
    import re
    found = {}
    for key, pat in (
        ("runtime", r"rkllm-runtime version:\s*([\w.]+)"),
        ("toolkit", r"rkllm-toolkit version:\s*([\w.]+)"),
        ("driver", r"rknpu driver version:\s*([\w.]+)"),
        ("platform", r"platform:\s*(RK\w+|RV\w+)"),
        ("dtype", r"model_dtype:\s*(\w+)"),
        ("context", r"max_context_limit:\s*(\d+)"),
        ("librknnrt", r"librknnrt version:\s*([\d.]+)"),
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            found[key] = m.group(1)
    return found


def cmd_explain(path=None):
    if path:
        try:
            with open(path, "r", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print("npuzoo explain: cannot read %s (%s)" % (path, e.strerror))
            return 2
    else:
        if sys.stdin.isatty():
            print("npuzoo explain: paste a log on stdin, or give a file.")
            print("  npuzoo explain board.log")
            print("  ./demo ... 2>&1 | npuzoo explain")
            return 2
        text = sys.stdin.read()

    if not text.strip():
        print("npuzoo explain: empty input.")
        return 2

    v = _versions(text)
    if v:
        print("From the log:")
        for k in ("platform", "runtime", "toolkit", "driver", "librknnrt", "dtype", "context"):
            if k in v:
                print("   %-10s %s" % (k, v[k]))
        if "runtime" in v and "toolkit" in v and v["runtime"].split("b")[0] != v["toolkit"].split("b")[0]:
            print("   note       runtime %s vs toolkit %s — these should normally match."
                  % (v["runtime"], v["toolkit"]))
        print()

    hits = scan(text)
    if looks_healthy(text):
        print("This log shows a successful init — nothing here needs fixing.")
        if hits:
            print("(Non-blocking notes follow.)\n")
        else:
            return 0
    elif not hits:
        print("No known failure signature found.")
        print("That is not the same as 'nothing is wrong' — it means this log does not")
        print("match anything npuzoo has seen yet. Please open it as a discussion so the")
        print("next person gets an answer:  %s/discussions" % REPO)
        return 0

    real = [h for h in hits if h["severity"] != NOISE]
    if not looks_healthy(text):
        print("%d finding(s):\n" % len(hits))
    for h in hits:
        print(" %s [%s] %s" % (EXPLAIN_ICON[h["severity"]], EXPLAIN_LABEL[h["severity"]], h["title"]))
        print("   matched: %s" % h["evidence"])
        print("   %s" % h["why"])
        for line in h["fix"]:
            print("     %s" % line)
        print()

    if real:
        print("Still stuck after that? Paste the log and your `npuzoo doctor` output into")
        print("%s/discussions — unmatched logs are how this list grows." % REPO)
    return 1 if any(h["severity"] == BLOCKER for h in hits) else 0
