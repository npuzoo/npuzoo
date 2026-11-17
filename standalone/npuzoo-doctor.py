#!/usr/bin/env python3
# npuzoo doctor — standalone, generated file. Do not edit.
# Source: https://github.com/npuzoo/npuzoo  (src/npuzoo/, tools/build_standalone.py)
# Apache-2.0
#
#   python3 npuzoo-doctor.py              # check this board
#   python3 npuzoo-doctor.py --json       # machine-readable
#   python3 npuzoo-doctor.py --explain f  # read an RKLLM/RKNN log instead
#
# Reads only /proc, /sys and the runtime .so files. Sends nothing anywhere.

import sys

# --------------------------------------------------------------------
# from src/npuzoo/known_issues.py
# --------------------------------------------------------------------
"""A knowledge base of real RKLLM / RKNPU failure signatures.

Every entry here was taken from a log someone actually posted publicly
(upstream issues, Hugging Face model cards, vendor docs) — not invented.
`docs/UPSTREAM.md` lists where each family of signatures came from.

Used by two things:
  * `npuzoo doctor`  — to phrase its fixes the same way
  * `npuzoo explain` — paste a log, get the diagnosis

Keep `match` patterns narrow. A false positive here sends someone down the
wrong road, which is worse than saying nothing.
"""
import re

REPO = "https://github.com/npuzoo/npuzoo"
DOC = REPO + "/blob/main/docs/fixes.md"

# severity
BLOCKER, PROBLEM, NOISE = "blocker", "problem", "noise"

