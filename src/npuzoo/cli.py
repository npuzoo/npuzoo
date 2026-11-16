"""npuzoo command line entry point."""
import argparse
import sys

from . import __version__


def main(argv=None):
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
    if args.cmd == "run":
        print("npuzoo run: lands in v0.2 with the first model batch.")
        print("Meanwhile: npuzoo pull prints the exact command to run each package by hand.")
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
