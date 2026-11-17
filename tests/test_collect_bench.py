"""tools/collect_bench.py: shared bench reports into the results page."""
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("collect_bench", ROOT / "tools" / "collect_bench.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)


def report(**over):
    r = {"npuzoo": "0.2.0", "date": "2026-12-01T10:00Z", "board": "Radxa ROCK 5B+", "chip": "rk3588",
         "kernel": "6.1.84", "npu_driver": "0.9.8", "runtime": "1.3.1", "mem_gb": 15.6,
         "cpu_governor": "ondemand", "npu_governor": "rknpu_ondemand",
         "model": {"file": "Qwen3-1.7B_rk3588_w8a8_rkllm-1.3.1.rkllm", "bytes": 2100000000, "sha256": "a" * 64},
         "load_s": 3.2, "workloads": {
             "chat": {"runs": 3, "prefill_tps": 120.5, "generate_tps": 14.2, "prefill_tokens": 30,
                      "generate_tokens": 128, "memory_mb": 2300.0},
             "long-prompt": {"runs": 3, "prefill_tps": 410.0, "generate_tps": 13.9, "prefill_tokens": 520,
                             "generate_tokens": 16, "memory_mb": 2350.0}},
         "python": "3.11.2"}
    r.update(over)
    return r


def test_report_from_an_issue_body():
    body = "### npuzoo bench JSON\n\n```json\n%s\n```\n\n### Anything unusual\n\nfan on" % json.dumps(report())
    assert cb.from_issue(body)["chip"] == "rk3588"
    with pytest.raises(cb.BadReport):
        cb.from_issue("no json here")


def test_clean_refuses_what_bench_does_not_write():
    with pytest.raises(cb.BadReport):
        cb.clean({k: v for k, v in report().items() if k != "runtime"})
    with pytest.raises(cb.BadReport):
        cb.clean(report(model={"file": "x.rkllm", "sha256": "nothex"}))
    with pytest.raises(cb.BadReport):
        cb.clean(report(workloads={"other": {}}))
    r = cb.clean(report(board="A | B\n<script>"), source="https://github.com/npuzoo/npuzoo/issues/7")
    assert r["board"] == "A | B <script>" and "python" not in r


def test_merge_replaces_the_same_report_and_render_ranks_nothing():
    a = cb.clean(report())
    b = cb.clean(report(chip="rk3576", cpu_governor="performance", npu_governor="userspace"))
    res = cb.merge([a], [b, cb.clean(report())])
    assert len(res) == 2
    md = cb.render(res)
    assert "| not pinned |" in md and "| pinned |" in md
    assert "fastest" not in md.lower() and md.count("## Qwen3-1.7B") == 1
    md = cb.render([cb.clean(report(board="A | B"), source="https://example.org/i/1")])
    assert "A \\| B" in md and "[link](https://example.org/i/1)" in md
    assert "No results yet." in cb.render([])


def test_main_writes_both_files(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY", "```json\n%s\n```" % json.dumps(report()))
    res, md = tmp_path / "r.json", tmp_path / "b.md"
    assert cb.main(["--issue-body-env", "BODY", "--source", "https://x/1", "--results", str(res), "--md", str(md)]) == 0
    assert json.loads(res.read_text())["results"][0]["source"] == "https://x/1"
    monkeypatch.setenv("BODY", "nothing")
    assert cb.main(["--issue-body-env", "BODY", "--results", str(res), "--md", str(md)]) == 1
    assert len(json.loads(res.read_text())["results"]) == 1
