"""`npuzoo inspect` — check a model file before you copy it to the board.

What this can tell without a board:

  * the file is not a model at all: a Git LFS pointer, an HTML or JSON error
    page, or a GGUF file. These produce the same bare "load model file error!"
    as a version mismatch, and cost people hours.
  * the file carries the .rkllm container signature.
  * the chip, weight format and toolkit version the *filename* claims, and
    whether that chip supports that weight format at all.
  * whether the file matches an expected size or SHA-256 (Hugging Face shows
    the SHA-256 as the file's LFS object id), i.e. whether a download finished.

What it deliberately does not do: decode the .rkllm header. Past the
signature the toolkit obfuscates the header, and we do not reverse-engineer a
vendor's format. The runtime itself reports toolkit version and target
platform when it loads a model; on a board, `npuzoo explain` reads that report.
See docs/rkllm-format.md.
"""
import hashlib
import json
import os
import re
import sys

from .doctor import RK_CHIPS, WARN, FAIL, INFO, collect
from .known_issues import REPO, DOC
from .models import family_for_name, supports, PLATFORMS

# Signature at offset 0 of Rockchip-format .rkllm files. Present in 43 of 44
# public files sampled on 2026-11-17: June 2024 to November 2026, toolkit
# 1.0.x to 1.3.1, RK3588 and RK3576 targets. The container field after it was
# the same in all 43, so the toolkit version is not readable from the header.
RKLLM_MAGIC = bytes.fromhex("daeeb336")
# The 44th file used the .rkllm extension for a different, third-party format
# (ASCII "RKLL", then an architecture name and a llama.cpp-style quant tag).
THIRD_PARTY_RKLL = b"RKLL"
GGUF_MAGIC = b"GGUF"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"

# A real model is hundreds of MB at the very least. Anything this small that
# still carries the signature is a broken download.
MIN_PLAUSIBLE_BYTES = 16 * 1024 * 1024

# WARN, FAIL and INFO come from doctor so the two commands share one vocabulary
PASS = "PASS"
INSPECT_ICON = {PASS: "✓", WARN: "!", FAIL: "✗", INFO: "·"}

_CHIP_RE = re.compile(r"(rk3588s|rk3588|rk3576|rk3562|rv1126b|rk3566|rk3568|rk182x|rk1820|rk1828)", re.I)
_DTYPE_RE = re.compile(r"(w4a16|w8a8|w4a8|w8a16)(?:[_-](g\d+))?", re.I)
_VER_RE = re.compile(r"(?:^|[-_v])(1\.[0-9]\.[0-9]+(?:b\d+)?)(?=$|[-_.])", re.I)