ISSUES = [
    {
        "id": "driver-too-old",
        "severity": PROBLEM,
        "match": [r"rknpu driver version is too low",
                  r"please upgrade to 0\.9\.\d"],
        "title": "RKNPU kernel driver is older than the runtime wants",
        "why": (
            "The RKLLM runtime checks the kernel driver version at init. Older drivers "
            "(0.8.x, and 0.9.x below the runtime's minimum) either refuse large models or "
            "fail later during weight allocation. The warning is often the real cause of "
            "the error printed a few lines further down."
        ),
        "fix": [
            "Check what you have:  cat /sys/kernel/debug/rknpu/version   (needs root)",
            "Debian/Ubuntu images from Radxa:  sudo apt update && sudo apt install rknpu2-rk3588",
            "  (RK356x boards:  sudo apt install rknpu2-rk356x)",
            "Otherwise the driver ships with the kernel — update to the board vendor's",
            "  current image/kernel. Aim for 0.9.8; 0.9.6 is the practical floor.",
        ],
    },
    {
        "id": "npu-oom",
        "severity": BLOCKER,
        "match": [r"failed to allocate handle.*errno:\s*12",
                  r"can ?not create weight memory for domain",
                  r"failed to malloc npu memory"],
        "title": "Out of memory allocating NPU weights",
        "why": (
            "The model does not fit. On RK3588 the published dtype is w8a8, so a model "
            "needs roughly 1 GB of RAM per billion parameters, plus the KV cache, plus "
            "whatever else is running. A 3B VLM lands around 9-10 GB in practice, a 7B "
            "around 11-12 GB. An old driver makes this worse, so check the driver first "
            "if the 'driver version is too low' warning is also present."
        ),
        "fix": [
            "Smaller model, or a 16 GB board. 8 GB boards top out around 3B at w8a8.",
            "Lower max_context_len — the KV cache is a large part of the footprint.",
            "Free RAM first: stop the desktop session, check `free -h`.",
            "w4a16 would halve the weights, but Rockchip publishes it for RK3576 and",
            "  RV1126B only — not for RK3588. Do not assume it works on RK3588.",
        ],
    },
    {
        "id": "model-runtime-mismatch",
        "severity": BLOCKER,
        "match": [r"load model file error"],
        "title": "The .rkllm file and librkllmrt.so do not match",
        "why": (
            "A .rkllm file is produced by one rkllm-toolkit version and is only loadable "
            "by a matching runtime. Mixing them fails at load with no useful message. "
            "This is the single most common way a model that 'works for everyone else' "
            "fails on your board — and the reason every npuzoo package records the exact "
            "toolkit and runtime version it was built against."
        ),
        "fix": [
            "Read the versions off your own system:",
            "  strings /usr/lib/librkllmrt.so | grep -i 'rkllm-runtime version'",
            "The loader also prints both lines at init — compare:",
            "  'rkllm-runtime version: X'  vs  'rkllm-toolkit version: Y'",
            "Then either get the runtime that matches the model, or a model built for",
            "  the runtime you have. Do not mix.",
        ],
    },
    {
        "id": "unsupported-architecture",
        "severity": BLOCKER,
        "match": [r"Not support \w+For\w*CausalLM",
                  r"Not support \w+Model!"],
        "title": "rkllm-toolkit does not support this model architecture",
        "why": (
            "The toolkit converts a fixed list of architectures, read from config.json. "
            "Anything outside that list is rejected up front, however small the model is."
        ),
        "fix": [
            "Check the supported-model list for YOUR toolkit version, not the newest one.",
            "Newer toolkit releases add architectures — upgrading the toolkit is usually",
            "  the fix, but it then also needs a matching runtime on the board.",
        ],
    },
    {
        "id": "toolkit-too-old-for-model",
        "severity": BLOCKER,
        "match": [r"Not found the weight of model\.layers\.\d+\.",
                  r"WARNING: Not found the weight of"],
        "title": "Toolkit is too old for this model's weight layout",
        "why": (
            "The architecture name is recognised but the weight names are not, so the "
            "converter silently finds nothing to quantize. This is what a newer model "
            "family looks like on an older toolkit — the conversion 'succeeds' into "
            "something useless, or dies late."
        ),
        "fix": [
            "Upgrade rkllm-toolkit to the release that lists this model family, then",
            "  upgrade the runtime on the board to the same release.",
            "If no release supports it yet, it is not convertible yet. Nothing on the",
            "  board side will fix it.",
        ],
    },
    {
        "id": "rknn-model-runtime-mismatch",
        "severity": PROBLEM,
        "match": [r"RKNN Model version: [\d.]+ not match with rknn runtime version"],
        "title": "librknnrt.so is older than the .rknn file",
        "why": (
            "Same class of problem as the RKLLM one, on the RKNN side (vision and audio "
            "encoders). It often still runs, but accuracy and speed are not guaranteed "
            "and some ops fall back or misbehave."
        ),
        "fix": [
            "Replace librknnrt.so with the version matching the toolkit that exported",
            "  the .rknn, and keep them together from then on.",
            "Check what you have:  strings /usr/lib/librknnrt.so | grep librknnrt",
        ],
    },
    {
        "id": "missing-libomp",
        "severity": BLOCKER,
        "match": [r"libomp\.so[\w.]*: cannot open shared object file",
                  r"error while loading shared libraries: libomp"],
        "title": "libomp.so is missing next to librkllmrt.so",
        "why": (
            "The RKLLM runtime links against OpenMP. Some board images do not ship it, "
            "and upstream's own notes call this out as a known gotcha."
        ),
        "fix": [
            "sudo apt install libomp-dev        # on most Debian/Ubuntu board images",
            "or copy libomp.so from the aarch64 cross-toolchain into the same directory",
            "  as librkllmrt.so, then: sudo ldconfig",
        ],
    },
    {
        "id": "matmul-run-failed",
        "severity": BLOCKER,
        "match": [r"matmul\(w8a8\) run failed", r"matmul\(\w+\) run failed"],
        "title": "NPU matmul failed at runtime",
        "why": (
            "Usually downstream of something else: an old kernel driver, or a model built "
            "by a toolkit the runtime does not match. Look at the lines above this one — "
            "they normally carry the real cause."
        ),
        "fix": [
            "Check the driver version warning and the toolkit/runtime pair first.",
            "If both are clean, this is worth reporting upstream with the full log.",
        ],
    },
    {
        "id": "no-npu-node",
        "severity": BLOCKER,
        "match": [r"/dev/rknpu.*No such file",
                  r"/sys/kernel/debug/rknpu.*No such file",
                  r"rknpu.*not found"],
        "title": "No NPU device — the driver is not loaded",
        "why": (
            "The rknpu driver is a vendor kernel driver. Mainline and many 'edge'/'current' "
            "community kernels build without it, so the hardware is there and completely "
            "unreachable. Nothing in userspace fixes this."
        ),
        "fix": [
            "lsmod | grep rknpu        # loaded?",
            "sudo dmesg | grep -i npu  # did it probe and fail, or never appear?",
            "If it never appears: boot a vendor-kernel image (6.1.y on RK3588) instead",
            "  of a mainline/edge one.",
        ],
    },
    {
        "id": "debugfs-permission",
        "severity": NOISE,
        "match": [r"/sys/kernel/debug.*Permission denied"],
        "title": "debugfs needs root",
        "why": "The driver version lives in debugfs, which is root-only on most images.",
        "fix": ["sudo cat /sys/kernel/debug/rknpu/version",
                "or re-run the whole command with sudo."],
    },
    {
        "id": "init-failed",
        "severity": PROBLEM,
        "generic": True,          # suppressed when a specific blocker also matched
        "match": [r"rkllm_init failed", r"rkllm init failed"],
        "title": "rkllm_init failed — cause is further up the log",
        "why": (
            "This line is the symptom, never the cause. The runtime prints the real "
            "reason one to three lines above it: a driver warning, an allocation failure, "
            "or a model-load error."
        ),
        "fix": [
            "Re-run with more logging:  export RKLLM_LOG_LEVEL=1",
            "Then send the whole log through `npuzoo explain` again, including the lines",
            "  printed before this one.",
        ],
    },
    {
        "id": "rknn-dynamic-shape-warning",
        "severity": NOISE,
        "match": [r"query RKNN_QUERY_INPUT_DYNAMIC_RANGE error",
                  r"Query dynamic range failed"],
        "title": "Harmless: static-shape RKNN model",
        "why": "The caller asked a dynamic-shape question of a static-shape model. Ignore it.",
        "fix": ["Nothing to do."],
    },
]


