#!/usr/bin/env python3
"""Install one rkllm-toolkit wheel on a CPU-only x86 machine.

The wheels pin exact torch versions. A plain `pip install` pulls the CUDA
build of torch (several GB) and tries to compile auto_gptq against CUDA.
This installs the pinned torch family from PyTorch's CPU index first, builds
auto_gptq without its CUDA extension, then installs the wheel itself.

    python install_toolkit.py rkllm_toolkit-1.3.1-cp310-cp310-linux_x86_64.whl
"""
import os
import re
import subprocess
import sys
import zipfile

CPU_INDEX = "https://download.pytorch.org/whl/cpu"
TORCH_FAMILY = ("torch", "torchvision", "torchaudio")


def requirements(whl):
    """Requires-Dist lines from the wheel's METADATA."""
    with zipfile.ZipFile(whl) as z:
        meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        text = z.read(meta).decode("utf-8", "replace")
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Requires-Dist:")]


def name_of(req):
    return re.split(r"[<>=!~ ;\[]", req, maxsplit=1)[0].strip().lower().replace("_", "-")


def plan(reqs):
    """(torch-family pins, auto_gptq pin or None)."""
    torch = [r.split(";")[0].strip() for r in reqs if name_of(r) in TORCH_FAMILY]
    gptq = next((r.split(";")[0].strip() for r in reqs if name_of(r) == "auto-gptq"), None)
    return torch, gptq


def extra_pins(reqs):
    """Pins the wheel leaves out but its own dependencies need today.

    - RKLLM() imports pkg_resources; setuptools 80 and later no longer ship it.
    - Toolkits that pin datasets 2.x (1.1.x pins 2.14.6) need a pyarrow that
      still has PyExtensionType; current pyarrow has removed it.
    """
    pins = ["setuptools<80"]
    ds = next((r for r in reqs if name_of(r) == "datasets"), "")
    m = re.search(r"==\s*(\d+)\.", ds)
    if m and int(m.group(1)) < 3:
        pins.append("pyarrow<15")
    return pins


def pip(*args, env=None):
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir"] + list(args)
    print("+ " + " ".join(cmd), flush=True)
    subprocess.check_call(cmd, env=env)


def main(whl):
    reqs = requirements(whl)
    torch, gptq = plan(reqs)
    # RKLLM() imports pkg_resources, which newer setuptools no longer ships
    pip("--upgrade", "pip", "wheel", "setuptools<80")
    if torch:
        pip("--index-url", CPU_INDEX, *torch)
    if gptq:
        env = dict(os.environ, BUILD_CUDA_EXT="0")
        pip("--no-build-isolation", gptq, env=env)
    # torch is already satisfied, so this resolves the rest from PyPI
    pip("--extra-index-url", CPU_INDEX, whl, *extra_pins(reqs))
    # construct it, not just import it: the constructor is where missing
    # dependencies (pkg_resources) show up
    out = subprocess.run([sys.executable, "-c", "from rkllm.api import RKLLM; RKLLM(); print('RKLLM() ok')"],
                         capture_output=True, text=True)
    print(out.stdout + out.stderr)
    return out.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
