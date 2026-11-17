"""`npuzoo explain` against logs that real people posted.

Each fixture in tests/logs/ is an excerpt of a log someone published while
asking for help. If a change to known_issues.py stops recognising one of
them, that is a regression for a real person.
"""
import os
import pathlib

import pytest

from npuzoo.known_issues import scan, looks_healthy, BLOCKER

LOGS = pathlib.Path(__file__).parent / "logs"


def read(name):
    return (LOGS / name).read_text()


def ids(text):
    return {h["id"] for h in scan(text)}


def test_old_driver_and_oom_are_both_reported():
    got = ids(read("driver-too-old-oom.log"))
    assert "driver-too-old" in got
    assert "npu-oom" in got


def test_generic_init_failure_is_suppressed_when_cause_is_known():
    # the log ends in `rkllm_init failed`, but the OOM above it is the answer
    assert "init-failed" not in ids(read("driver-too-old-oom.log"))


def test_generic_init_failure_shows_when_nothing_else_matches():
    assert "init-failed" in ids("rkllm init start\nE rkllm: rkllm_init failed\n")


def test_model_runtime_mismatch():
    got = ids(read("version-mismatch.log"))
    assert "model-runtime-mismatch" in got
    assert "npu-oom" not in got          # do not blame memory for a load error


def test_unsupported_architecture():
    assert "unsupported-architecture" in ids(read("unsupported-arch.log"))


def test_toolkit_too_old_for_model():
    assert "toolkit-too-old-for-model" in ids(read("toolkit-too-old.log"))


def test_rknn_mismatch_and_benign_warning():
    got = ids(read("rknn-mismatch.log"))
    assert "rknn-model-runtime-mismatch" in got
    assert "rknn-dynamic-shape-warning" in got


def test_matmul_failure_points_at_the_driver():
    got = ids(read("matmul-failed.log"))
    assert "matmul-run-failed" in got
    assert "driver-too-old" in got


def test_healthy_log_is_recognised_as_healthy():
    text = read("healthy.log")
    assert looks_healthy(text)
    assert not any(h["severity"] == BLOCKER for h in scan(text))


@pytest.mark.parametrize("name", sorted(os.listdir(LOGS)))
def test_every_fixture_except_healthy_matches_something(name):
    text = read(name)
    if name == "healthy.log":
        return
    assert scan(text), "%s no longer matches any known issue" % name


def test_no_issue_fires_on_unrelated_text():
    noise = "Linux orangepi5 6.1.43-rockchip-rk3588 #1 SMP Fri Oct 10 10:00:00 UTC 2025 aarch64\n"
    assert scan(noise) == []
