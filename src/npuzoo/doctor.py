"""npuzoo doctor — board / kernel / NPU driver / runtime health checks.

Design rules:
- Never crash on a missing file: every probe returns None gracefully.
- Every FAIL/WARN carries a `fix`: one copy-pasteable step or doc link.
- `--json` output is stable: scripts and the future web UI consume it.
"""
import json
import os
import platform
import re
import subprocess

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"

DOC = "https://github.com/npuzoo/npuzoo/blob/main/docs/fixes.md"

RK_CHIPS = {
    "rk3588": {"npu_tops": 6, "rkllm": True},
    "rk3588s": {"npu_tops": 6, "rkllm": True},
    "rk3576": {"npu_tops": 6, "rkllm": True},
    "rk3566": {"npu_tops": 1, "rkllm": False},
    "rk3568": {"npu_tops": 1, "rkllm": False},
}

# Known minimums (update as rkllm releases move)
MIN_RKNPU_DRIVER = (0, 9, 6)   # rkllm runtime needs >= 0.9.6
GOOD_RKNPU_DRIVER = (0, 9, 8)


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode(errors="replace").strip().strip("\x00")
    except OSError:
        return None


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None


def _lib_version(path, pattern):
    """Scan a shared library's strings for an embedded version."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        m = re.search(pattern, data)
        return m.group(1).decode() if m else None
    except OSError:
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


def collect(demo=False):
    if demo:
        return {
            "board": "Orange Pi 5 Plus", "chip": "rk3588", "os": "Armbian 24.11 (noble)",
            "kernel": "6.1.75-vendor-rk35xx", "mem_gb": 15.6,
            "npu_node": True, "npu_driver": "0.9.6",
            "rknnrt": {"path": "/usr/lib/librknnrt.so", "version": "2.3.0"},
            "rkllmrt": {"path": None, "version": None},
        }
    info = {}
    model = _read("/proc/device-tree/model") or _read("/sys/firmware/devicetree/base/model")
    info["board"] = model
    compat = _read("/proc/device-tree/compatible") or ""
    chip = None
    for c in RK_CHIPS:
        if c in compat.lower() or (model and c in model.lower()):
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
    info["npu_node"] = os.path.exists("/dev/rknpu") or bool(
        [d for d in (os.listdir("/dev/dri") if os.path.isdir("/dev/dri") else []) if d.startswith("render")]
        and os.path.exists("/sys/kernel/debug/rknpu")
    ) or os.path.exists("/sys/kernel/debug/rknpu")
    drv = _read("/sys/kernel/debug/rknpu/version")  # "RKNPU driver: v0.9.8"
    m = re.search(r"v?([\d.]+)", drv or "")
    info["npu_driver"] = m.group(1) if m else None

    p = _find_lib(["librknnrt.so"])
    info["rknnrt"] = {"path": p, "version": _lib_version(p, rb"librknnrt version: ([\d.]+)") if p else None}
    p = _find_lib(["librkllmrt.so"])
    info["rkllmrt"] = {"path": p, "version": _lib_version(p, rb"rkllm[\w\- ]*version[:\s]+([\d.]+)") if p else None}
    return info


def diagnose(info):
    checks = []

    def add(status, name, detail, fix=None):
        checks.append({"status": status, "name": name, "detail": detail, "fix": fix})

    chip = info.get("chip")
    if chip in RK_CHIPS:
        add(OK, "board", f'{info.get("board") or "unknown board"} ({chip.upper()}, {RK_CHIPS[chip]["npu_tops"]} TOPS NPU)')
        if not RK_CHIPS[chip]["rkllm"]:
            add(WARN, "llm-support", f"{chip.upper()} NPU is too small for RKLLM; LLMs will run on CPU only.")
    elif chip:
        add(WARN, "board", f"Detected {chip}, not a primary npuzoo target yet.")
    else:
        add(FAIL, "board", "Not a recognized Rockchip board (or not running on the board).",
            fix=f"npuzoo currently targets RK3588/RK3576 boards. See {DOC}#boards")

    add(INFO, "os", f'{info.get("os")} · kernel {info.get("kernel")}')
    k = info.get("kernel") or ""
    vendor_kernel = bool(re.match(r"^(5\.10|6\.1)\b", k))
    if not vendor_kernel and chip in RK_CHIPS:
        add(WARN, "kernel",
            "Non-vendor kernel. Mainline kernels often ship without the rknpu driver "
            "(this is the classic 'no /dev/rknpu' problem on Armbian current/edge).",
            fix=f"Use the vendor branch (6.1.y) image, or see {DOC}#kernel")

    if info.get("mem_gb"):
        gb = info["mem_gb"]
        status = OK if gb >= 7 else WARN
        add(status, "memory", f"{gb} GB RAM" + ("" if gb >= 7 else " — 3B+ models will be tight; prefer ≤2B."))

    if info.get("npu_node"):
        add(OK, "npu-device", "NPU device node present")
    else:
        add(FAIL, "npu-device", "No NPU device node found.",
            fix=f"Driver missing or not loaded. Check `dmesg | grep -i rknpu`; see {DOC}#npu-node")

    drv = info.get("npu_driver")
    if drv:
        t = _ver_tuple(drv)
        if t and t >= GOOD_RKNPU_DRIVER:
            add(OK, "npu-driver", f"rknpu driver v{drv}")
        elif t and t >= MIN_RKNPU_DRIVER:
            add(OK, "npu-driver", f"rknpu driver v{drv} (meets minimum {'.'.join(map(str, MIN_RKNPU_DRIVER))})")
        else:
            add(WARN, "npu-driver", f"rknpu driver v{drv} is older than {'.'.join(map(str, MIN_RKNPU_DRIVER))}; RKLLM runtime will refuse to start.",
                fix=f"Update board image / kernel. See {DOC}#driver")
    elif info.get("npu_node"):
        add(WARN, "npu-driver", "Could not read driver version (debugfs not mounted?)",
            fix="sudo mount -t debugfs none /sys/kernel/debug  # then re-run")

    r = info.get("rknnrt") or {}
    if r.get("path"):
        add(OK, "librknnrt", f'{r["path"]}' + (f' (v{r["version"]})' if r.get("version") else ""))
    else:
        add(WARN, "librknnrt", "librknnrt.so not found — vision/speech RKNN models won't run.",
            fix=f"npuzoo pull will install it per-package; or see {DOC}#rknnrt")

    r = info.get("rkllmrt") or {}
    if r.get("path"):
        add(OK, "librkllmrt", f'{r["path"]}' + (f' (v{r["version"]})' if r.get("version") else ""))
    else:
        add(WARN, "librkllmrt", "librkllmrt.so not found — LLM packages won't run on the NPU yet.",
            fix=f"npuzoo pull installs the runtime matching each model package. {DOC}#rkllmrt")

    return checks


ICON = {OK: "✓", WARN: "!", FAIL: "✗", INFO: "·"}


def run_doctor(as_json=False, demo=False):
    info = collect(demo=demo)
    checks = diagnose(info)
    if as_json:
        print(json.dumps({"info": info, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("npuzoo doctor" + (" (demo board)" if demo else ""))
        print("─" * 56)
        for c in checks:
            print(f" {ICON[c['status']]} {c['name']:<12} {c['detail']}")
            if c.get("fix"):
                print(f"   ↳ fix: {c['fix']}")
        fails = sum(1 for c in checks if c["status"] == FAIL)
        warns = sum(1 for c in checks if c["status"] == WARN)
        print("─" * 56)
        if fails:
            print(f" {fails} problem(s) block the NPU. Fix the ✗ items first.")
        elif warns:
            print(f" NPU usable with caveats ({warns} warning(s)).")
        else:
            print(" Board looks good. Try: npuzoo list")
        print(f" Stuck? Paste this output into {DOC.replace('/blob/main/docs/fixes.md','')}/discussions")
    return 1 if any(c["status"] == FAIL for c in checks) else 0
