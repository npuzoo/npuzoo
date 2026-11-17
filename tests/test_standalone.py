"""The one-file script people curl: it must run every path without a traceback."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "standalone" / "npuzoo-doctor.py"
LOGS = ROOT / "tests" / "logs"


def run(args, stdin=None):
    p = subprocess.run([sys.executable, str(SCRIPT)] + args, input=stdin, capture_output=True, text=True)
    assert "Traceback" not in p.stderr, p.stderr
    return p


def test_explain_every_fixture():
    for log in sorted(LOGS.glob("*.log")):
        p = run(["--explain", str(log)])
        assert p.returncode in (0, 1), (log.name, p.stdout, p.stderr)


def test_explain_architecture_note():
    p = run(["--explain"], stdin="ERROR: Not support Qwen3ForCausalLM!\n")
    assert "added in RKLLM 1.2.1" in p.stdout


def test_inspect_paths(tmp_path):
    lfs = tmp_path / "m-rk3588-w8a8.rkllm"
    lfs.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:%s\nsize 123\n" % ("0" * 64))
    assert "Git LFS pointer" in run(["--inspect", str(lfs), "--board", "rk3588"]).stdout
    good = tmp_path / "Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm"
    with open(good, "wb") as f:
        f.write(bytes.fromhex("daeeb33603000000"))
        f.truncate(20 * 1024 * 1024)
    out = run(["--inspect", str(good), "--board", "rk3588", "--runtime", "1.1.4"]).stdout
    assert "added in RKLLM 1.2.1" in out


def test_demo_and_help():
    assert run(["--demo"]).returncode in (0, 1)
    assert "--inspect" in run(["--help"]).stdout


def test_pc_mode():
    p = run(["--pc"])
    assert "rkllm-toolkit" in p.stdout and p.returncode in (0, 1)
