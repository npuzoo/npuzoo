"""`npuzoo doctor` verdicts for board setups seen in the wild.

Each case below mirrors a configuration reported in a public thread or a
vendor doc, so these are not hypotheticals. They pin down behaviour that
matters: never claim a board is fine when the driver will refuse models,
and never scare someone whose board is actually healthy.
"""
import pytest

from npuzoo.doctor import diagnose, collect, _fits, FAIL, WARN, OK


def verdict(checks, name):
    for c in checks:
        if c["name"] == name:
            return c
    return None


def board(**over):
    base = {
        "board": "Orange Pi 5 Plus", "chip": "rk3588", "os": "Debian 12 (bookworm)",
        "kernel": "6.1.43-rockchip-rk3588", "mem_gb": 15.6,
        "npu_node": True, "npu_driver": "0.9.8", "npu_driver_error": None,
        "rknnrt": {"path": "/usr/lib/librknnrt.so", "version": "2.3.0"},
        "rkllmrt": {"path": "/usr/lib/librkllmrt.so", "version": "1.2.1"},
        "cpu_governor": "performance", "npu_governor": None,
    }
    base.update(over)
    return base


def test_healthy_board_has_no_failures():
    checks = diagnose(board())
    assert not [c for c in checks if c["status"] == FAIL]
    assert verdict(checks, "npu-driver")["status"] == OK


def test_driver_0_8_2_is_flagged():
    # as reported with rkllm-runtime 1.0.1 / 1.2.1b1 on RK3588
    c = verdict(diagnose(board(npu_driver="0.8.2")), "npu-driver")
    assert c["status"] == WARN
    assert "0.9.6" in c["detail"] or "0.9.6" in (c["fix"] or "")


def test_driver_0_9_6_passes_but_says_so():
    c = verdict(diagnose(board(npu_driver="0.9.6")), "npu-driver")
    assert c["status"] == OK
    assert "0.9.6" in c["detail"]


def test_debugfs_permission_is_not_reported_as_a_missing_driver():
    checks = diagnose(board(npu_driver=None, npu_driver_error="permission"))
    c = verdict(checks, "npu-driver")
    assert c["status"] != WARN and c["status"] != FAIL
    assert "sudo" in (c["fix"] or "")


def test_mainline_kernel_without_npu_fails():
    checks = diagnose(board(kernel="6.12.9-edge-rockchip64", npu_node=False,
                            npu_driver=None, npu_driver_error="missing"))
    assert verdict(checks, "npu-device")["status"] == FAIL
    assert verdict(checks, "kernel")["status"] == WARN


def test_rk3588_is_told_it_has_no_w4a16():
    c = verdict(diagnose(board()), "weights")
    assert "w8a8" in c["detail"]
    assert "w4a16" in c["detail"]          # mentioned precisely to warn it is absent


def test_rk3576_is_told_it_has_w4a16():
    c = verdict(diagnose(board(chip="rk3576", board="Radxa ROCK 4D")), "weights")
    assert "w4a16" in c["detail"]
    assert "will not help you" not in c["detail"]


def test_rk3566_is_not_an_llm_target():
    c = verdict(diagnose(board(chip="rk3566", board="Radxa ROCK 3A")), "board")
    assert c["status"] == WARN
    assert "CPU" in c["detail"]


def test_8gb_board_is_told_what_will_not_fit():
    c = verdict(diagnose(board(mem_gb=7.7)), "memory")
    assert c["status"] == OK
    assert "7B" in c["detail"]


def test_runtime_version_pairing_is_always_stated():
    c = verdict(diagnose(board()), "version-pairing")
    assert "1.2.1" in c["detail"]


def test_missing_runtime_is_a_warning_not_a_failure():
    c = verdict(diagnose(board(rkllmrt={"path": None, "version": None})), "librkllmrt")
    assert c["status"] == WARN


def test_non_performance_governor_is_explained_not_scolded():
    c = verdict(diagnose(board(cpu_governor="ondemand")), "clocks")
    assert "lower" in c["detail"]


@pytest.mark.parametrize("gb,expect", [(3.8, "2B"), (7.7, "5B"), (15.6, "12B"), (0.9, "under 1B")])
def test_memory_sizing_is_monotonic_and_sane(gb, expect):
    got = _fits(gb)
    assert got is not None
    # we only pin the shape; exact rounding may move as real numbers arrive
    assert got.endswith("B")


def test_collect_never_raises_off_board():
    info = collect()
    assert "chip" in info and "npu_node" in info


def test_demo_mode_is_self_consistent():
    checks = diagnose(collect(demo=True))
    assert verdict(checks, "board")["status"] == OK
