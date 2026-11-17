"""Infer which RKLLM runtime produced a log, from the messages in it.

Most logs people paste do not contain a version line — the banner scrolled off,
or they pasted only the error. But the runtime's message catalogue grew a lot
between releases (17 log strings in 1.1.0, 210 in 1.3.1), so the *presence* of a
message pins a lower bound on the version.

data/runtime_fingerprints.json was produced by extracting the literal strings
from the official librkllmrt.so at every release tag from 1.1.0 to 1.3.1 and
recording which release each message first appears in. See
tools/build_fingerprints.py.

This gives a lower bound, never an exact version: a 1.3.1 runtime can still emit
a message introduced in 1.2.0. Phrase it that way to the user.
"""
import json
import os

_DATA = os.path.join(os.path.dirname(__file__), "data", "runtime_fingerprints.json")

_cache = None

# The standalone build inlines the table here, because a single file has no
# package data directory to read from. tools/build_standalone.py fills it in.
EMBEDDED = None


def _load():
    global _cache
    if _cache is None:
        if EMBEDDED:
            _cache = (EMBEDDED["versions"], EMBEDDED["stems"])
            return _cache
        try:
            with open(_DATA) as f:
                d = json.load(f)
            _cache = (d["versions"], d["stems"])
        except Exception:
            _cache = ([], [])
    return _cache


def infer_runtime(text):
    """Return (min_version, [evidence]) or (None, []).

    min_version is the newest 'introduced in' among the messages we recognise,
    i.e. the runtime must be at least this new.
    """
    versions, stems = _load()
    if not versions:
        return None, []
    order = {v: i for i, v in enumerate(versions)}
    best, evidence = None, []
    for stem, ver in stems:
        if stem in text:
            evidence.append((stem, ver))
            if best is None or order[ver] > order[best]:
                best = ver
    if best is None:
        return None, []
    # only the messages that actually justify the bound are worth showing
    evidence = [e for e in evidence if e[1] == best]
    return best, evidence


def is_newest(version):
    versions, _ = _load()
    return bool(versions) and version == versions[-1]
