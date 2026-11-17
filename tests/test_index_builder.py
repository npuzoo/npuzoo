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
    monkeypatch.setattr(bci, "build", lambda **kw: {"files": [], "repos": 0})
    out = tmp_path / "c.json"
    assert bci.main(["--out", str(out)]) == 1 and not out.exists()


# ------------------------------------------------------------ ModelScope

MS_LIST_OPENAPI = {"success": True, "data": {"models": [
    {"id": "radxa/Qwen3-1.7B-RKLLM", "downloads": 1234, "license": "apache-2.0",
     "last_modified": "2026-09-01T10:00:00Z"},
    {"owner": "cix", "name": "Qwen2.5-VL", "downloads": 9},
], "total_count": 2}}
MS_LIST_LEGACY = {"Code": 200, "Data": {"Model": {"Models": [
    {"Path": "AXERA-TECH", "Name": "Qwen3-0.6B", "Downloads": 77, "LastUpdatedTime": 1760000000}],
    "TotalCount": 1}}}
MS_FILES = {"Code": 200, "Data": {"Files": [
    {"Path": "rk3588", "Type": "tree"},
    {"Path": "rk3588/Qwen3-1.7B-w8a8-rk3588-1.2.1.rkllm", "Type": "blob", "Size": 2312345678, "Sha256": "ef" * 32},
    {"Path": "README.md", "Type": "blob", "Size": 100, "Sha256": "00" * 32},
]}, "Success": True}


def test_ms_items_both_api_generations():
    assert [bci.ms_repo_id(i) for i in bci.ms_items(MS_LIST_OPENAPI)] == ["radxa/Qwen3-1.7B-RKLLM", "cix/Qwen2.5-VL"]
    assert [bci.ms_repo_id(i) for i in bci.ms_items(MS_LIST_LEGACY)] == ["AXERA-TECH/Qwen3-0.6B"]
    assert bci.ms_items(None) == [] and bci.ms_items({"Code": 500}) == []


def test_ms_files_keeps_rkllm_blobs():
    assert bci.ms_files(MS_FILES) == [("rk3588/Qwen3-1.7B-w8a8-rk3588-1.2.1.rkllm", 2312345678, "ef" * 32)]
    assert bci.ms_files({"Data": []}) == [] and bci.ms_files({}) == []


def test_ms_entries():
    item = bci.ms_items(MS_LIST_OPENAPI)[0]
    e = bci.ms_entries(item, bci.ms_files(MS_FILES))[0]
    assert e["source"] == "modelscope" and e["repo"] == "radxa/Qwen3-1.7B-RKLLM"
    assert e["downloads"] is None and e["downloads_total"] == 1234 and e["updated"] == "2026-09-01"
    legacy = bci.ms_entries(bci.ms_items(MS_LIST_LEGACY)[0], [("m.rkllm", 1, None)])[0]
    assert legacy["updated"] == "2025-10-09"


def test_modelscope_failure_keeps_huggingface(monkeypatch):
    monkeypatch.setattr(bci, "QUERIES", [])
    def boom(sleep=0):
        raise RuntimeError("down")
    monkeypatch.setattr(bci, "build_modelscope", boom)
    idx = bci.build(sleep=0)
    assert idx["sources"] == {"huggingface": 0, "modelscope": 0}



def test_modelscope_page_size_is_within_the_api_limit():
    assert bci.MS_PAGE <= 50


def test_modelscope_request_failures_are_skipped(monkeypatch):
    import http.client
    calls = []

    def flaky(url, tries=6):
        calls.append(url)
        raise http.client.IncompleteRead(b"partial", 100)
    monkeypatch.setattr(bci, "_get", flaky)
    assert bci._ms_get("https://modelscope.example/api/v1/models/x/repo/files") is None
    assert len(calls) == 1


def test_modelscope_download_field_names():
    assert bci.ms_downloads({"Downloads": 12}) == 12
    assert bci.ms_downloads({"download_count": 7}) == 7
    assert bci.ms_downloads({"TotalDownloadsCount": 9, "name": "x"}) == 9
    assert bci.ms_downloads({"downloads": True}) is None and bci.ms_downloads({}) is None
