"""npuzoo doctor --pc — the PC where you convert models with rkllm-toolkit.

Conversion happens on an x86 Linux machine, not on the board, and it has its
own ways to fail before a model is even loaded. Each check here comes from
something that actually broke, mostly in npuzoo's own conversion matrix
(docs/conversion-matrix.md, public GitHub Actions logs).
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys

from .known_issues import REPO

PC_OK, PC_WARN, PC_FAIL, PC_INFO = "OK", "WARN", "FAIL", "INFO"
PC_ICON = {PC_OK: "✓", PC_WARN: "!", PC_FAIL: "✗", PC_INFO: "·"}

# Python versions Rockchip ships wheels for (rkllm-toolkit/packages at each tag).
WHEEL_PYTHONS = {
    "1.3.1": ["3.10", "3.11", "3.12"], "1.3.0": ["3.9", "3.10", "3.11", "3.12"],
    "1.2.3": ["3.9", "3.10", "3.11", "3.12"], "1.2.1": ["3.8", "3.9", "3.10", "3.11", "3.12"],
    "1.1.4": ["3.8", "3.10"],
}

# Peak memory while converting at float32, measured in the conversion matrix
# on a 4-core, 16 GB runner: Qwen3-0.6B about 7 GB, Qwen2.5-1.5B about 13 GB.
# A straight line through those: about 3 GB plus 6.5 GB per billion parameters.
def conversion_peak_gb(params_b):
    return 3.0 + 6.5 * params_b


def largest_convertible_b(mem_gb):
    return max(0.0, (mem_gb - 3.0) / 6.5)


def _dist_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _dist_requires(name):
    try:
        from importlib.metadata import requires
        return requires(name) or []
    except Exception:
        return []


def _has_module(name):
    try:
        import importlib.util
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _pyarrow_has_pyextensiontype():
    try:
        import pyarrow
        return hasattr(pyarrow, "PyExtensionType")
    except Exception:
        return None


def _mem_gb():
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"MemTotal:\s+(\d+)", f.read())
        return round(int(m.group(1)) / 1048576, 1)
    except Exception:
        return None


def _gpu():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def collect_pc():
    info = {
        "machine": platform.machine(),
        "system": platform.system(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "mem_gb": _mem_gb(),
        "disk_free_gb": None,
        "gpu": _gpu(),
        "toolkit": _dist_version("rkllm-toolkit"),
        "requires": _dist_requires("rkllm-toolkit"),
        "installed": {},
        "pkg_resources": _has_module("pkg_resources"),
        "pyarrow_pyextensiontype": None,
    }
    try:
        info["disk_free_gb"] = round(shutil.disk_usage(os.getcwd()).free / 1e9, 1)
    except Exception:
        pass
    for req in info["requires"]:
        name = re.split(r"[<>=!~ ;\[]", req, maxsplit=1)[0].strip()
        if name and name not in info["installed"]:
            info["installed"][name] = _dist_version(name)
    if info["toolkit"] and _dist_version("datasets"):
        info["pyarrow_pyextensiontype"] = _pyarrow_has_pyextensiontype()
    return info


def _pins(requires):
    """{name: version} for the exact (==) pins in a wheel's requirements."""
    out = {}
    for req in requires:
        req = req.split(";")[0]
        m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*==\s*([\w.+]+)\s*$", req)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _norm(v):
    return (v or "").split("+")[0]