def _ver(s):
    """'1.2.1b1' -> (1, 2, 1, 0, 1); a beta sorts before its release."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:b(\d+))?$", s or "")
    if not m:
        return None
    a, b, c, beta = m.groups()
    return (int(a), int(b), int(c), 0 if beta else 1, int(beta or 0))


def sniff(head):
    """Classify the first bytes of a file."""
    stripped = head.lstrip()
    low = stripped[:64].lower()
    if head.startswith(RKLLM_MAGIC):
        return "rkllm"
    if head.startswith(THIRD_PARTY_RKLL):
        return "rkll-third-party"
    if head.startswith(GGUF_MAGIC):
        return "gguf"
    if stripped.startswith(LFS_POINTER):
        return "lfs-pointer"
    if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
        return "html"
    if stripped.startswith(b"{") and b'"error"' in stripped[:4096]:
        return "json-error"
    return "unknown"


def parse_lfs_pointer(text):
    """Return (sha256, size) from a Git LFS pointer, either may be None."""
    oid = re.search(r"oid sha256:([0-9a-f]{64})", text)
    size = re.search(r"^size (\d+)", text, re.M)
    return (oid.group(1) if oid else None, int(size.group(1)) if size else None)


def parse_name(name):
    """What the filename claims. Nothing here is verified."""
    base = os.path.basename(name)
    out = {"chip": None, "dtype": None, "group": None, "toolkit": None}
    m = _CHIP_RE.search(base)
    if m:
        out["chip"] = m.group(1).lower()
    m = _DTYPE_RE.search(base)
    if m:
        out["dtype"] = m.group(1).lower()
        out["group"] = m.group(2).lower() if m.group(2) else None
    m = _VER_RE.search(base)
    if m:
        out["toolkit"] = m.group(1)
    return out


def sha256_of(path, chunk=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def check_claims(claimed, board=None, runtime=None, family=None):
    """Check what a name claims (chip, weight format, toolkit) against a board and runtime.

    Used by inspect for a file on disk and by find for files not yet downloaded.
    """
    findings = []

    def add(status, check, detail, fix=None):
        findings.append({"status": status, "check": check, "detail": detail, "fix": fix})

    chip, dtype = claimed["chip"], claimed["dtype"]
    if not chip and not dtype:
        add(INFO, "filename", "The name does not say which chip or weight format it was built for.",
            fix=["Ask the uploader, or load it on the board and run: npuzoo explain"])
    if chip in ("rk1820", "rk1828", "rk182x"):
        add(WARN, "target", "Built for the %s AI co-processor, not for the NPU inside RK3588/RK3576." % chip.upper())
    elif chip:
        spec = RK_CHIPS.get(chip)
        if spec and not spec["rkllm"]:
            add(FAIL, "target", "%s has no RKLLM support; no .rkllm model runs on it." % chip.upper(),
                fix=["Use an RK3588, RK3576, RK3562 or RV1126B board for language models. See %s#boards" % DOC])
        elif spec and dtype and dtype not in [d.split("_")[0] for d in spec["dtypes"]]:
            add(FAIL, "weight format",
                "The name says %s on %s. Rockchip publishes %s for %s only." % (
                    dtype, chip.upper(), " / ".join(sorted(set(d.split("_")[0] for d in spec["dtypes"]))), chip.upper()),
                fix=["Get a %s build of the model for %s." % (spec["dtypes"][0], chip.upper())])
        elif spec and dtype:
            add(PASS, "weight format", "%s%s is a published format for %s." % (
                dtype, ("_" + claimed["group"]) if claimed["group"] else "", chip.upper()))
    if claimed["group"]:
        add(INFO, "weight format", "Group-wise quantization (%s) needs runtime 1.1.0 or newer." % claimed["group"])

    if board:
        b = board.lower()
        if chip and chip not in ("rk1820", "rk1828", "rk182x") and not (b == chip or (b, chip) in (("rk3588s", "rk3588"), ("rk3588", "rk3588s"))):
            add(FAIL, "target", "The name says %s, but this board is %s. The runtime will refuse it with "
                "\"The model's target_platform does not match the real platform\"." % (chip.upper(), b.upper()),
                fix=["Get the %s build of this model." % b.upper()])

    tk = claimed["toolkit"]
    if tk and runtime:
        if _ver(tk) and _ver(runtime) and _ver(tk) > _ver(runtime):
            add(FAIL, "versions", "The name says toolkit %s, newer than runtime %s. The runtime will refuse it." % (tk, runtime),
                fix=["Upgrade the runtime to %s or newer, or get a build made with toolkit %s." % (tk, runtime)])
        elif _ver(tk) and _ver(runtime) and _ver(tk)[:2] < _ver(runtime)[:2]:
            add(WARN, "versions",
                "The name says toolkit %s; your runtime is %s. Rockchip does not document which older "
                "models newer runtimes still load. If you see 'The model version is too old', re-convert." % (tk, runtime))
        elif _ver(tk) and _ver(runtime):
            add(PASS, "versions", "Toolkit %s in the name fits runtime %s." % (tk, runtime))
    elif not tk:
        add(INFO, "versions", "The toolkit version is not in the name and is not readable from the file. "
            "The runtime prints it when it loads the model; send that log to: npuzoo explain")

    # What Rockchip's changelog says each release supports (models.py).
    since = (family or {}).get("since")
    if since:
        name = family["name"]
        if runtime and supports(runtime, since) is False:
            add(FAIL, "model family", "This looks like %s, which Rockchip added in RKLLM %s. "
                "Runtime %s cannot run it." % (name, since, runtime),
                fix=["Upgrade the board's runtime (librkllmrt.so) to %s or newer, with a model built by the "
                     "same toolkit version." % since])
        if tk and supports(tk, since) is False:
            add(WARN, "model family", "The name says toolkit %s, but Rockchip added %s in %s, so the version in "
                "the name is probably wrong. The runtime prints the real one when it loads the model." % (tk, name, since))
    if board and runtime:
        b = board.lower()
        psince = PLATFORMS.get(b)
        if psince and supports(runtime, psince) is False:
            add(FAIL, "board", "%s support arrived in RKLLM %s; runtime %s predates it." % (b.upper(), psince, runtime),
                fix=["Upgrade the runtime to %s or newer." % psince])
    return findings


def inspect_file(path, board=None, runtime=None, expect_sha256=None, expect_size=None, name=None):
    """Return a list of findings: dicts with status, check, detail, fix."""
    findings = []

    def add(status, check, detail, fix=None):
        findings.append({"status": status, "check": check, "detail": detail, "fix": fix})

    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError as e:
        add(FAIL, "file", "cannot read %s: %s" % (path, e.strerror or e))
        return findings

    kind = sniff(head)
    claimed = parse_name(name or path)

    if kind == "lfs-pointer":
        oid, real = parse_lfs_pointer(head.decode("utf-8", "replace"))
        add(FAIL, "file type",
            "This is a Git LFS pointer (%d bytes), not the model. The real file is %s." % (
                size, ("%.2f GB" % (real / 1e9)) if real else "elsewhere"),
            fix=["git lfs install && git lfs pull      # inside the cloned repo",
                 "or download the file itself: https://huggingface.co/<repo>/resolve/main/<file>"])
        return findings
    if kind == "html":
        add(FAIL, "file type", "This is a web page, not a model — the download saved an error or login page.",
            fix=["Download from the 'resolve' URL, not the 'blob' page URL:",
                 "  https://huggingface.co/<repo>/resolve/main/<file>"])
        return findings
    if kind == "json-error":
        add(FAIL, "file type", "This is a JSON error response, not a model — the server refused the download.",
            fix=["Check the repo is public, or log in (huggingface-cli login) for gated repos."])
        return findings
    if kind == "gguf":
        add(FAIL, "file type",
            "This is a GGUF file (llama.cpp format). Rockchip's NPU runtime only loads .rkllm files.",
            fix=["Run GGUF on the CPU with llama.cpp or Ollama,",
                 "or get the .rkllm build of the same model for the NPU: npuzoo list"])
        return findings
    if kind == "rkll-third-party":
        m = re.match(rb"RKLL.{4}([a-z0-9_]{2,24})", head, re.S)
        arch = m.group(1).decode() if m else None
        add(WARN, "file type",
            "Named .rkllm, but this is not Rockchip's format: it starts with 'RKLL'%s, a format made for a "
            "third-party runtime. Rockchip's runtime (librkllmrt) will most likely refuse it with "
            "\"load model file error!\"." % ((" and names the architecture '%s'" % arch) if arch else ""),
            fix=["Load it with the runtime its uploader names (read the model page),",
                 "or get a build made with Rockchip's rkllm-toolkit."])
        return findings
    if kind == "unknown":
        if path.lower().endswith(".rknn"):
            add(INFO, "file type",
                "An .rknn file: a vision or audio model for the RKNN runtime, not a language model for RKLLM.")
        else:
            add(WARN, "file type",
                "No Rockchip .rkllm signature at the start of the file. 43 of 44 public .rkllm files we "
                "sampled carry it, so Rockchip's runtime will most likely refuse this one.",
                fix=["If it came from a converter that failed, re-run the conversion and check its log."])
        return findings

    add(PASS, "file type", ".rkllm signature present (%.2f GB)." % (size / 1e9))

    if size < MIN_PLAUSIBLE_BYTES:
        add(FAIL, "size", "Only %d bytes — far too small for a model. The download stopped early." % size,
            fix=["Download it again and compare the size with the one listed on the model page."])
    if expect_size is not None:
        if size == expect_size:
            add(PASS, "size", "Matches the expected %d bytes." % expect_size)
        else:
            add(FAIL, "size", "%d bytes, expected %d. The download is incomplete or a different file." % (
                size, expect_size), fix=["Download it again."])
    if expect_sha256:
        got = sha256_of(path)
        if got == expect_sha256.lower():
            add(PASS, "checksum", "SHA-256 matches.")
        else:
            add(FAIL, "checksum", "SHA-256 does not match the expected value. The file is corrupt or not the one published.",
                fix=["Download it again; on Hugging Face the expected value is the LFS 'oid sha256' of the file."])

    # What the filename claims, checked against what the chip can do.
    findings.extend(check_claims(claimed, board=board, runtime=runtime,
                                 family=family_for_name(name or path)))
    return findings


def cmd_inspect(path, board=None, runtime=None, expect_sha256=None, expect_size=None, as_json=False):
    if board is None and os.path.exists("/proc/device-tree/compatible"):
        try:
            board = collect().get("chip")
        except Exception:
            board = None
    findings = inspect_file(path, board=board, runtime=runtime,
                            expect_sha256=expect_sha256, expect_size=expect_size)
    worst = 0 if not any(f["status"] == FAIL for f in findings) else 1
    if as_json:
        print(json.dumps({"file": path, "board": board, "findings": findings}, ensure_ascii=False, indent=2))
        return worst
    print("npuzoo inspect  %s" % path)
    if board:
        print("  board: %s" % board.upper())
    for f in findings:
        print("  %s %-14s %s" % (INSPECT_ICON[f["status"]], f["check"], f["detail"]))
        for line in (f["fix"] or []):
            print("      %s" % line)
    if worst:
        print("\nProblems above will stop the model from loading. More help: %s/issues" % REPO)
    return worst
