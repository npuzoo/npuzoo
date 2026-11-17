"""The weekly index builder, tested on recorded API shapes (no network)."""
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bci", ROOT / "tools" / "build_community_index.py")
bci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bci)

LISTED = {
    "id": "alice/Qwen3-1.7B-rk3588",
    "downloads": 912,
    "lastModified": "2026-10-03T08:12:44.000Z",
    "gated": False,
    "tags": ["license:apache-2.0", "base_model:Qwen/Qwen3-1.7B", "base_model:quantized:Qwen/Qwen3-1.7B"],
    "siblings": [{"rfilename": "README.md"}, {"rfilename": "Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm"}],
}
DETAIL = {
    "id": "alice/Qwen3-1.7B-rk3588",
    "lastModified": "2026-10-03T08:12:44.000Z",
    "siblings": [
        {"rfilename": "README.md", "size": 812},
        {"rfilename": "Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm", "size": 2312345678,
         "lfs": {"sha256": "ab" * 32, "size": 2312345678, "pointerSize": 135}},
        {"rfilename": "old/x.RKLLM", "size": 99, "lfs": {"oid": "sha256:" + "cd" * 32, "size": 1999999999}},
    ],
}


def test_has_rkllm():
    assert bci.has_rkllm(LISTED)
    assert not bci.has_rkllm({"siblings": [{"rfilename": "m.rknn"}]})
    assert not bci.has_rkllm({})


def test_licence_and_base_model_from_tags():
    assert bci.license_of(LISTED) == "apache-2.0"
    assert bci.base_model_of(LISTED) == "Qwen/Qwen3-1.7B"


def test_card_data_wins_and_lists_are_flattened():
    m = {"cardData": {"license": ["mit"], "base_model": ["Qwen/Qwen3-4B"]}, "tags": ["license:apache-2.0"]}
    assert bci.license_of(m) == "mit" and bci.base_model_of(m) == "Qwen/Qwen3-4B"


def test_files_from_detail():
    files = bci.files_from_detail(LISTED, DETAIL)
    assert [f["path"] for f in files] == ["Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm", "old/x.RKLLM"]
    f = files[0]
    assert f["bytes"] == 2312345678 and f["sha256"] == "ab" * 32
    assert f["updated"] == "2026-10-03" and f["downloads"] == 912 and not f["gated"]
    # LFS size wins over the pointer size; an "oid" form is accepted too
    assert files[1]["bytes"] == 1999999999 and files[1]["sha256"] == "cd" * 32


def test_detail_missing_is_empty():
    assert bci.files_from_detail(LISTED, None) == []


def test_next_link():
    h = '<https://huggingface.co/api/models?search=rk3588&cursor=abc>; rel="next"'
    assert bci.next_link(h).endswith("cursor=abc")
    assert bci.next_link(None) is None
    assert bci.next_link('<https://x>; rel="prev"') is None


def test_list_url_expands_what_the_index_needs():
    u = bci.list_url("search", "rk3588")
    for e in ("siblings", "downloads", "lastModified", "tags", "cardData", "gated"):
        assert "expand%5B%5D=" + e in u


def test_dump_is_valid_json_one_file_per_line():
    index = {"schema": 1, "generated": "2026-11-17T04:23Z", "repos": 1,
             "files": bci.files_from_detail(LISTED, DETAIL)}
    text = bci.dump(index)
    assert json.loads(text)["files"][0]["repo"] == "alice/Qwen3-1.7B-rk3588"
    assert sum(1 for line in text.splitlines() if line.startswith('{"base_model"')) == 2


def test_refuses_to_write_a_tiny_index(tmp_path, monkeypatch):
    monkeypatch.setattr(bci, "build", lambda: {"files": [], "repos": 0})
    out = tmp_path / "c.json"
    assert bci.main(["--out", str(out)]) == 1 and not out.exists()
