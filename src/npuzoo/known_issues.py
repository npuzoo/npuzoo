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
        "id": "runtime-older-than-toolkit",
        "severity": BLOCKER,
        "match": [r"rkllm-runtime version is lower than the rkllm-toolkit version"],
        "title": "Runtime is older than the toolkit that built this model",
        "why": (
            "The precise form of the pairing problem, and the runtime tells you so outright: "
            "the model was converted by a newer rkllm-toolkit than the librkllmrt.so on this "
            "board. The message names the minimum runtime version you need."
        ),
        "fix": [
            "Read the version it asks for from the message itself, then install that runtime.",
            "Check what you have:  strings /usr/lib/librkllmrt.so | grep 'RKLLM SDK'",
            "Upgrading the runtime is normally easier than re-converting the model.",
        ],
    },
    {
        "id": "model-too-old",
        "severity": PROBLEM,
        "match": [r"model version is too old, please use the latest toolkit"],
        "title": "The .rkllm file predates this runtime",
        "why": (
            "The other direction: the runtime is newer than the file. Older model formats are "
            "dropped over time, so a .rkllm someone published a year ago may simply no longer "
            "load. Most community model repos never state which toolkit built their files."
        ),
        "fix": [
            "Re-convert from the original weights with a toolkit matching your runtime.",
            "Or install the older runtime the file was built for, if you can identify it.",
        ],
    },
    {
        "id": "wrong-target-platform",
        "severity": BLOCKER,
        "match": [r"model's target_platform does not match the real platform"],
        "title": "This model was built for a different chip",
        "why": (
            "A .rkllm records its target chip. An RK3576 package will not run on RK3588 and "
            "vice versa — the NPU layouts differ. Model repos frequently fail to say which "
            "chip a file targets, so this is easy to hit by downloading the wrong one."
        ),
        "fix": [
            "Check your chip:  npuzoo doctor",
            "Then get the package built for it. npuzoo checks this before downloading.",
        ],
    },
    {
        "id": "unsupported-rope",
        "severity": BLOCKER,
        "match": [r"unsupported rope type was detected"],
        "title": "Runtime too old for this model's positional encoding",
        "why": (
            "The model uses a RoPE variant this runtime does not implement. It is a capability "
            "gap, not a configuration mistake — newer model families keep introducing these."
        ),
        "fix": ["Upgrade librkllmrt.so to the release that supports this model family.",
                "If the newest runtime still refuses it, the model is not convertible yet."],
    },
    {
        "id": "kv-cache-alloc-failed",
        "severity": BLOCKER,
        "match": [r"Failed to allocate buffer for kv cache",
                  r"Failed to allocate compute buffers"],
        "title": "Out of memory for the KV cache, not the weights",
        "why": (
            "The weights loaded; the context did not. The KV cache grows with max_context_len, "
            "and it is allocated separately — which is why a model that 'fits' still dies when "
            "you raise the context."
        ),
        "fix": [
            "Lower max_context_len. Halving it roughly halves the cache.",
            "Check free RAM at the moment of failure:  free -h",
            "This is the first thing to try before concluding the model is too big.",
        ],
    },
    {
        "id": "context-too-small",
        "severity": PROBLEM,
        "match": [r"Max_context\[\d+\] must be less than the model's max_context_limit",
                  r"The length of prompt is greater than max context",
                  r"The context is not enough! history_s"],
        "title": "Context length misconfigured or exceeded",
        "why": (
            "max_context_limit is baked in at conversion time; you cannot raise it at runtime "
            "past that ceiling. Conversions before runtime 1.2.0 were commonly capped at 4096, "
            "so an old package cannot be given a long context no matter what you pass."
        ),
        "fix": [
            "The ceiling is printed at init as max_context_limit — you cannot exceed it.",
            "To go higher, re-convert with a larger limit (1.2.0 and later support up to 16K).",
            "If the prompt itself is too long, trim it or raise max_context within the ceiling.",
        ],
    },
    {
        "id": "invalid-model-file",
        "severity": BLOCKER,
        "match": [r"Invalid magic number, got",
                  r"magic does not match the current model",
                  r"Invalid rkllm model!"],
        "title": "Not a valid .rkllm file",
        "why": (
            "Usually a truncated or partial download, a Git LFS pointer committed instead of "
            "the real file, or an HTML error page saved under a .rkllm name."
        ),
        "fix": [
            "Check the size and the first bytes:  ls -l model.rkllm && head -c 64 model.rkllm | xxd",
            "A few hundred bytes of text means you downloaded a pointer or an error page.",
            "Re-download and verify the checksum. npuzoo pull verifies sha256 for you.",
        ],
    },
    {
        "id": "unsupported-architecture-runtime",
        "severity": BLOCKER,
        "match": [r"model architecture \S+ is not supported by rkllm",
                  r"Unsupported model architecture"],
        "title": "Runtime does not support this architecture",
        "why": "The runtime, not the converter, is refusing it. Pair with a toolkit/runtime that lists it.",
        "fix": ["Upgrade both toolkit and runtime to a release that names this model family."],
    },
    {
        "id": "armhf-2gb-limit",
        "severity": BLOCKER,
        "match": [r"32-bit systems only support models with weights smaller than 2GB"],
        "title": "You are running a 32-bit userland",
        "why": (
            "The board is 64-bit but the OS image is armhf, which caps model weights at 2 GB. "
            "Easy to miss, because everything else works."
        ),
        "fix": ["Confirm:  uname -m   (expect aarch64, not armv7l)",
                "Reflash a 64-bit (arm64/aarch64) image. There is no workaround in userland."],
    },
    {
        "id": "cpu-affinity-misconfigured",
        "severity": PROBLEM,
        "match": [r"number of enabled CPUs must be greater than or equal to the number of NPU cores",
                  r"Expected The number of enabled CPUs between"],
        "title": "CPU core mask does not fit the NPU core count",
        "why": (
            "RK3588 drives its 3 NPU cores from CPU threads, so the enabled-CPU mask has to be "
            "at least as large as the NPU core count."
        ),
        "fix": ["Leave the CPU mask at its default unless you have measured a reason to change it.",
                "If you must set it, enable at least as many CPUs as NPU cores in use."],
    },
    {
        "id": "missing-eos-token",
        "severity": PROBLEM,
        "match": [r"Cannot find tokenizer eos token id in model file"],
        "title": "No EOS token — generation will not stop cleanly",
        "why": (
            "Without an end-of-sequence id the model runs until it hits the context limit, which "
            "looks like rambling or repetition rather than an error. A conversion-time problem, "
            "surfacing at runtime."
        ),
        "fix": [
            "Re-convert with a toolkit that reads this tokenizer correctly (1.3.0 added support",
            "  for multiple EOS token ids).",
            "As a stopgap, set a stop string in your client.",
        ],
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
        # Seen in npuzoo's own conversion matrix (public GitHub Actions logs,
        # Nov 2026): rkllm-toolkit 1.2.3 on Python 3.10 with current setuptools.
        "id": "toolkit-no-pkg-resources",
        "severity": BLOCKER,
        "match": [r"No module named 'pkg_resources'"],
        "title": "rkllm-toolkit cannot start: this setuptools no longer has pkg_resources",
        "why": (
            "The toolkit imports pkg_resources when RKLLM() is created, before any model is "
            "loaded. Recent setuptools releases removed it, so a fresh install of the toolkit "
            "fails at the first line of a conversion script even though `import rkllm` works."
        ),
        "fix": [
            "In the environment where rkllm-toolkit is installed:",
            '  pip install "setuptools<80"',
        ],
    },
    {
        # Same source: rkllm-toolkit 1.1.4, which pins datasets 2.14.6.
        "id": "toolkit-pyarrow-too-new",
        "severity": BLOCKER,
        "match": [r"module 'pyarrow' has no attribute 'PyExtensionType'"],
        "title": "rkllm-toolkit cannot import: pyarrow is too new for its datasets version",
        "why": (
            "rkllm-toolkit 1.1.x pins datasets 2.14.6 but leaves pyarrow unpinned. That "
            "datasets release subclasses pyarrow.PyExtensionType, which current pyarrow has "
            "removed, so `from rkllm.api import RKLLM` fails on a fresh install today."
        ),
        "fix": [
            "In the environment where rkllm-toolkit is installed:",
            '  pip install "pyarrow<15"',
            "Or move to toolkit 1.2.x or newer — and a runtime of the same version on the board.",
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
