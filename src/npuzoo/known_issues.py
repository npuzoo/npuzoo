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
