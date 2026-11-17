import hashlib
import io
import json
import os

import pytest

from npuzoo import community
from npuzoo.community import claims_for, judge, search, download, cmd_find, cmd_get, YES, MAYBE, NO

RKLLM_HEAD = bytes.fromhex("daeeb33603000000")


def entry(repo, path, **kw):
    e = {"repo": repo, "path": path, "bytes": 2_000_000_000, "sha256": "0" * 64,
         "updated": "2026-10-01", "downloads": 10, "license": "apache-2.0",
         "base_model": None, "gated": False}
    e.update(kw)
    return e


INDEX = {
    "schema": 1, "generated": "2026-11-17T04:23Z",
    "files": [
        entry("alice/Qwen3-1.7B-rk3588", "Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm", downloads=900,
              base_model="Qwen/Qwen3-1.7B"),
        entry("bob/qwen3-rkllm-1.3.1", "rk3576/Qwen3-1.7B-w4a16.rkllm", downloads=50),
        entry("carol/Qwen3-1.7B-NPU", "model.rkllm", downloads=4000),
        entry("dave/qwen3-1.7b", "qwen3-1.7b-rk3588-w4a16.rkllm", downloads=20),
        entry("erin/Llama-3.2-1B-rk3588-1.1.4", "llama.rkllm", downloads=300),
    ],
}


# ------------------------------------------------------------ claims

def test_claims_fall_back_to_folder_then_repo():
    c = claims_for(INDEX["files"][1])
    assert c == {"chip": "rk3576", "dtype": "w4a16", "group": None, "toolkit": "1.3.1"}


def test_claims_from_repo_name_only():
    c = claims_for(INDEX["files"][4])
    assert c["chip"] == "rk3588" and c["toolkit"] == "1.1.4" and c["dtype"] is None


def test_filename_wins_over_repo():
    e = entry("x/model-rk3576", "m-rk3588-w8a8.rkllm")
    assert claims_for(e)["chip"] == "rk3588"


# ------------------------------------------------------------ judging

def test_fits():
    assert judge(INDEX["files"][0], "rk3588", "1.2.1")[0] == YES


def test_wrong_chip_is_no():
    v, why = judge(INDEX["files"][1], "rk3588", "1.3.1")
    assert v == NO and any("RK3576" in r for r in why)


def test_w4a16_on_rk3588_is_no_even_without_board():
    assert judge(INDEX["files"][3])[0] == NO


def test_toolkit_newer_than_runtime_is_no():
    assert judge(INDEX["files"][0], "rk3588", "1.2.0")[0] == NO


def test_name_says_nothing_is_maybe():
    v, why = judge(INDEX["files"][2], "rk3588", "1.3.1")
    assert v == MAYBE and any("chip" in r for r in why)


def test_rk3588s_board_takes_rk3588_files():
    assert judge(INDEX["files"][0], "rk3588s", "1.2.1")[0] == YES


def test_older_toolkit_is_maybe_with_a_reason():
    # Rockchip does not document which older models newer runtimes still load
    v, why = judge(INDEX["files"][0], "rk3588", "1.3.1")
    assert v == MAYBE and any("too old" in r for r in why)


def test_gated_is_flagged():
    v, why = judge(dict(INDEX["files"][0], gated=True), "rk3588", "1.3.1")
    assert any("HF_TOKEN" in r for r in why)


# ------------------------------------------------------------ search

def test_search_ranks_fit_before_downloads():
    rows = search(INDEX, "qwen3 1.7b", "rk3588", "1.2.1")
    assert [r["repo"] for r in rows][:2] == ["alice/Qwen3-1.7B-rk3588", "carol/Qwen3-1.7B-NPU"]
    assert rows[-1]["verdict"] == NO


def test_search_terms_all_must_match():
    assert [r["repo"] for r in search(INDEX, "llama")] == ["erin/Llama-3.2-1B-rk3588-1.1.4"]
    assert search(INDEX, "llama qwen") == []


def test_search_matches_base_model():
    assert [r["repo"] for r in search(INDEX, "qwen/qwen3-1.7b")] == ["alice/Qwen3-1.7B-rk3588"]


@pytest.fixture
def index_file(tmp_path):
    p = tmp_path / "community.json"
    p.write_text(json.dumps(INDEX))
    return str(p)


def test_find_hides_files_that_will_not_load(index_file, capsys):
    assert cmd_find("qwen3", board="rk3588", runtime="1.2.1", index_src=index_file) == 0
    out = capsys.readouterr().out
    assert "alice/Qwen3-1.7B-rk3588" in out and "dave/qwen3-1.7b" not in out
    assert "2 file(s) hidden" in out
    assert "npuzoo get alice/Qwen3-1.7B-rk3588 Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm" in out


def test_find_all_shows_them(index_file, capsys):
    cmd_find("qwen3", board="rk3588", runtime="1.3.1", index_src=index_file, show_all=True)
    assert "dave/qwen3-1.7b" in capsys.readouterr().out


