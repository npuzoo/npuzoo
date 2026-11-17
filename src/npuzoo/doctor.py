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

from .known_issues import REPO, DOC

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
                      "version": _lib_version(p, [rb"RKNN SDK \(version:\s*([\w.]+)",
                                                  rb"librknnrt version:\s*([\d.]+)"]) if p else None}
    # The runtime version is NOT in the "rkllm-runtime version: %s" line — that is a
    # format string, filled in at runtime. The literal lives in the SDK banner:
    #   RKLLM SDK (version: 1.3.1 | target: Linux | build: 20cd29809 2026-09-28 ...)
    # Verified against every release tag from 1.1.0 to 1.3.1.
    p = _find_lib(["librkllmrt.so"])
    info["rkllmrt"] = {"path": p,
                       "version": _lib_version(p, [rb"RKLLM SDK \(version:\s*([\w.]+)",
                                                   rb"rkllm-runtime version:\s*([\d.]+\w*)"]) if p else None}

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