SUCCESS_MARKERS = [
    r"RKLLM initialized successfully",
    r"Model init time \(ms\)",
    r"rkllm_init.*success",
]


def looks_healthy(text):
    """True when the log shows a successful init and no blocker matched."""
    if any(re.search(p, text, re.IGNORECASE) for p in SUCCESS_MARKERS):
        return not any(h["severity"] == BLOCKER for h in scan(text))
    return False


def scan(text):
    """Return the issues whose signatures appear in `text`, most severe first.

    A `generic` entry (one that only says 'something failed') is dropped when a
    specific blocker already explains the same failure.
    """
    hits = []
    for issue in ISSUES:
        for pat in issue["match"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                hits.append({**issue, "evidence": m.group(0)[:160]})
                break
    specific = any(h["severity"] == BLOCKER and not h.get("generic") for h in hits)
    if specific:
        hits = [h for h in hits if not h.get("generic")]
    order = {BLOCKER: 0, PROBLEM: 1, NOISE: 2}
    hits.sort(key=lambda h: order[h["severity"]])
    return hits


def by_id(issue_id):
    for issue in ISSUES:
        if issue["id"] == issue_id:
            return issue
    return None

# --------------------------------------------------------------------
# from src/npuzoo/doctor.py
# --------------------------------------------------------------------
"""npuzoo doctor — board / kernel / NPU driver / runtime health checks.

Design rules:
- Never crash on a missing file: every probe returns None gracefully.
- Every FAIL/WARN carries a `fix`: one copy-pasteable step or doc link.
- `--json` output is stable: scripts and the future web UI consume it.
- Say only what we have actually seen. Facts behind these checks are
  recorded, with sources, in docs/UPSTREAM.md.
"""
import glob
import json
import os
import platform
import re
import subprocess


OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"


# What Rockchip's own RKLLM release actually supports, and in which weight
# formats it publishes numbers. w4a16 is published for RK3576 and RV1126B
# only — assuming it works on RK3588 is a common and expensive mistake.
RK_CHIPS = {
    "rk3588":  {"rkllm": True,  "dtypes": ["w8a8"]},
    "rk3588s": {"rkllm": True,  "dtypes": ["w8a8"]},
    "rk3576":  {"rkllm": True,  "dtypes": ["w8a8", "w4a16", "w4a16_g128"]},
    "rk3562":  {"rkllm": True,  "dtypes": ["w8a8"]},
    "rv1126b": {"rkllm": True,  "dtypes": ["w8a8", "w4a16", "w4a16_g128"]},
    "rk3566":  {"rkllm": False, "dtypes": []},
    "rk3568":  {"rkllm": False, "dtypes": []},
}

# Kernel driver versions. The runtime warns below its own minimum; 0.9.6 is
# the practical floor people report working, 0.9.8 is what current images ship.
MIN_RKNPU_DRIVER = (0, 9, 6)
GOOD_RKNPU_DRIVER = (0, 9, 8)

DEBUGFS_VERSION = "/sys/kernel/debug/rknpu/version"


def _read(path):
    """Return file contents, or a ('error', kind) marker we can act on."""
    try:
        with open(path, "rb") as f:
            return f.read().decode(errors="replace").strip().strip("\x00")
    except PermissionError:
        return "__EACCES__"
    except OSError:
        return None


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None


def _lib_version(path, patterns):
    """Scan a shared library's strings for an embedded version."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    for pat in patterns:
        m = re.search(pat, data)
        if m:
            return m.group(1).decode()
    return None


def _find_lib(names):
    dirs = [
        "/usr/lib", "/usr/local/lib", "/usr/lib/aarch64-linux-gnu",
        "/oem/usr/lib", "/vendor/lib64", os.path.expanduser("~/.local/lib"),
    ]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    out = _run(["ldconfig", "-p"])
    if out:
        for line in out.splitlines():
            for n in names:
                if n in line and "=>" in line:
                    return line.split("=>")[-1].strip()
    return None


def _ver_tuple(s):
    m = re.search(r"(\d+)\.(\d+)\.?(\d+)?", s or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def _fits(mem_gb):
    """Largest model size that realistically loads at w8a8, given total RAM.

    Rockchip's published memory column is weights only, measured at a 128-token
    sequence. Real sessions add the KV cache and the rest of the system, and the
    reported footprints bear that out: a 7B audio VLM lands near 11.6 GB, a 3B
    vision VLM near 9.7 GB. Hence the headroom below — deliberately pessimistic,
    because a number that is too generous sends people into an allocation
    failure. Recalibrated as real boards report in.
    """
    if mem_gb is None:
        return None
    usable = mem_gb - 2.0          # OS, page cache, your shell
    if usable < 1.4:
        return "under 1B"
    return "about %.0fB" % max(1, usable / 1.45)


def collect(demo=False):
    if demo:
        return {
            "board": "Orange Pi 5 Plus", "chip": "rk3588", "os": "Armbian 24.11 (noble)",
            "kernel": "6.1.75-vendor-rk35xx", "mem_gb": 15.6,
            "npu_node": True, "npu_driver": "0.9.6", "npu_driver_error": None,
            "rknnrt": {"path": "/usr/lib/librknnrt.so", "version": "2.3.0"},
            "rkllmrt": {"path": None, "version": None},
            "cpu_governor": "ondemand", "npu_governor": "dmc_ondemand",
        }
    info = {}
    model = _read("/proc/device-tree/model") or _read("/sys/firmware/devicetree/base/model")
    info["board"] = model if model != "__EACCES__" else None
    compat = (_read("/proc/device-tree/compatible") or "")
    chip = None
    for c in RK_CHIPS:
        if c in compat.lower() or (info["board"] and c in info["board"].lower()):
            chip = c
            break
    info["chip"] = chip

    osr = _read("/etc/os-release") or ""
    m = re.search(r'PRETTY_NAME="(.+?)"', osr)
    info["os"] = m.group(1) if m else platform.platform()
    info["kernel"] = platform.release()

    try:
        mem_kb = int(re.search(r"MemTotal:\s+(\d+)", _read("/proc/meminfo") or "0").group(1))
        info["mem_gb"] = round(mem_kb / 1048576, 1)
    except Exception:
        info["mem_gb"] = None

    info["npu_node"] = (os.path.exists("/dev/rknpu")
                        or os.path.isdir("/sys/kernel/debug/rknpu")
                        or os.path.exists("/sys/class/devfreq/fdab0000.npu")
                        or bool(glob.glob("/sys/class/devfreq/*npu*")))

    drv = _read(DEBUGFS_VERSION)          # "RKNPU driver: v0.9.8"
    if drv == "__EACCES__":
        info["npu_driver"], info["npu_driver_error"] = None, "permission"
    elif drv is None:
        info["npu_driver"], info["npu_driver_error"] = None, "missing"
    else:
        m = re.search(r"v?(\d+\.\d+\.?\d*)", drv)
        info["npu_driver"] = m.group(1) if m else None
        info["npu_driver_error"] = None if m else "unparsed"

    p = _find_lib(["librknnrt.so"])
    info["rknnrt"] = {"path": p,
                      "version": _lib_version(p, [rb"librknnrt version:\s*([\d.]+)"]) if p else None}
    p = _find_lib(["librkllmrt.so"])
    info["rkllmrt"] = {"path": p,
                       "version": _lib_version(p, [rb"rkllm-runtime version:\s*([\d.]+\w*)",
                                                   rb"rkllm[\w\- ]*version[:\s]+([\d.]+)"]) if p else None}

    govs = {_read(f) for f in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_governor")}
    govs.discard(None)
    govs.discard("__EACCES__")
    info["cpu_governor"] = "/".join(sorted(govs)) if govs else None
    ngov = None
    for f in glob.glob("/sys/class/devfreq/*npu*/governor"):
        v = _read(f)
        if v and v != "__EACCES__":
            ngov = v
            break
    info["npu_governor"] = ngov
    return info


def diagnose(info):
    checks = []

    def add(status, name, detail, fix=None):
        checks.append({"status": status, "name": name, "detail": detail, "fix": fix})

    chip = info.get("chip")
    spec = RK_CHIPS.get(chip or "")
    if spec and spec["rkllm"]:
        add(OK, "board", "%s (%s)" % (info.get("board") or "unknown board", chip.upper()))
        add(INFO, "weights", "%s publishes %s for LLMs." % (chip.upper(), ", ".join(spec["dtypes"]))
            + ("" if "w4a16" in spec["dtypes"] else
               " There is no published w4a16 path here — a 4-bit model built for another chip will not help you."))
    elif spec:
        add(WARN, "board", "%s detected. Its NPU is not an RKLLM target; LLMs will run on CPU."
            % chip.upper(), fix="RKNN vision/audio models still work. See %s#boards" % DOC)
    elif chip:
        add(WARN, "board", "Detected %s, not a primary npuzoo target yet." % chip)
    else:
        add(FAIL, "board", "Not a recognized Rockchip board (or not running on the board).",
            fix="npuzoo targets RK3588/RK3588S/RK3576 first. See %s#boards" % DOC)

    add(INFO, "os", "%s · kernel %s" % (info.get("os"), info.get("kernel")))
    k = info.get("kernel") or ""
    vendor_kernel = bool(re.match(r"^(5\.10|6\.1)\b", k))
    if not vendor_kernel and spec and spec["rkllm"]:
        add(WARN, "kernel",
            "Kernel %s is not a Rockchip vendor branch. Mainline and most 'edge'/'current' "
            "community kernels are built without the rknpu driver, so the NPU is simply "
            "absent — no userspace fix exists for that." % k,
            fix="Check `lsmod | grep rknpu` first. If empty, boot a vendor-kernel (6.1.y) image. %s#kernel" % DOC)

    gb = info.get("mem_gb")
    if gb:
        fits = _fits(gb)
        if gb >= 15:
            add(OK, "memory", "%s GB RAM — fits %s at w8a8, VLMs included." % (gb, fits))
        elif gb >= 7:
            add(OK, "memory", "%s GB RAM — fits %s at w8a8. 7B models and most VLMs will not load." % (gb, fits))
        else:
            add(WARN, "memory", "%s GB RAM — fits %s at w8a8." % (gb, fits),
                fix="Pick smaller packages, and lower max_context_len: the KV cache is a big share of the footprint.")

    if info.get("npu_node"):
        add(OK, "npu-device", "NPU present")
    else:
        add(FAIL, "npu-device", "No NPU device node, no rknpu debugfs, no NPU devfreq entry.",
            fix="lsmod | grep rknpu  and  sudo dmesg | grep -i npu — then %s#npu-node" % DOC)

    drv, drv_err = info.get("npu_driver"), info.get("npu_driver_error")
    if drv:
        t = _ver_tuple(drv)
        if t and t >= GOOD_RKNPU_DRIVER:
            add(OK, "npu-driver", "rknpu driver v%s" % drv)
        elif t and t >= MIN_RKNPU_DRIVER:
            add(OK, "npu-driver", "rknpu driver v%s — above the 0.9.6 floor, but current "
                                  "runtimes ask for newer; upgrade if a model fails to allocate." % drv)
        else:
            add(WARN, "npu-driver",
                "rknpu driver v%s is below 0.9.6. Expect 'driver version is too low' at init, "
                "and allocation failures on larger models." % drv,
                fix="Radxa images: sudo apt install rknpu2-rk3588 — otherwise update the board image. %s#driver" % DOC)
    elif drv_err == "permission":
        add(INFO, "npu-driver", "Driver version needs root to read.",
            fix="sudo cat %s   (or re-run: sudo npuzoo doctor)" % DEBUGFS_VERSION)
    elif drv_err == "missing" and info.get("npu_node"):
        add(WARN, "npu-driver", "rknpu debugfs entry not readable — debugfs may not be mounted.",
            fix="sudo mount -t debugfs none /sys/kernel/debug  # then re-run")

    r = info.get("rknnrt") or {}
    if r.get("path"):
        add(OK, "librknnrt", r["path"] + (" (v%s)" % r["version"] if r.get("version") else " (version unknown)"))
    else:
        add(WARN, "librknnrt", "librknnrt.so not found — RKNN vision/audio models won't run.",
            fix="npuzoo installs it per package; or see %s#rknnrt" % DOC)

    r = info.get("rkllmrt") or {}
    if r.get("path"):
        v = r.get("version")
        add(OK, "librkllmrt", r["path"] + (" (v%s)" % v if v else " (version unknown)"))
        add(INFO, "version-pairing",
            "A .rkllm file only loads on the runtime it was built for"
            + (" — yours is v%s, so you need packages built against it." % v if v else ".")
            + " Mismatches fail with 'load model file error' and nothing more useful.")
    else:
        add(WARN, "librkllmrt", "librkllmrt.so not found — LLM packages can't run on the NPU yet.",
            fix="npuzoo pull installs the runtime matching each package. %s#rkllmrt" % DOC)

    cg, ng = info.get("cpu_governor"), info.get("npu_governor")
    if cg or ng:
        detail = "CPU governor %s" % (cg or "?") + (", NPU devfreq %s" % ng if ng else "")
        if cg and "performance" not in cg:
            add(INFO, "clocks", detail + ". Vendor benchmark figures are measured with clocks "
                                         "pinned at maximum, so your numbers will be lower — that is "
                                         "normal, and it is what npuzoo measures and reports.")
        else:
            add(OK, "clocks", detail)

    return checks


ICON = {OK: "✓", WARN: "!", FAIL: "✗", INFO: "·"}


def run_doctor(as_json=False, demo=False):
    info = collect(demo=demo)
    checks = diagnose(info)
    if as_json:
        print(json.dumps({"info": info, "checks": checks}, ensure_ascii=False, indent=2))
        return 1 if any(c["status"] == FAIL for c in checks) else 0

    print("npuzoo doctor" + (" (demo board)" if demo else ""))
    print("─" * 64)
    for c in checks:
        print(" %s %-15s %s" % (ICON[c["status"]], c["name"], c["detail"]))
        if c.get("fix"):
            for i, line in enumerate(str(c["fix"]).split("\n")):
                print("   %s %s" % ("↳ fix:" if i == 0 else "      ", line))
    fails = sum(1 for c in checks if c["status"] == FAIL)
    warns = sum(1 for c in checks if c["status"] == WARN)
    print("─" * 64)
    if fails:
        print(" %d problem(s) block the NPU. Fix the ✗ items first." % fails)
    elif warns:
        print(" NPU usable with caveats (%d warning(s))." % warns)
    else:
        print(" Board looks good. Try: npuzoo list")
    print(" Got a log that fails? Pipe it through:  npuzoo explain < your.log")
    print(" Stuck? Paste this output into %s/discussions" % REPO)
    return 1 if fails else 0

# --------------------------------------------------------------------
# from src/npuzoo/explain.py
# --------------------------------------------------------------------
"""npuzoo explain — paste an RKLLM/RKNN log, get the diagnosis.

Useful with no hardware at all: the knowledge base in known_issues.py is
built from logs people posted publicly, so this works on anyone's log.

    npuzoo explain board.log
    ./demo ... 2>&1 | npuzoo explain
"""
import sys


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



def _main(argv):
    argv = list(argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__ or "")
        print("usage: npuzoo-doctor.py [--json] [--demo] [--explain [FILE]]")
        return 0
    if "--explain" in argv:
        i = argv.index("--explain")
        path = argv[i + 1] if len(argv) > i + 1 else None
        return cmd_explain(path)
    return run_doctor(as_json="--json" in argv, demo="--demo" in argv)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
