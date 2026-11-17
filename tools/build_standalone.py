#!/usr/bin/env python3
"""Bundle doctor + explain + inspect into one dependency-free file.

The point of the standalone script is that someone on a forum can run it in
one line, with no pip, no venv, no repo clone:

    curl -fsSL https://raw.githubusercontent.com/npuzoo/npuzoo/main/standalone/npuzoo-doctor.py | python3

It is generated, never hand-edited, so it cannot drift from the package.
Regenerate with:  python tools/build_standalone.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "npuzoo"
OUT = ROOT / "standalone" / "npuzoo-doctor.py"

MODULES = ["known_issues", "fingerprint", "doctor", "explain", "inspect"]

# package data a single file cannot read from disk, inlined instead
EMBED = {"fingerprint": ("EMBEDDED", SRC / "data" / "runtime_fingerprints.json")}

HEADER = '''#!/usr/bin/env python3
# npuzoo doctor — standalone, generated file. Do not edit.
# Source: https://github.com/npuzoo/npuzoo  (src/npuzoo/, tools/build_standalone.py)
# Apache-2.0
#
#   python3 npuzoo-doctor.py              # check this board
#   python3 npuzoo-doctor.py --json       # machine-readable
#   python3 npuzoo-doctor.py --explain f  # read an RKLLM/RKNN log instead
#   python3 npuzoo-doctor.py --inspect m.rkllm [--board rk3588] [--runtime 1.2.1]
#                                         # will this model file load here?
#
# Reads only /proc, /sys and the runtime .so files. Sends nothing anywhere.
'''

FOOTER = '''

def _main(argv):
    # people pipe this into head/less; a closed pipe is not an error
    try:
        return _run(argv)
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


def _run(argv):
    argv = list(argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__ or "")
        print("usage: npuzoo-doctor.py [--json] [--demo] [--explain [FILE]]\\n"
              "       npuzoo-doctor.py --inspect FILE [--board CHIP] [--runtime VER]\\n"
              "                        [--sha256 HEX] [--size BYTES] [--json]")
        return 0
    if "--inspect" in argv:
        i = argv.index("--inspect")
        if len(argv) <= i + 1:
            print("--inspect needs a model file path", file=sys.stderr)
            return 2

        def opt(flag):
            if flag in argv and len(argv) > argv.index(flag) + 1:
                return argv[argv.index(flag) + 1]
            return None
        size = opt("--size")
        return cmd_inspect(argv[i + 1], board=opt("--board"), runtime=opt("--runtime"),
                           expect_sha256=opt("--sha256"),
                           expect_size=int(size) if size else None,
                           as_json="--json" in argv)
    if "--explain" in argv:
        i = argv.index("--explain")
        path = argv[i + 1] if len(argv) > i + 1 else None
        return cmd_explain(path)
    return run_doctor(as_json="--json" in argv, demo="--demo" in argv)


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
'''

DROP_IMPORT = re.compile(r"^\s*from \.[\w.]* import .*$", re.M)


def module_source(name):
    text = (SRC / (name + ".py")).read_text()
    text = DROP_IMPORT.sub("", text)
    if name in EMBED:
        const, path = EMBED[name]
        blob = json.dumps(json.loads(path.read_text()), separators=(",", ":"))
        text += "\n\n%s = json.loads(%r)\n_cache = None\n" % (const, blob)
    return "# " + "-" * 68 + "\n# from src/npuzoo/%s.py\n# " % name + "-" * 68 + "\n" + text


def check(bundled):
    """Fail loudly rather than ship a broken one-liner."""
    import ast
    tree = ast.parse(bundled)

    # board images still ship old Pythons; f-strings are 3.6+, walrus is 3.8+
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr):
            raise SystemExit("standalone must stay Python 3.6-compatible: walrus operator found")

    # a later module silently shadowing an earlier module's global is how this
    # bundle broke the first time (explain.ICON ate doctor.ICON)
    seen, clash = {}, []
    offset = 0
    for name in MODULES:
        mod = ast.parse((SRC / (name + ".py")).read_text())
        for node in mod.body:
            targets = []
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    elts = tgt.elts if isinstance(tgt, ast.Tuple) else [tgt]
                    targets += [e.id for e in elts if isinstance(e, ast.Name)]
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                targets = [node.name]
            for t in targets:
                if t in seen and seen[t] != name:
                    clash.append("%s: defined in both %s and %s" % (t, seen[t], name))
                seen[t] = name
        offset += 1
    if clash:
        raise SystemExit("name clash would break the bundle:\n  " + "\n  ".join(clash))


def build():
    parts = [HEADER, "import sys\n"]
    parts += [module_source(m) for m in MODULES]
    parts.append(FOOTER)
    bundled = "\n".join(parts)

    check(bundled)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(bundled)
    OUT.chmod(0o755)
    print("wrote %s (%d bytes)" % (OUT.relative_to(ROOT), OUT.stat().st_size))


if __name__ == "__main__":
    build()
