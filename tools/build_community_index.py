#!/usr/bin/env python3
"""Build index/community.json: every .rkllm file published on Hugging Face and ModelScope.

npuzoo find reads this index so people can see, before downloading, which
community-built model files claim to fit their board and runtime. We list and
link; the files stay with their authors, and downloads count for them.

Only facts Hugging Face publishes go into the index (repo, path, size,
SHA-256, licence, base model, last update, 30-day downloads). What a file
*claims* (chip, weight format, toolkit version) is parsed from its name at
query time, so improving the parser never needs a rebuild.

    python tools/build_community_index.py --out index/community.json

Standard library only. Runs weekly in .github/workflows/community-index.yml.
Set HF_ENDPOINT to use a mirror, HF_TOKEN to raise the rate limit.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
UA = "npuzoo-index-builder/1 (+https://github.com/npuzoo/npuzoo)"

# Repo-name searches plus one tag filter. A repo found by several is fetched
# once. Results without a .rkllm file are dropped before any detail request,
# so broad terms like "npu" cost only list pages.
QUERIES = [
    ("search", "rkllm"), ("search", "rk3588"), ("search", "rk3576"),
    ("search", "rk3562"), ("search", "rv1126"), ("search", "rknn"),
    ("search", "rockchip"), ("search", "npu"), ("filter", "rkllm"),
]
EXPAND = ["siblings", "downloads", "lastModified", "tags", "cardData", "gated"]
PAGE = 1000


def _get(url, tries=6):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    delay = 2.0
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r), r.headers.get("Link")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                wait = float(e.headers.get("Retry-After") or delay)
                print("  %s on %s, waiting %.0fs" % (e.code, url[:90], wait), file=sys.stderr)
                time.sleep(wait)
                delay = min(delay * 2, 120)
                continue
            if e.code in (401, 403, 404):
                return None, None          # private, gated-without-token, or deleted since listing
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            raise
    return None, None


def next_link(header):
    """URL of rel="next" in an RFC 8288 Link header, or None."""
    for part in (header or "").split(","):
        m = re.match(r'\s*<([^>]+)>\s*;\s*rel="?next"?', part)
        if m:
            return m.group(1)
    return None


def list_url(kind, term):
    q = [(kind, term), ("limit", str(PAGE))] + [("expand[]", e) for e in EXPAND]
    return ENDPOINT + "/api/models?" + urllib.parse.urlencode(q)


def has_rkllm(model):
    return any(s.get("rfilename", "").lower().endswith(".rkllm") for s in model.get("siblings") or [])


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def license_of(model):
    lic = _first((model.get("cardData") or {}).get("license"))
    if lic:
        return str(lic)
    for t in model.get("tags") or []:
        if t.startswith("license:"):
            return t.split(":", 1)[1]
    return None


def base_model_of(model):
    bm = _first((model.get("cardData") or {}).get("base_model"))
    if bm:
        return str(bm)
    for t in model.get("tags") or []:
        # "base_model:Qwen/Qwen3-1.7B" — skip the relation forms
        # ("base_model:quantized:...", "base_model:finetune:...")
        if t.startswith("base_model:") and t.count(":") == 1:
            return t.split(":", 1)[1]
    return None


def files_from_detail(model, detail):
    """Index entries for the .rkllm files of one repo."""
    out = []
    for s in (detail or {}).get("siblings") or []:
        path = s.get("rfilename", "")
        if not path.lower().endswith(".rkllm"):
            continue
        lfs = s.get("lfs") or {}
        sha = lfs.get("sha256") or lfs.get("oid")
        size = lfs.get("size") or s.get("size")
        out.append({
            "source": "huggingface",
            "repo": model["id"],
            "path": path,
            "bytes": int(size) if size is not None else None,
            "sha256": sha.split(":")[-1] if sha else None,
            "updated": (model.get("lastModified") or detail.get("lastModified") or "")[:10] or None,
            "downloads": model.get("downloads"),
            "license": license_of(model),
            "base_model": base_model_of(model),
            "gated": bool(model.get("gated")),
        })
    return out


# ---------------------------------------------------------------- ModelScope
#
# Most domestic developers never touch Hugging Face, so the same files are
# looked for on ModelScope too. Endpoints as used by the official client
# (modelscope_hub): GET /openapi/v1/models?search=... lists models, and
# GET /api/v1/models/{id}/repo/files?Recursive=True lists files with Path,
# Size and Sha256. Field names differ between API generations, so parsing is
# deliberately tolerant.

MS_ENDPOINT = os.environ.get("MODELSCOPE_ENDPOINT", "https://www.modelscope.cn").rstrip("/")
MS_TERMS = ["rkllm", "rk3588", "rk3576", "rk3562", "rv1126", "rknn", "rockchip", "npu"]
MS_PAGE = 50          # the OpenAPI refuses larger pages (modelscope_hub caps at 50)


def _unwrap(payload):
    """The interesting part of a ModelScope response, whatever envelope it came in."""
    while isinstance(payload, dict):
        for key in ("data", "Data"):
            if key in payload and isinstance(payload[key], (dict, list)):
                payload = payload[key]
                break
        else:
            return payload
    return payload


def ms_items(payload):
    """Model records from a list response."""
    data = _unwrap(payload)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("models", "Models", "items", "Items"):
        if isinstance(data.get(key), list):
            return data[key]
    for key in ("Model", "model"):
        if isinstance(data.get(key), dict):
            return ms_items(data[key])
    return next((v for v in data.values() if isinstance(v, list)), [])


def ms_repo_id(item):
    rid = item.get("id") or item.get("model_id") or item.get("ModelId")
    if isinstance(rid, str) and "/" in rid:
        return rid
    owner = item.get("owner") or item.get("Path") or item.get("path") or item.get("Owner")
    name = item.get("name") or item.get("Name")
    if isinstance(owner, dict):
        owner = owner.get("name") or owner.get("Name")
    return "%s/%s" % (owner, name) if owner and name else None


def _date(v):
    if isinstance(v, (int, float)) and v > 0:
        return time.strftime("%Y-%m-%d", time.gmtime(v / 1000 if v > 1e11 else v))
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


def ms_files(payload):
    """(path, size, sha256) of the .rkllm files in a repo/files response."""
    data = _unwrap(payload)
    if isinstance(data, dict):
        files = data.get("Files") or data.get("files") or []
    else:
        files = data if isinstance(data, list) else []
    out = []
    for f in files or []:
        if not isinstance(f, dict) or (f.get("Type") or f.get("type")) == "tree":
            continue
        path = f.get("Path") or f.get("path") or ""
        if path.lower().endswith(".rkllm"):
            out.append((path, f.get("Size") or f.get("size"), f.get("Sha256") or f.get("sha256")))
    return out


def ms_entries(item, files):
    rid = ms_repo_id(item)
    lic = item.get("license") or item.get("License")
    return [{
        "source": "modelscope",
        "repo": rid,
        "path": path,
        "bytes": int(size) if size is not None else None,
        "sha256": sha,
        "updated": _date(item.get("last_modified") or item.get("LastUpdatedTime") or item.get("UpdatedAt")
                         or item.get("updated_at") or item.get("GmtModified")),
        "downloads": None,
        "downloads_total": item.get("downloads") or item.get("Downloads"),
        "license": lic if isinstance(lic, str) and lic else None,
        "base_model": None,
        "gated": False,
    } for path, size, sha in files]


_ms_errors = []


def _ms_get(url):
    """A ModelScope GET that logs and skips a refused request instead of ending the run."""
    try:
        data, _ = _get(url)
        return data
    except urllib.error.HTTPError as e:
        if len(_ms_errors) < 5:
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                body = ""
            print("  modelscope %s on %s: %s" % (e.code, url[:120], body), file=sys.stderr)
        _ms_errors.append(e.code)
        return None


def build_modelscope(sleep=0.25):
    found = {}
    for term in MS_TERMS:
        for page in range(1, 3000 // MS_PAGE + 1):
            q = urllib.parse.urlencode({"search": term, "page_number": page, "page_size": MS_PAGE})
            payload = _ms_get(MS_ENDPOINT + "/openapi/v1/models?" + q)
            items = ms_items(payload) if payload else []
            if page == 1 and not items:
                print("  modelscope %s: no items; response starts %s" % (
                    term, json.dumps(payload, ensure_ascii=False)[:400]), file=sys.stderr)
            for it in items:
                rid = ms_repo_id(it) if isinstance(it, dict) else None
                if rid:
                    found.setdefault(rid, it)
            time.sleep(sleep)
            if len(items) < MS_PAGE:
                break
        print("modelscope search=%s: %d repos so far" % (term, len(found)), file=sys.stderr)
    entries = []
    for i, rid in enumerate(sorted(found)):
        url = "%s/api/v1/models/%s/repo/files?%s" % (
            MS_ENDPOINT, urllib.parse.quote(rid, safe="/"),
            urllib.parse.urlencode({"Revision": "master", "Recursive": "True"}))
        files = ms_files(_ms_get(url) or {})
        entries += ms_entries(found[rid], files)
        if (i + 1) % 100 == 0:
            print("  modelscope files %d/%d" % (i + 1, len(found)), file=sys.stderr)
        time.sleep(sleep)
    return entries


def dump(index):
    """One file per line, so a weekly refresh is a readable diff."""
    head = {k: v for k, v in index.items() if k != "files"}
    lines = [json.dumps(f, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for f in index["files"]]
    body = json.dumps(head, sort_keys=True, ensure_ascii=False, indent=1)[:-2]
    return body + ',\n "files": [\n' + ",\n".join(lines) + "\n ]\n}\n"


def build(sleep=0.25, with_modelscope=True):
    repos = {}
    for kind, term in QUERIES:
        url, pages = list_url(kind, term), 0
        while url:
            data, link = _get(url)
            pages += 1
            for m in data or []:
                if has_rkllm(m) and not m.get("private"):
                    repos.setdefault(m["id"], m)
            url = next_link(link)
            time.sleep(sleep)
        print("%s=%s: %d page(s), %d repos with .rkllm so far" % (kind, term, pages, len(repos)), file=sys.stderr)

    files = []
    for i, rid in enumerate(sorted(repos)):
        detail, _ = _get(ENDPOINT + "/api/models/" + urllib.parse.quote(rid, safe="/") + "?blobs=true")
        files += files_from_detail(repos[rid], detail)
        if (i + 1) % 100 == 0:
            print("  details %d/%d" % (i + 1, len(repos)), file=sys.stderr)
        time.sleep(sleep)

    hf_count = len(files)
    ms = []
    if with_modelscope:
        try:
            ms = build_modelscope(sleep)
        except Exception as e:      # ModelScope must never cost us the Hugging Face index
            print("modelscope failed: %s: %s" % (type(e).__name__, e), file=sys.stderr)
    files += ms
    files.sort(key=lambda f: (f["repo"].lower(), f["path"], f["source"]))
    return {
        "schema": 1,
        "generated": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
        "source": ENDPOINT,
        "sources": {"huggingface": hf_count, "modelscope": len(ms)},
        "note": "Files published by their authors on Hugging Face and ModelScope. npuzoo lists and links "
                "them; it has not tested them. Claims (chip, format, toolkit) come from file names.",
        "repos": len({(f["source"], f["repo"]) for f in files}),
        "files": files,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="index/community.json")
    ap.add_argument("--no-modelscope", action="store_true")
    args = ap.parse_args(argv)
    index = build(with_modelscope=not args.no_modelscope)
    if len(index["files"]) < 50:
        # a broken API or a rate-limit wall should not wipe a good index
        print("only %d files found; refusing to overwrite %s" % (len(index["files"]), args.out), file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(dump(index))
    print("wrote %s: %d files in %d repos (%s)" % (args.out, len(index["files"]), index["repos"],
                                                  index.get("sources")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
