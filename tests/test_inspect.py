"""`npuzoo inspect` against file shapes seen in public .rkllm repos.

The headers below copy only the first bytes that are the same in every
Rockchip-format sample (signature and container fields). The model payload is
padding: inspect never reads past the first 4 KB except to hash.
"""
import hashlib
import os

import pytest

from npuzoo.inspect import (FAIL, PASS, WARN, INFO, inspect_file, parse_lfs_pointer,
                            parse_name, sniff)

# Signature + container fields shared by all 43 Rockchip-format samples.
ROCKCHIP_HEAD = bytes.fromhex(
    "daeeb3360300000037010000000000002800000000000000140000000000000000")
# The third-party file: ASCII magic, version 1, architecture name, padding.
THIRD_PARTY_HEAD = b"RKLL" + b"\x01\x00\x00\x00" + b"qwen3" + b"\x00" * 27 + b"Q8_0"
BIG = 20 * 1024 * 1024  # over the "too small to be a model" threshold


def write(tmp_path, name, head, size=None):
    p = tmp_path / name
    with open(p, "wb") as f:
        f.write(head)
        if size and size > len(head):
            f.seek(size - 1)
            f.write(b"\0")
    return str(p)


def statuses(findings, check=None):
    return [f["status"] for f in findings if check is None or f["check"] == check]


def test_lfs_pointer_is_named_and_real_size_reported(tmp_path):
    ptr = (b"version https://git-lfs.github.com/spec/v1\n"
           b"oid sha256:" + b"a" * 64 + b"\nsize 4846783300\n")
    p = write(tmp_path, "Qwen3-4B_RK3588_w8a8.rkllm", ptr)
    f = inspect_file(p)
    assert f[0]["status"] == FAIL and "LFS pointer" in f[0]["detail"]
    assert "4.85 GB" in f[0]["detail"]
    assert parse_lfs_pointer(ptr.decode()) == ("a" * 64, 4846783300)


def test_html_error_page(tmp_path):
    p = write(tmp_path, "model.rkllm", b"\n<!DOCTYPE html><html><body>Not Found</body></html>")
    f = inspect_file(p)
    assert f[0]["status"] == FAIL and "web page" in f[0]["detail"]


def test_json_error(tmp_path):
    p = write(tmp_path, "model.rkllm", b'{"error":"Access to model is restricted"}')
    assert "JSON" in inspect_file(p)[0]["detail"]


def test_gguf_is_not_for_the_npu(tmp_path):
    p = write(tmp_path, "qwen3-4b-q4_k_m.gguf", b"GGUF\x03\x00\x00\x00" + b"\0" * 64)
    f = inspect_file(p)
    assert f[0]["status"] == FAIL and "GGUF" in f[0]["detail"]


def test_third_party_rkll_format_is_flagged_with_its_architecture(tmp_path):
    p = write(tmp_path, "Qwen3-Embedding-0.6B.rkllm", THIRD_PARTY_HEAD, BIG)
    f = inspect_file(p)
    assert sniff(THIRD_PARTY_HEAD) == "rkll-third-party"
    assert f[0]["status"] == WARN and "not Rockchip's format" in f[0]["detail"]
    assert "'qwen3'" in f[0]["detail"]


def test_unknown_signature_is_a_warning_not_a_verdict(tmp_path):
    p = write(tmp_path, "weird.rkllm", b"\x00" * 64, BIG)
    assert inspect_file(p)[0]["status"] == WARN


def test_rknn_file_is_explained(tmp_path):
    p = write(tmp_path, "yolo11n.rknn", b"\x00" * 64)
    assert inspect_file(p)[0]["status"] == INFO