def test_find_json(index_file, capsys):
    cmd_find("llama", board="rk3588", runtime="1.3.1", index_src=index_file, as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert data["results"][0]["verdict"] == MAYBE    # toolkit 1.1.4 is older than runtime 1.3.1
    assert data["results"][0]["claims"]["toolkit"] == "1.1.4"


def test_find_nothing(index_file, capsys):
    assert cmd_find("mistral", board="rk3588", index_src=index_file) == 1


# ------------------------------------------------------------ download

class FakeResp(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def getcode(self):
        return self.status


def _payload():
    return RKLLM_HEAD + b"\0" * (20 * 1024 * 1024 - len(RKLLM_HEAD))


def test_download_verifies_and_renames(tmp_path, monkeypatch):
    data = _payload()
    monkeypatch.setattr(community, "_open", lambda url, start=0: FakeResp(data))
    out = str(tmp_path / "m.rkllm")
    ok, msg = download("u", out, len(data), hashlib.sha256(data).hexdigest(), progress=False)
    assert ok and os.path.getsize(out) == len(data) and not os.path.exists(out + ".part")


def test_download_bad_checksum_deletes_part(tmp_path, monkeypatch):
    data = _payload()
    monkeypatch.setattr(community, "_open", lambda url, start=0: FakeResp(data))
    out = str(tmp_path / "m.rkllm")
    ok, msg = download("u", out, len(data), "f" * 64, progress=False)
    assert not ok and "SHA-256" in msg
    assert not os.path.exists(out) and not os.path.exists(out + ".part")


def test_download_resumes(tmp_path, monkeypatch):
    data = _payload()
    out = str(tmp_path / "m.rkllm")
    with open(out + ".part", "wb") as f:
        f.write(data[:1000])
    seen = {}

    def fake_open(url, start=0):
        seen["start"] = start
        return FakeResp(data[start:], status=206)

    monkeypatch.setattr(community, "_open", fake_open)
    ok, _ = download("u", out, len(data), hashlib.sha256(data).hexdigest(), progress=False)
    assert ok and seen["start"] == 1000


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    data = _payload()
    out = str(tmp_path / "m.rkllm")
    with open(out + ".part", "wb") as f:
        f.write(b"garbage")
    monkeypatch.setattr(community, "_open", lambda url, start=0: FakeResp(data, status=200))
    ok, _ = download("u", out, len(data), hashlib.sha256(data).hexdigest(), progress=False)
    assert ok


def test_download_short_keeps_part_for_resume(tmp_path, monkeypatch):
    data = _payload()
    monkeypatch.setattr(community, "_open", lambda url, start=0: FakeResp(data[:5000]))
    out = str(tmp_path / "m.rkllm")
    ok, msg = download("u", out, len(data), None, progress=False)
    assert not ok and "resume" in msg and os.path.getsize(out + ".part") == 5000


# ------------------------------------------------------------ get

def test_get_refuses_wrong_chip_without_download(index_file, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(community, "_open", lambda *a, **k: pytest.fail("must not download"))
    rc = cmd_get("bob/qwen3-rkllm-1.3.1", "rk3576/Qwen3-1.7B-w4a16.rkllm", board="rk3588",
                 runtime="1.3.1", index_src=index_file, dest=str(tmp_path))
    assert rc == 1 and "Not downloading" in capsys.readouterr().out


def test_get_downloads_checks_and_inspects(tmp_path, monkeypatch, capsys):
    data = _payload()
    idx = {"files": [entry("alice/m", "m-rk3588-w8a8-1.2.1.rkllm", bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest())]}
    p = tmp_path / "idx.json"
    p.write_text(json.dumps(idx))
    monkeypatch.setattr(community, "_open", lambda url, start=0: FakeResp(data))
    rc = cmd_get("alice/m", "m-rk3588-w8a8-1.2.1.rkllm", board="rk3588", runtime="1.3.1",
                 index_src=str(p), dest=str(tmp_path / "dl"))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "SHA-256 match" in out and os.path.exists(tmp_path / "dl" / "m-rk3588-w8a8-1.2.1.rkllm")


def test_resolve_url_quotes_and_honours_mirror(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com/")
    assert community.resolve_url("a/b", "dir/x y.rkllm") == "https://hf-mirror.com/a/b/resolve/main/dir/x%20y.rkllm"


# ------------------------------------------------------------ index cache

def test_remote_index_cached_for_a_day(tmp_path, monkeypatch):
    monkeypatch.setattr(community, "HOME", str(tmp_path))
    monkeypatch.setattr(community, "CACHE", str(tmp_path / "community.json"))
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        return io.BytesIO(json.dumps(INDEX).encode())

    monkeypatch.setattr(community.urllib.request, "urlopen", fake_urlopen)
    community.load_index("https://example.test/i.json")
    community.load_index("https://example.test/i.json")
    assert len(calls) == 1
    community.load_index("https://example.test/i.json", refresh=True)
    assert len(calls) == 2


def test_remote_index_falls_back_to_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(community, "HOME", str(tmp_path))
    cache = tmp_path / "community.json"
    cache.write_text(json.dumps(INDEX))
    os.utime(cache, (0, 0))              # stale
    monkeypatch.setattr(community, "CACHE", str(cache))

    def boom(req, timeout=0):
        raise OSError("offline")

    monkeypatch.setattr(community.urllib.request, "urlopen", boom)
    idx, where = community.load_index("https://example.test/i.json")
    assert where == str(cache) and len(idx["files"]) == 5
