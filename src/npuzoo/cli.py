"""npuzoo command line entry point."""
import argparse
import sys

from . import __version__


def main(argv=None):
    # people pipe this into head/less; a closed pipe is not an error
    try:
        return _main(argv)
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


def _main(argv=None):
    p = argparse.ArgumentParser(
        prog="npuzoo",
        description="Run AI models on NPU single-board computers. One command.",
    )
    p.add_argument("--version", action="version", version=f"npuzoo {__version__}")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("doctor", help="check board, kernel, NPU driver and runtime libs")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.add_argument("--demo", action="store_true", help="simulate a board (for development off-board)")

    pull = sub.add_parser("pull", help="download a verified model package for this board")
    pull.add_argument("name", help="package name, e.g. qwen3-1.7b")
    pull.add_argument("--index", default=None, help="registry index URL or local path (default: built-in)")

    ls = sub.add_parser("list", help="list packages available for this board")
    ls.add_argument("--index", default=None)

    run = sub.add_parser("run", help="run a pulled model")
    run.add_argument("name")

    ex = sub.add_parser("explain", help="read an RKLLM/RKNN log and say what went wrong")
    ex.add_argument("logfile", nargs="?", help="log file to read (default: stdin)")

    ins = sub.add_parser("inspect", help="check a model file before copying it to the board")
    ins.add_argument("file", help="the .rkllm file to check")
    ins.add_argument("--board", help="chip of the target board, e.g. rk3588 (auto-detected on a board)")
    ins.add_argument("--runtime", help="librkllmrt version on the board, e.g. 1.3.1")
    ins.add_argument("--sha256", help="expected SHA-256 (Hugging Face: the file's LFS oid)")
    ins.add_argument("--size", type=int, help="expected size in bytes")
    ins.add_argument("--json", action="store_true", help="machine-readable output")

    fd = sub.add_parser("find", help="search community .rkllm files on Hugging Face and check they fit this board")
    fd.add_argument("query", nargs="*", help="words to match, e.g. qwen3 1.7b")
    fd.add_argument("--board", help="chip, e.g. rk3588 (auto-detected on a board)")
    fd.add_argument("--runtime", help="librkllmrt version, e.g. 1.3.1 (auto-detected on a board)")
    fd.add_argument("--all", action="store_true", help="also show files whose names say they will not load")
    fd.add_argument("--limit", type=int, default=20, help="rows to show; 0 for all")
    fd.add_argument("--index", default=None, help="community index URL or path")
    fd.add_argument("--refresh", action="store_true", help="fetch the index again even if cached today")
    fd.add_argument("--json", action="store_true", help="machine-readable output")

    gt = sub.add_parser("get", help="download a community .rkllm file, verify it, and inspect it")
    gt.add_argument("repo", help="Hugging Face repo, e.g. someone/qwen3-1.7b-rk3588")
    gt.add_argument("path", help="file path inside the repo")
    gt.add_argument("--board", help="chip, e.g. rk3588 (auto-detected on a board)")
    gt.add_argument("--runtime", help="librkllmrt version (auto-detected on a board)")
    gt.add_argument("--dir", default=None, help="where to save (default: ~/.npuzoo/community/<repo>)")
    gt.add_argument("--index", default=None, help="community index URL or path")
    gt.add_argument("--force", action="store_true", help="download even if the name says it will not load")

    sp = sub.add_parser("support", help="which RKLLM release added a model family or chip")
    sp.add_argument("name", nargs="?", help="model or chip, e.g. qwen3, Qwen3ForCausalLM, rk3562")

    args = p.parse_args(argv)

    if args.cmd == "doctor":
        from .doctor import run_doctor
        return run_doctor(as_json=args.json, demo=args.demo)
    if args.cmd == "pull":
        from .registry import cmd_pull
        return cmd_pull(args.name, args.index)
    if args.cmd == "list":
        from .registry import cmd_list
        return cmd_list(args.index)
    if args.cmd == "explain":
        from .explain import cmd_explain
        return cmd_explain(args.logfile)
    if args.cmd == "support":
        from .models import cmd_support
        return cmd_support(args.name)
    if args.cmd == "find":
        from .community import cmd_find
        return cmd_find(" ".join(args.query), board=args.board, runtime=args.runtime, index_src=args.index,
                        show_all=args.all, limit=args.limit, as_json=args.json, refresh=args.refresh)
    if args.cmd == "get":
        from .community import cmd_get
        return cmd_get(args.repo, args.path, board=args.board, runtime=args.runtime,
                       index_src=args.index, dest=args.dir, force=args.force)
    if args.cmd == "inspect":
        from .inspect import cmd_inspect
        return cmd_inspect(args.file, board=args.board, runtime=args.runtime,
                           expect_sha256=args.sha256, expect_size=args.size, as_json=args.json)
    if args.cmd == "run":
        print("npuzoo run: lands in v0.2 with the first model batch.")
        print("Meanwhile: npuzoo pull prints the exact command to run each package by hand.")
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