def test_good_rk3588_w8a8(tmp_path):
    p = write(tmp_path, "Qwen3-4B_RK3588_w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    f = inspect_file(p, board="rk3588")
    assert FAIL not in statuses(f)
    assert PASS in statuses(f, "file type") and PASS in statuses(f, "weight format")


def test_w4a16_on_rk3588_is_rejected(tmp_path):
    # A real trap: the same repo ships RK3576 w4a16 next to RK3588 w8a8.
    p = write(tmp_path, "Qwen3-4B_RK3588_w4a16.rkllm", ROCKCHIP_HEAD, BIG)
    f = inspect_file(p)
    assert FAIL in statuses(f, "weight format")


def test_rk3576_file_on_rk3588_board(tmp_path):
    p = write(tmp_path, "Qwen3-4B_RK3576_w4a16.rkllm", ROCKCHIP_HEAD, BIG)
    f = inspect_file(p, board="rk3588")
    assert any(x["status"] == FAIL and "target_platform" in x["detail"] for x in f)


def test_rk3588s_board_takes_rk3588_build(tmp_path):
    p = write(tmp_path, "Qwen3-1.7B-w8a8-rk3588.rkllm", ROCKCHIP_HEAD, BIG)
    assert FAIL not in statuses(inspect_file(p, board="rk3588s"))


def test_rk3566_has_no_rkllm(tmp_path):
    p = write(tmp_path, "tinyllama-rk3566.rkllm", ROCKCHIP_HEAD, BIG)
    assert FAIL in statuses(inspect_file(p), "target")


def test_coprocessor_build_is_flagged(tmp_path):
    p = write(tmp_path, "qwen3-4b-rknn3-rk1828.rkllm", ROCKCHIP_HEAD, BIG)
    assert WARN in statuses(inspect_file(p), "target")


def test_truncated_download(tmp_path):
    p = write(tmp_path, "Qwen3-4B_RK3588_w8a8.rkllm", ROCKCHIP_HEAD, 4096)
    assert FAIL in statuses(inspect_file(p), "size")


def test_expected_size_mismatch(tmp_path):
    p = write(tmp_path, "m_rk3588_w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    assert FAIL in statuses(inspect_file(p, expect_size=BIG + 1), "size")
    assert PASS in statuses(inspect_file(p, expect_size=BIG), "size")


def test_sha256(tmp_path):
    p = write(tmp_path, "m_rk3588_w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    good = hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert PASS in statuses(inspect_file(p, expect_sha256=good), "checksum")
    assert FAIL in statuses(inspect_file(p, expect_sha256="0" * 64), "checksum")


def test_toolkit_newer_than_runtime(tmp_path):
    p = write(tmp_path, "Qwen3.5-9B-RK3588-RKLLM-1.3.1-w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    assert FAIL in statuses(inspect_file(p, runtime="1.2.3"), "versions")
    assert PASS in statuses(inspect_file(p, runtime="1.3.1"), "versions")


def test_old_toolkit_on_new_runtime_is_a_warning_only(tmp_path):
    # Rockchip does not document the cutoff; we must not claim it fails.
    p = write(tmp_path, "Qwen2.5-7B-Instruct-rk3588-1.1.0-w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    assert statuses(inspect_file(p, runtime="1.3.1"), "versions") == [WARN]


def test_beta_sorts_before_release(tmp_path):
    p = write(tmp_path, "m-rk3588-1.2.1b1-w8a8.rkllm", ROCKCHIP_HEAD, BIG)
    assert PASS in statuses(inspect_file(p, runtime="1.2.1"), "versions")


@pytest.mark.parametrize("name,chip,dtype,group,tk", [
    ("Qwen3-4B_RK3576_w4a16_g128.rkllm", "rk3576", "w4a16", "g128", None),
    ("Qwen2.5-Math-1.5B-Instruct_w8a8_g128_rk3588.rkllm", "rk3588", "w8a8", "g128", None),
    ("Llama-3.2-1B-Instruct-rk3588-w8a8-opt-0-hybrid-ratio-0.0.rkllm", "rk3588", "w8a8", None, None),
    ("Qwen3-1.7B-RKLLM-v1.2.3.rkllm", None, None, None, "1.2.3"),
    ("qwen2-1.8B-rk3588.rkllm", "rk3588", None, None, None),
])
def test_parse_name(name, chip, dtype, group, tk):
    got = parse_name(name)
    assert (got["chip"], got["dtype"], got["group"], got["toolkit"]) == (chip, dtype, group, tk)


def test_missing_file(tmp_path):
    assert inspect_file(str(tmp_path / "nope.rkllm"))[0]["status"] == FAIL