def diagnose_pc(info):
    checks = []

    def add(status, name, detail, fix=None):
        checks.append({"status": status, "name": name, "detail": detail, "fix": fix})

    machine = (info.get("machine") or "").lower()
    if info.get("system") != "Linux":
        add(PC_FAIL, "system", "%s. Rockchip ships rkllm-toolkit for Linux only." % info.get("system"),
            fix="Use a Linux machine or VM (WSL2 on Windows works for many people).")
    if machine in ("x86_64", "amd64"):
        add(PC_OK, "cpu", "x86_64")
    else:
        add(PC_FAIL, "cpu", "%s. rkllm-toolkit wheels are built for x86_64 only — you cannot convert "
            "models on the board itself." % (machine or "unknown"),
            fix="Convert on an x86_64 Linux PC or cloud VM, then copy the .rkllm file to the board.")

    tk, py = info.get("toolkit"), ".".join(info["python"].split(".")[:2])
    if tk:
        add(PC_OK, "rkllm-toolkit", "version %s" % tk)
        ok_py = WHEEL_PYTHONS.get(tk)
        if ok_py and py not in ok_py:
            add(PC_WARN, "python", "Python %s, but Rockchip ships toolkit %s for Python %s only." % (
                py, tk, ", ".join(ok_py)))
        else:
            add(PC_OK, "python", "Python %s" % info["python"])
        add(PC_INFO, "pairing", "Models you convert here need runtime %s on the board (librkllmrt.so). "
            "Check the board with: npuzoo doctor" % tk)
    else:
        add(PC_WARN, "rkllm-toolkit", "Not installed in this Python (%s)." % info["python"],
            fix="Get the wheel for your Python from https://github.com/airockchip/rknn-llm "
                "(rkllm-toolkit/packages). Current release 1.3.1 has wheels for Python %s."
                % ", ".join(WHEEL_PYTHONS["1.3.1"]))

    if tk and not info.get("pkg_resources"):
        add(PC_FAIL, "setuptools", "pkg_resources is missing; RKLLM() imports it when it starts, so every "
            "conversion fails with \"No module named 'pkg_resources'\".", fix='pip install "setuptools<80"')
    if info.get("pyarrow_pyextensiontype") is False:
        ds = (info.get("installed") or {}).get("datasets") or "?"
        if ds.startswith("2."):
            add(PC_FAIL, "pyarrow", "datasets %s needs pyarrow.PyExtensionType, which this pyarrow no longer "
                "has; importing the toolkit fails." % ds, fix='pip install "pyarrow<15"')

    pins = _pins(info.get("requires") or [])
    drift = []
    for name, want in sorted(pins.items()):
        have = (info.get("installed") or {}).get(name)
        if have is None:
            drift.append("%s missing (wants %s)" % (name, want))
        elif _norm(have) != _norm(want):
            drift.append("%s %s (wants %s)" % (name, have, want))
    if drift:
        add(PC_WARN, "dependencies", "Not what the toolkit pins: " + "; ".join(drift[:6])
            + (" …" if len(drift) > 6 else ""),
            fix="Use a fresh virtualenv for each toolkit version, and install the wheel last.")
    elif pins:
        add(PC_OK, "dependencies", "%d pinned dependencies match." % len(pins))

    mem = info.get("mem_gb")
    if mem:
        b = largest_convertible_b(mem)
        detail = "%s GB RAM: models up to about %.1fB parameters at float32 " % (mem, b)
        detail += "(measured: 0.6B needs about 7 GB, 1.5B about 13 GB)."
        if b < 1.5:
            add(PC_WARN, "memory", detail, fix="Add swap, or convert with dtype='float16' in load_huggingface "
                "(roughly half the memory, at some precision cost), or use a bigger machine.")
        else:
            add(PC_OK, "memory", detail + " 4B models need about 30 GB.")
    if info.get("gpu"):
        add(PC_INFO, "gpu", "%s — load_huggingface(device='cuda') is faster than the CPU." % info["gpu"])
    else:
        add(PC_INFO, "gpu", "No NVIDIA GPU: conversion runs on the CPU. On 4 cores, a 1.5B model "
            "took 35–45 minutes per target in our runs.")
    disk = info.get("disk_free_gb")
    if disk is not None and disk < 20:
        add(PC_WARN, "disk", "%s GB free here. A 2B model needs about 4 GB to download plus 2–3 GB "
            "per converted file." % disk)
    return checks


def run_pc(as_json=False):
    info = collect_pc()
    checks = diagnose_pc(info)
    fails = sum(1 for c in checks if c["status"] == PC_FAIL)
    if as_json:
        print(json.dumps({"info": info, "checks": checks}, ensure_ascii=False, indent=2))
        return 1 if fails else 0
    print("npuzoo doctor --pc   (the machine that converts models)")
    print("─" * 64)
    for c in checks:
        print(" %s %-15s %s" % (PC_ICON[c["status"]], c["name"], c["detail"]))
        if c.get("fix"):
            print("   ↳ fix: %s" % c["fix"])
    print("─" * 64)
    print(" Conversion failed anyway? Pipe its output through:  npuzoo explain")
    print(" Which release supports your model:  npuzoo support <model>")
    print(" Stuck? %s/discussions" % REPO)
    return 1 if fails else 0
