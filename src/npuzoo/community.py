"""npuzoo find / npuzoo get — community .rkllm files on Hugging Face.

Hundreds of people have converted models for Rockchip NPUs and published them.
The hard part for a user is not finding a file but knowing, before a multi-GB
download, whether it can load on *their* board with *their* runtime. find
answers that from what each file's name claims; get downloads one, checks size
and SHA-256 against what Hugging Face published, then runs inspect on it.

We list and link. Files stay with their authors; downloads go to them and
count for them. Nothing here is tested by us — that is what verified packages
(npuzoo pull) are for.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from . import USER_AGENT
from .doctor import collect, FAIL, WARN
from .inspect import parse_name, check_claims, inspect_file, PASS, INSPECT_ICON
from .models import family_for_name

INDEX_URL = "https://raw.githubusercontent.com/npuzoo/npuzoo/main/index/community.json"
HOME = os.path.expanduser(os.environ.get("NPUZOO_HOME", "~/.npuzoo"))
CACHE = os.path.join(HOME, "community.json")
MAX_AGE = 24 * 3600

YES, MAYBE, NO = "yes", "maybe", "no"
MARK = {YES: "✓", MAYBE: "?", NO: "✗"}
_RANK = {YES: 0, MAYBE: 1, NO: 2}


def _endpoint():
    # HF_ENDPOINT=https://hf-mirror.com works where huggingface.co is slow or blocked
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")


def _ms_endpoint():
    return os.environ.get("MODELSCOPE_ENDPOINT", "https://www.modelscope.cn").rstrip("/")


SOURCES = {"huggingface": "Hugging Face", "modelscope": "ModelScope"}


def source_of(entry):
    return entry.get("source") or "huggingface"


# ---------------------------------------------------------------- index

def load_index(src=None, refresh=False, now=None):
    """Return (index, where_it_came_from). Remote index is cached for a day."""
    src = src or os.environ.get("NPUZOO_COMMUNITY_INDEX") or INDEX_URL
    if not src.startswith(("http://", "https://")):
        with open(src, encoding="utf-8") as f:
            return json.load(f), src
    now = now or time.time()
    fresh = os.path.exists(CACHE) and now - os.path.getmtime(CACHE) < MAX_AGE
    if fresh and not refresh:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f), CACHE
    try:
        req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        index = json.loads(raw.decode("utf-8"))
        os.makedirs(HOME, exist_ok=True)
        with open(CACHE, "wb") as f:
            f.write(raw)
        return index, src
    except Exception as e:
        if os.path.exists(CACHE):
            print("! could not refresh the index (%s); using the cached copy" % e, file=sys.stderr)
            with open(CACHE, encoding="utf-8") as f:
                return json.load(f), CACHE
        raise


# ---------------------------------------------------------------- judging

def claims_for(entry):
    """What the file name claims, falling back to its folders, then the repo name.

    'rk3588/Qwen3-1.7B-w8a8.rkllm' in 'someone/qwen3-rkllm-1.2.1' claims chip
    rk3588, format w8a8 and toolkit 1.2.1. None of it is verified.
    """
    parts = [entry["path"]] + list(reversed(entry["path"].split("/")[:-1])) + [entry["repo"].split("/")[-1]]
    claims = {"chip": None, "dtype": None, "group": None, "toolkit": None}
    for p in parts:
        c = parse_name(p)
        for k in claims:
            if claims[k] is None and c[k] is not None:
                if k == "group" and claims["dtype"] not in (None, c["dtype"]):
                    continue        # a group size only belongs with its own format
                claims[k] = c[k]
    return claims


def family_for_entry(entry):
    """Model family from the file name, its folders, the repo name, then the base model."""
    parts = [entry["path"].split("/")[-1]] + list(reversed(entry["path"].split("/")[:-1])) \
        + [entry["repo"].split("/")[-1], entry.get("base_model") or ""]
    for p in parts:
        fam = family_for_name(p)
        if fam:
            return fam
    return None


def judge(entry, board=None, runtime=None):
    """(verdict, reasons) for loading this file on board with runtime."""
    claims = claims_for(entry)
    findings = check_claims(claims, board=board, runtime=runtime, family=family_for_entry(entry))
    fails = [f["detail"] for f in findings if f["status"] == FAIL]
    if fails:
        return NO, fails
    reasons = [f["detail"] for f in findings if f["status"] == WARN]
    if entry.get("gated"):
        reasons.append("Gated: accept the terms on the model page and set HF_TOKEN before downloading.")
    unknown = []
    if not claims["chip"]:
        unknown.append("chip")
    if runtime and not claims["toolkit"]:
        unknown.append("toolkit version")
    if unknown:
        reasons.append("The name does not say the %s." % " or ".join(unknown))
        return MAYBE, reasons
    if claims["chip"] in ("rk1820", "rk1828", "rk182x") or any(
            f["status"] == WARN for f in findings):
        return MAYBE, reasons
    return YES, reasons


def _matches(entry, terms):
    hay = " ".join(str(entry.get(k) or "") for k in ("repo", "path", "base_model")).lower()
    return all(t in hay for t in terms)


def search(index, query="", board=None, runtime=None, source=None):
    terms = [t.lower() for t in (query or "").split()]
    rows = []
    for e in index.get("files", []):
        if source and source_of(e) != source:
            continue
        if terms and not _matches(e, terms):
            continue
        verdict, reasons = judge(e, board, runtime)
        rows.append(dict(e, verdict=verdict, reasons=reasons, claims=claims_for(e)))
    # stable sorts: newest first, then most downloaded, then best fit
    rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
    rows.sort(key=lambda r: (_RANK[r["verdict"]], -(r.get("downloads") or 0)))
    return rows


def _target():
    """Board chip and runtime version, when we are running on a board."""
    if not os.path.exists("/proc/device-tree/compatible"):
        return None, None
    try:
        info = collect()
        return info.get("chip"), (info.get("rkllmrt") or {}).get("version")
    except Exception:
        return None, None


# ---------------------------------------------------------------- find

def _gb(n):
    return "-" if not n else "%.1f" % (n / 1e9)


def cmd_find(query="", board=None, runtime=None, index_src=None, show_all=False,
             limit=20, as_json=False, refresh=False, source=None):
    if board is None and runtime is None:
        board, runtime = _target()
    try:
        index, where = load_index(index_src, refresh=refresh)
    except Exception as e:
        print("✗ Could not load the community index (%s)." % e)
        print("  It is rebuilt weekly from Hugging Face; try again later, or pass --index PATH.")
        return 2
    rows = search(index, query, board, runtime, source)
    hidden = [r for r in rows if r["verdict"] == NO] if not show_all else []
    shown = [r for r in rows if show_all or r["verdict"] != NO]
    if as_json:
        print(json.dumps({"board": board, "runtime": runtime, "index": where,
                          "generated": index.get("generated"), "results": shown[:limit] if limit else shown},
                         ensure_ascii=False, indent=2))
        return 0 if shown else 1

    target = ", ".join(x for x in (board and board.upper(), runtime and "runtime " + runtime) if x)
    print("npuzoo find %s%s" % (query or "(all)", ("   for " + target) if target else ""))
    if not board:
        print("  Not on a board: add --board rk3588 (and --runtime 1.3.1) to check fit.")
    if not shown:
        print("  Nothing%s matches." % (" that fits" if hidden else ""))
    else:
        # one block per repo: its best file, and how many more it has
        groups, order = {}, []
        for r in shown:
            key = (source_of(r), r["repo"])
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)
        cap = order[:limit] if limit else order
        for repo in cap:
            r, more = groups[repo][0], len(groups[repo]) - 1
            dl = r.get("downloads")
            print()
            src = source_of(r)
            print("  %s %s%s" % (MARK[r["verdict"]], r["repo"], "   [ModelScope]" if src == "modelscope" else ""))
            print("      %s" % r["path"])
            if src == "modelscope":
                pop = "%s downloads in total" % (r.get("downloads_total") if r.get("downloads_total") is not None else "?")
            else:
                pop = "%s downloads/30d" % (dl if dl is not None else "?")
            print("      %s GB · toolkit %s · updated %s · %s%s" % (
                _gb(r.get("bytes")), r["claims"]["toolkit"] or "?", r.get("updated") or "?", pop,
                ("   (+%d more file%s in this repo)" % (more, "s" if more > 1 else "")) if more else ""))
        if limit and len(order) > limit:
            print("\n  … %d more repos (--limit 0 shows all)" % (len(order) - limit))
    if hidden:
        print("\n  %d file(s) hidden because their names say they will not load here (--all shows them)." % len(hidden))
    if shown:
        top = shown[0]
        print("\n  ✓ name fits   ? name does not say enough   ✗ will not load")
        print("  Get one:  npuzoo get %s%s %s" % ("--source modelscope " if source_of(top) == "modelscope" else "",
                                               top["repo"], top["path"]))
    print("\n  Published by their authors on Hugging Face and ModelScope; npuzoo has not tested them.")
    print("  Index of %s, %d files." % ((index.get("generated") or "?")[:10], len(index.get("files", []))))
    return 0 if shown else 1


# ---------------------------------------------------------------- get

def resolve_url(repo, path, endpoint=None, source="huggingface"):
    if source == "modelscope":
        return "%s/models/%s/resolve/master/%s" % (endpoint or _ms_endpoint(), repo, urllib.parse.quote(path))
    return "%s/%s/resolve/main/%s" % (endpoint or _endpoint(), repo, urllib.parse.quote(path))


def _open(url, start=0):
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = "bytes=%d-" % start
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def download(url, out, expect_bytes=None, expect_sha256=None, progress=True):
    """Download with resume. Returns (ok, message)."""
    part = out + ".part"
    h = hashlib.sha256()
    start = 0
    if os.path.exists(part):
        start = os.path.getsize(part)
        if expect_bytes and start >= expect_bytes:
            start = 0
        else:
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 22), b""):
                    h.update(chunk)
    r = _open(url, start)
    status = getattr(r, "status", None) or r.getcode()
    if start and status != 206:          # server ignored the Range: start over
        start, h = 0, hashlib.sha256()
    done, last = start, -1
    with r, open(part, "ab" if start else "wb") as w:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            w.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and expect_bytes:
                pct = int(done * 100 / expect_bytes)
                if pct // 5 != last:
                    last = pct // 5
                    sys.stdout.write("\r  %3d%%  %.2f / %.2f GB" % (pct, done / 1e9, expect_bytes / 1e9))
                    sys.stdout.flush()
    if progress and expect_bytes:
        sys.stdout.write("\n")
    if expect_bytes is not None and done != expect_bytes:
        return False, "Got %d bytes, expected %d. Run the same command again to resume." % (done, expect_bytes)
    if expect_sha256 and h.hexdigest() != expect_sha256.lower():
        os.remove(part)
        return False, "SHA-256 does not match what Hugging Face published. The partial file was deleted."
    os.replace(part, out)
    return True, "Size%s match what Hugging Face published." % (" and SHA-256" if expect_sha256 else "")


def cmd_get(repo, path, board=None, runtime=None, index_src=None, dest=None, force=False, source=None):
    if board is None and runtime is None:
        board, runtime = _target()
    try:
        index, _ = load_index(index_src)
    except Exception:
        index = {"files": []}
    source = source or os.environ.get("NPUZOO_SOURCE") or None
    matches = [e for e in index.get("files", []) if e["repo"] == repo and e["path"] == path
               and (source is None or source_of(e) == source)]
    matches.sort(key=lambda e: source_of(e) != "huggingface")      # Hugging Face first unless asked
    entry = matches[0] if matches else None
    if entry is None:
        entry = {"repo": repo, "path": path, "source": source or "huggingface"}
        print("! %s/%s is not in the index; it will be downloaded without a checksum to compare." % (repo, path))

    verdict, reasons = judge(entry, board, runtime)
    if verdict == NO and not force:
        print("✗ Not downloading: by its name, this file will not load here.")
        for r in reasons:
            print("    " + r)
        print("  Find one that fits:  npuzoo find %s" % (entry.get("base_model") or os.path.basename(path).split("-")[0]))
        print("  Download anyway:     add --force")
        return 1
    for r in reasons:
        print("! " + r)

    dest = dest or os.path.join(HOME, "community", repo)
    out = os.path.join(dest, path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    url = resolve_url(repo, path, source=source_of(entry))
    if entry.get("license"):
        print("  License: %s (from the model page; you are bound by it)" % entry["license"])
    print("↓ %s" % url)
    try:
        ok, msg = download(url, out, entry.get("bytes"), entry.get("sha256"))
    except Exception as e:
        print("✗ Download failed: %s" % e)
        if "huggingface.co" in url:
            print("  If huggingface.co is slow or blocked here, try:  HF_ENDPOINT=https://hf-mirror.com npuzoo get ...")
            print("  or look for the same model on ModelScope:  npuzoo find <name> --source modelscope")
        return 1
    print(("✓ " if ok else "✗ ") + msg)
    if not ok:
        return 1

    findings = inspect_file(out, board=board, runtime=runtime)
    for f in findings:
        if f["status"] != PASS or f["check"] in ("file type",):
            print("  %s %-14s %s" % (INSPECT_ICON[f["status"]], f["check"], f["detail"]))
    print("\nSaved to %s" % out)
    return 1 if any(f["status"] == FAIL for f in findings) else 0
