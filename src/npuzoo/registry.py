"""npuzoo registry — package index, pull, list.

v0.1: index is a JSON file (local path or URL). Hosted registry later keeps
the same schema, served from registry.npuzoo.dev. Weights live on HF/S3; the
index stores URLs + sha256, so the registry stays tiny and auditable.

Index schema (v1):
{
  "schema": 1,
  "packages": [
    {
      "name": "qwen3-1.7b",
      "display": "Qwen3 1.7B Instruct",
      "chip": "rk3588",
      "backend": "rkllm",                  # rkllm | rknn | cpu-gguf
      "quant": "w8a8",
      "requires": {"npu_driver": ">=0.9.6", "rkllmrt": "==1.2.3"},
      "context": 4096,
      "files": [{"url": "...", "sha256": "...", "bytes": 123}],
      "bench": {"npu_tps": 12.4, "cpu_tps": 7.9, "npu_w": 5.1, "cpu_w": 9.8,
                "board": "Orange Pi 5 Plus 16GB", "date": "2026-11-20"},
      "recommend": "npu",                  # honest pick: npu | cpu
      "license": "apache-2.0",
      "card": "https://..."
    }
  ]
}
"""
import hashlib
import json
import os
import sys
import urllib.request

from . import USER_AGENT
from .doctor import collect

CACHE = os.path.expanduser(os.environ.get("NPUZOO_HOME", "~/.npuzoo"))
DEMO_INDEX = os.path.join(os.path.dirname(__file__), "data", "index.demo.json")


def _load_index(src):
    if src is None:
        src = os.environ.get("NPUZOO_INDEX", DEMO_INDEX)
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), src
    with open(src) as f:
        return json.load(f), src


def _match(pkg, chip):
    return chip is None or pkg.get("chip") in (chip, "any")


def cmd_list(index_src):
    idx, src = _load_index(index_src)
    chip = collect().get("chip")
    rows = [p for p in idx.get("packages", []) if _match(p, chip)]
    if not rows:
        print(f"No packages for chip={chip or 'unknown'} in {src}")
        return 1

    def s(v):
        return "-" if v in (None, "") else str(v)

    print(f"{'NAME':<18} {'BACKEND':<9} {'QUANT':<6} {'CTX':<6} {'NPU t/s':<8} {'CPU t/s':<8} REC")
    for p in rows:
        b = p.get("bench") or {}
        print(f"{p['name']:<18} {s(p.get('backend')):<9} {s(p.get('quant')):<6} "
              f"{s(p.get('context')):<6} {s(b.get('npu_tps')):<8} {s(b.get('cpu_tps')):<8} "
              f"{s(p.get('recommend'))}")
    return 0


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_pull(name, index_src):
    idx, _ = _load_index(index_src)
    pkg = next((p for p in idx.get("packages", []) if p["name"] == name), None)
    if not pkg:
        print(f"Package '{name}' not found. Try: npuzoo list")
        return 1
    chip = collect().get("chip")
    if chip and pkg.get("chip") not in (chip, "any"):
        print(f"'{name}' targets {pkg.get('chip')}, this board is {chip}.")
        return 1
    dest = os.path.join(CACHE, "models", pkg["name"])
    os.makedirs(dest, exist_ok=True)
    for f in pkg.get("files", []):
        out = os.path.join(dest, os.path.basename(f["url"].split("?")[0]))
        if os.path.exists(out) and f.get("sha256") and _sha256(out) == f["sha256"]:
            print(f"✓ {os.path.basename(out)} (cached)")
            continue
        print(f"↓ {f['url']}")
        req = urllib.request.Request(f["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as w:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                w.write(chunk)
        if f.get("sha256") and _sha256(out) != f["sha256"]:
            print(f"✗ checksum mismatch for {out}; deleting.")
            os.remove(out)
            return 1
        print(f"✓ {os.path.basename(out)}")
    print(f"\nPulled '{name}' → {dest}")
    b = pkg.get("bench") or {}
    if b:
        print(f"Measured on {b.get('board')}: NPU {b.get('npu_tps')} t/s @ {b.get('npu_w')} W · "
              f"CPU {b.get('cpu_tps')} t/s @ {b.get('cpu_w')} W → recommend {pkg.get('recommend','?').upper()}")
    print("Run instructions are in the package's model card.")
    return 0
