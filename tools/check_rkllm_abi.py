#!/usr/bin/env python3
"""Check npuzoo's ctypes layouts against an official rkllm.h, for a target ABI.

Without a board, this is the strongest check available that the binding in
src/npuzoo/rkllm_rt.py passes the runtime what it expects: every struct size
and field offset is compared with what clang computes from Rockchip's own
header for aarch64 Linux (and x86_64, as a control). No system headers are
needed: fixed-width types come from compiler builtins.

    python tools/check_rkllm_abi.py rkllm-1.3.1.h 1.3 [--target aarch64-linux-gnu]

Exit 0 when every assertion holds; the compiler's message names the first
one that does not.
"""
import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from npuzoo import rkllm_rt as rt  # noqa: E402

PREAMBLE = """
typedef __INT8_TYPE__ int8_t;   typedef __UINT8_TYPE__ uint8_t;
typedef __INT16_TYPE__ int16_t; typedef __UINT16_TYPE__ uint16_t;
typedef __INT32_TYPE__ int32_t; typedef __UINT32_TYPE__ uint32_t;
typedef __INT64_TYPE__ int64_t; typedef __UINT64_TYPE__ uint64_t;
typedef __SIZE_TYPE__ size_t;
#define offsetof(t, m) __builtin_offsetof(t, m)
"""

# header type expression -> ctypes class, per profile. MM is the multimodal
# input type whatever the header calls it (1.2.1/1.2.2 spell it "MultiModel").
COMMON = [
    ("RKLLMExtendParam", rt.RKLLMExtendParam),
    ("RKLLMEmbedInput", rt.RKLLMEmbedInput),
    ("RKLLMTokenInput", rt.RKLLMTokenInput),
    ("RKLLMLoraParam", rt.RKLLMLoraParam),
    ("RKLLMPromptCacheParam", rt.RKLLMPromptCacheParam),
    ("RKLLMResultLastHiddenLayer", rt.RKLLMResultLastHiddenLayer),
    ("RKLLMResultLogits", rt.RKLLMResultLogits),
    ("RKLLMPerfStat", rt.RKLLMPerfStat),
    ("RKLLMResult", rt.RKLLMResult),
]
TYPES = {
    "1.3": COMMON + [
        ("RKLLMParam", rt.RKLLMParam13),
        ("MM", rt.RKLLMMultiModalInput13),
        ("RKLLMInput", rt.RKLLMInput13),
        ("RKLLMSamplingParam", rt.RKLLMSamplingParam),
        ("RKLLMInferParam", rt.RKLLMInferParam13),
        ("RKLLMCallback", rt.RKLLMCallback),
    ],
    "1.2": COMMON + [
        ("RKLLMParam", rt.RKLLMParam12),
        ("MM", rt.RKLLMMultiModalInput12),
        ("RKLLMInput", rt.RKLLMInput12),
        ("RKLLMInferParam", rt.RKLLMInferParam12),
    ],
}


def _contains(cls, inner):
    """True when cls holds inner somewhere inside (directly, in a union, or deeper)."""
    for _n, ftype in getattr(cls, "_fields_", []):
        if ftype is inner or (isinstance(ftype, type) and issubclass(ftype, (ctypes.Structure, ctypes.Union))
                              and _contains(ftype, inner)):
            return True
    return False


def assertions(profile, header_text):
    """static_assert lines for every size and offset; members the header lacks are skipped."""
    out = []
    short = set()     # our classes that hold fields this header does not have
    for cname, cls in TYPES[profile]:
        names = [n for n, _ in cls._fields_ if n not in getattr(cls, "_anonymous_", ())]
        if any(not re.search(r"\b%s\b" % re.escape(n), header_text) for n in names):
            short.add(cls)
    for cname, cls in TYPES[profile]:
        fields = []
        for name, ftype in cls._fields_:
            if name in getattr(cls, "_anonymous_", ()):
                # an anonymous union: check the offset of each of its members
                for uname, _ in ftype._fields_:
                    fields.append((uname, getattr(cls, uname).offset))
            else:
                fields.append((name, getattr(cls, name).offset))
        present = [(n, o) for n, o in fields if re.search(r"\b%s\b" % re.escape(n), header_text)]
        if cls in short or any(_contains(cls, other) for other in short):
            # a field our layout has and this header does not (1.3.0 has no audio input):
            # sizes cannot be equal, ours may only be larger
            out.append('static_assert(sizeof(%s) <= %d, "%s is larger in the header than in npuzoo");'
                       % (cname, ctypes.sizeof(cls), cname))
        else:
            out.append('static_assert(sizeof(%s) == %d, "sizeof(%s) differs");'
                       % (cname, ctypes.sizeof(cls), cname))
        for n, o in present:
            out.append('static_assert(offsetof(%s, %s) == %d, "offset of %s.%s differs");' % (cname, n, o, cname, n))
    return out


def source(header_text, profile):
    body = re.sub(r"#include\s*<[^>]+>", "", header_text)
    return (PREAMBLE + body +
            "\ntypedef decltype(((RKLLMInput*)0)->multimodal_input) MM;\n" +
            "\n".join(assertions(profile, header_text)) + "\n")


def check(header_path, profile, target):
    compiler = shutil.which("clang++")
    if not compiler:
        raise SystemExit("clang++ is needed (it can target aarch64 without a sysroot)")
    with open(header_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "abi.cpp")
        with open(src, "w") as f:
            f.write(source(text, profile))
        p = subprocess.run([compiler, "-std=c++11", "-fsyntax-only", "-nostdinc", "-nostdinc++",
                            "--target=%s" % target, src], capture_output=True, text=True)
    if p.returncode != 0:
        msgs = [line for line in p.stderr.splitlines() if "error" in line]
        print("%s (%s, %s): MISMATCH\n  %s" % (header_path, profile, target, "\n  ".join(msgs[:10])))
        return 1
    print("%s (%s, %s): %d assertions hold" % (header_path, profile, target,
                                                 len(assertions(profile, text))))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("header")
    ap.add_argument("profile", choices=sorted(TYPES))
    ap.add_argument("--target", action="append",
                    help="clang target triple (default: aarch64-linux-gnu and x86_64-linux-gnu)")
    a = ap.parse_args(argv)
    targets = a.target or ["aarch64-linux-gnu", "x86_64-linux-gnu"]
    return max(check(a.header, a.profile, t) for t in targets)


if __name__ == "__main__":
    sys.exit(main())
