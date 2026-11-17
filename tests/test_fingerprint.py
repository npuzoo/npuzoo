"""Dating a log by the messages in it.

The fingerprint table is extracted from the official librkllmrt.so at every
release tag (tools/build_fingerprints.py). These tests pin the property that
makes it useful: it must give a *lower bound* that is never wrong, and it must
stay silent rather than guess.
"""
import pytest

from npuzoo.fingerprint import infer_runtime, _load


def test_table_loaded():
    versions, stems = _load()
    assert versions[0] == "1.1.0" and versions[-1] == "1.3.1"
    assert len(stems) > 50


def test_silent_on_a_log_with_no_known_messages():
    v, why = infer_runtime("Linux orangepi5 6.1.43-rockchip-rk3588 aarch64\n")
    assert v is None and why == []


def test_dates_a_log_with_no_version_line():
    v, why = infer_runtime("E rkllm: The model's target_platform does not match the real platform\n")
    assert v == "1.3.0"
    assert why and why[0][1] == "1.3.0"


def test_takes_the_newest_bound_when_several_messages_match():
    text = ("E rkllm: Mismatch between enabled CPUs mask and expected count. Please check the configuration.\n"
            "E rkllm: Failed to allocate buffer for kv cache\n")
    v, _ = infer_runtime(text)
    # 1.2.0 message and a 1.2.2 message -> runtime must be at least 1.2.2
    assert v == "1.2.2"


def test_evidence_only_cites_messages_that_justify_the_bound():
    text = ("E rkllm: Mismatch between enabled CPUs mask and expected count. Please check the configuration.\n"
            "E rkllm: Failed to allocate buffer for kv cache\n")
    v, why = infer_runtime(text)
    assert all(ver == v for _, ver in why)


@pytest.mark.parametrize("stem_fragment,expected", [
    ("Failed to allocate buffer for kv cache", "1.2.2"),
    ("The model's target_platform does not match the real platform", "1.3.0"),
])
def test_known_anchors(stem_fragment, expected):
    v, _ = infer_runtime("E rkllm: " + stem_fragment + "\n")
    assert v == expected


def test_bound_is_a_floor_not_an_equality():
    """A newer runtime still emits old messages, so an old bound must not be
    read as 'this is an old runtime'. Nothing in the API should imply that."""
    v, _ = infer_runtime("E rkllm: Mismatch between enabled CPUs mask and expected count. "
                         "Please check the configuration.\n")
    versions, _s = _load()
    assert v in versions
    assert versions.index(v) < len(versions) - 1   # i.e. newer releases also emit it
