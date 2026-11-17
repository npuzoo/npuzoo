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
    d.add_argument("--pc", action="store_true", help="check the x86 PC you convert models on instead")

    pull = sub.add_parser("pull", help="download a verified model package for this board")
    pull.add_argument("name", help="package name, e.g. qwen3-1.7b")
    pull.add_argument("--index", default=None, help="registry index URL or local path (default: built-in)")

    ls = sub.add_parser("list", help="list packages available for this board")
    ls.add_argument("--index", default=None)

    def model_opts(sp):
        sp.add_argument("--lib", help="path to librkllmrt.so (default: found like doctor does)")
        sp.add_argument("--context", type=int, default=4096, help="max_context_len (default 4096)")
        sp.add_argument("--max-new-tokens", type=int, default=1024)
        sp.add_argument("--temperature", type=float, default=0.8)
        sp.add_argument("--force", action="store_true", help="load even if inspect says it will fail")

    run = sub.add_parser("run", help="chat with a .rkllm model on the NPU; prints the runtime's own speed")
    run.add_argument("name", help="a .rkllm file, or a pulled package name")
    run.add_argument("--prompt", "-p", help="one prompt, then exit (default: interactive)")
    run.add_argument("--think", action="store_true", help="enable thinking mode (Qwen3)")
    run.add_argument("--json", action="store_true", help="answer and timings as JSON")
    model_opts(run)

    cv = sub.add_parser("convert", help="convert a Hugging Face model to .rkllm on this x86 PC (rkllm-toolkit)")
    cv.add_argument("model", help="Hugging Face repo id (Qwen/Qwen3-1.7B) or a local model directory")
    cv.add_argument("--chip", required=True, help="rk3588, rk3588s, rk3576, rk3562 or rv1126b")
    cv.add_argument("--dtype", help="weight format (default w8a8; w4a16_g128 makes a smaller file for rk3576)")
    cv.add_argument("--out", default=".", help="directory for the .rkllm file (default: here)")
    cv.add_argument("--context", type=int, default=4096, help="max context the model is built for (default 4096)")
    cv.add_argument("--no-calibration", action="store_true", help="skip the calibration set (faster, may lose quality)")
    cv.add_argument("--force", action="store_true", help="convert even if the checks say it will fail")

    bn = sub.add_parser("bench", help="measure a .rkllm model the same way on every board; writes a shareable JSON")
    bn.add_argument("name", help="a .rkllm file, or a pulled package name")
    bn.add_argument("--repeats", type=int, default=3, help="measured runs per workload (default 3)")
    bn.add_argument("--out", help="where to write the JSON report")
    bn.add_argument("--lib", help="path to librkllmrt.so")
    bn.add_argument("--context", type=int, default=4096)
    bn.add_argument("--force", action="store_true", help="load even if inspect says it will fail")

    sv = sub.add_parser("serve", help="serve a .rkllm model over the OpenAI chat API")
    sv.add_argument("name", help="a .rkllm file, or a pulled package name")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8080)
    sv.add_argument("--model-name", help="model id clients see (default: the file name)")
    model_opts(sv)

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
    fd.add_argument("--source", choices=["huggingface", "modelscope"], help="only files from this site")

    gt = sub.add_parser("get", help="download a community .rkllm file, verify it, and inspect it")
    gt.add_argument("repo", help="Hugging Face repo, e.g. someone/qwen3-1.7b-rk3588")
    gt.add_argument("path", help="file path inside the repo")
    gt.add_argument("--board", help="chip, e.g. rk3588 (auto-detected on a board)")
    gt.add_argument("--runtime", help="librkllmrt version (auto-detected on a board)")
    gt.add_argument("--dir", default=None, help="where to save (default: ~/.npuzoo/community/<repo>)")
    gt.add_argument("--index", default=None, help="community index URL or path")
    gt.add_argument("--force", action="store_true", help="download even if the name says it will not load")
    gt.add_argument("--source", choices=["huggingface", "modelscope"],
                    help="site to download from (default: Hugging Face; or set NPUZOO_SOURCE)")

    sp = sub.add_parser("support", help="which RKLLM release added a model family or chip")
    sp.add_argument("name", nargs="?", help="model or chip, e.g. qwen3, Qwen3ForCausalLM, rk3562")

    args = p.parse_args(argv)

    if args.cmd == "doctor":
        if args.pc:
            from .pc import run_pc
            return run_pc(as_json=args.json)
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
                        show_all=args.all, limit=args.limit, as_json=args.json, refresh=args.refresh,
                        source=args.source)
    if args.cmd == "get":
        from .community import cmd_get
        return cmd_get(args.repo, args.path, board=args.board, runtime=args.runtime,
                       index_src=args.index, dest=args.dir, force=args.force, source=args.source)
    if args.cmd == "inspect":
        from .inspect import cmd_inspect
        return cmd_inspect(args.file, board=args.board, runtime=args.runtime,
                           expect_sha256=args.sha256, expect_size=args.size, as_json=args.json)
    if args.cmd == "run":
        from .runner import cmd_run
        return cmd_run(args.name, prompt=args.prompt, lib_path=args.lib, force=args.force, context=args.context,
                       max_new_tokens=args.max_new_tokens, temperature=args.temperature, think=args.think,
                       as_json=args.json)
    if args.cmd == "convert":
        from .convert import cmd_convert
        return cmd_convert(args.model, args.chip, dtype=args.dtype, out_dir=args.out, context=args.context,
                           calibrate=not args.no_calibration, force=args.force)
    if args.cmd == "bench":
        from .bench import cmd_bench
        return cmd_bench(args.name, repeats=args.repeats, lib_path=args.lib, force=args.force,
                         context=args.context, out_path=args.out)
    if args.cmd == "serve":
        from .runner import cmd_serve
        return cmd_serve(args.name, host=args.host, port=args.port, lib_path=args.lib, force=args.force,
                         context=args.context, max_new_tokens=args.max_new_tokens,
                         temperature=args.temperature, name=args.model_name)

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
