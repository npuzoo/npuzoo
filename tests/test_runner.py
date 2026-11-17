"""npuzoo run / serve against a stand-in for librkllmrt.so (no board needed).

The stand-in receives exactly the ctypes objects the real library would, and
answers through the same callback. tools/check_rkllm_abi.py separately
checks those objects' layouts against Rockchip's headers.
"""
import ctypes
import json
import threading
import urllib.request

import pytest

from npuzoo import rkllm_rt as rt
from npuzoo.runner import Conversation, make_handler, perf_line, _finish


class FakeFn(object):
    def __init__(self, fn):
        self.fn, self.argtypes, self.restype = fn, None, None

    def __call__(self, *a):
        return self.fn(*a)


class FakeLib(object):
    def __init__(self, profile, chunks=(b"Hel", b"lo"), fail=False):
        self.P, self.chunks, self.fail, self.calls = rt.PROFILES[profile], list(chunks), fail, []
        self.rkllm_createDefaultParam = FakeFn(lambda: self.P["param"]())
        self.rkllm_init = FakeFn(self._init)
        self.rkllm_run = FakeFn(self._run)
        self.rkllm_clear_kv_cache = FakeFn(lambda *a: self.calls.append(("clear", a[1])) or 0)
        self.rkllm_destroy = FakeFn(lambda h: self.calls.append(("destroy",)) or 0)
        self.rkllm_abort = FakeFn(lambda h: 0)

    def _init(self, handle_ref, param_ref, cb):
        self.param = param_ref._obj
        self.cb = cb._obj.result_callback if self.P["callback_struct"] else cb
        handle_ref._obj.value = 4242
        return 0

    def _run(self, handle, inp_ref, infer_ref, userdata):
        inp, infer = inp_ref._obj, infer_ref._obj
        self.calls.append(("run", inp.prompt_input.decode(), inp.role.decode(), infer.keep_history,
                           getattr(infer, "max_new_tokens", None)))
        if self.fail:
            self.cb(ctypes.pointer(rt.RKLLMResult()), None, rt.RUN_ERROR)
            return -1
        for c in self.chunks:
            r = rt.RKLLMResult()
            r.text = c
            self.cb(ctypes.pointer(r), None, rt.RUN_NORMAL)
        r = rt.RKLLMResult()
        r.perf.prefill_time_ms, r.perf.prefill_tokens = 250.0, 50
        r.perf.generate_time_ms, r.perf.generate_tokens = 1000.0, 12
        r.perf.memory_usage_mb = 1890.5
        self.cb(ctypes.pointer(r), None, rt.RUN_FINISH)
        return 0


@pytest.mark.parametrize("profile", ["1.3", "1.2"])
def test_session_generates_and_reports_perf(profile):
    lib = FakeLib(profile)
    s = rt.Session(lib, profile, "/m.rkllm", max_context_len=2048, max_new_tokens=256)
    assert lib.param.model_path == b"/m.rkllm" and lib.param.max_context_len == 2048
    assert lib.param.extend_param.enabled_cpus_mask == rt.CPU_BIG
    seen = []
    res = s.generate("hi", on_text=seen.append)
    assert res["text"] == "Hello" and seen == ["Hel", "lo"] and res["finished"]
    assert rt.tokens_per_second(res["perf"]) == (200.0, 12.0)
    s.close()
    assert ("destroy",) in lib.calls


def test_utf8_split_across_callbacks():
    lib = FakeLib("1.3", chunks=[b"\xe4\xbd", b"\xa0\xe5\xa5\xbd"])
    s = rt.Session(lib, "1.3", "/m.rkllm")
    assert s.generate("你好")["text"] == "你好"


def test_runtime_error_raises():
    s = rt.Session(FakeLib("1.3", fail=True), "1.3", "/m.rkllm")
    with pytest.raises(rt.RuntimeError_):
        s.generate("hi")


def test_profiles():
    assert rt.profile_for("1.3.1") == "1.3" and rt.profile_for("1.3.0") == "1.3"
    assert rt.profile_for("1.2.1") == "1.2" and rt.profile_for("1.2.3") == "1.2"
    assert rt.profile_for("1.2.0") is None and rt.profile_for("1.1.4") is None and rt.profile_for(None) is None


def test_max_new_tokens_per_run_only_on_13():
    lib = FakeLib("1.3")
    rt.Session(lib, "1.3", "/m.rkllm").generate("x", max_new_tokens=7)
    assert lib.calls[-1][-1] == 7


# ------------------------------------------------------------ conversation mapping

def test_conversation_continues_and_resets():
    c = Conversation()
    msgs = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]
    p = c.plan(msgs)
    assert p["reset"] and p["prompt"] == "Be brief.\n\nHi" and p["role"] == "user"
    c.answered(p["after"], "Hello!")
    msgs += [{"role": "assistant", "content": "Hello!"}, {"role": "user", "content": "And?"}]
    p = c.plan(msgs)
    assert not p["reset"] and p["prompt"] == "And?"
    c.answered(p["after"], "More.")
    edited = msgs[:2] + [{"role": "assistant", "content": "something else"}, {"role": "user", "content": "And?"}]
    assert c.plan(edited)["reset"]


def test_conversation_tool_messages_and_parts():
    c = Conversation()
    p = c.plan([{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url"}]}])
    assert p["prompt"] == "a"
    c.answered(p["after"], "call")
    p = c.plan([{"role": "user", "content": [{"type": "text", "text": "a"}]},
                {"role": "assistant", "content": "call"}, {"role": "tool", "content": "{\"t\": 21}"}])
    assert p["role"] == "tool" and not p["reset"]


def test_conversation_needs_a_user_message():
    with pytest.raises(ValueError):
        Conversation().plan([{"role": "assistant", "content": "x"}])


def test_finish_reason_and_perf_line():
    assert _finish({"perf": {"generate_tokens": 64}}, 64) == "length"
    assert _finish({"perf": {"generate_tokens": 3}}, 64) == "stop"
    line = perf_line({"prefill_ms": 250.0, "prefill_tokens": 50, "generate_ms": 1000.0,
                      "generate_tokens": 12, "memory_mb": 1890.5}, {"governor": "ondemand"})
    assert "prefill 200.0 tok/s" in line and "generate 12.0 tok/s" in line and "not pinned" in line


# ------------------------------------------------------------ OpenAI-compatible server

@pytest.fixture
def server():
    from http.server import ThreadingHTTPServer
    lib = FakeLib("1.3")
    session = rt.Session(lib, "1.3", "/m.rkllm")
    handler = make_handler(session, "qwen3-test", threading.Lock(), Conversation(), 1024, {"runtime": "1.3.1"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1], lib
    httpd.shutdown()
    httpd.server_close()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, dict(r.headers), r.read().decode()


def test_models_and_health(server):
    base, _ = server
    with urllib.request.urlopen(base + "/v1/models", timeout=10) as r:
        assert json.load(r)["data"][0]["id"] == "qwen3-test"
    with urllib.request.urlopen(base + "/health", timeout=10) as r:
        assert json.load(r)["runtime"] == "1.3.1"


def test_chat_completion(server):
    base, lib = server
    code, headers, body = post(base + "/v1/chat/completions", {
        "model": "qwen3-test", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 64})
    out = json.loads(body)
    assert code == 200 and out["choices"][0]["message"]["content"] == "Hello"
    assert out["usage"] == {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62}
    assert out["npuzoo"]["generate_tps"] == 12.0 and headers["X-Npuzoo-History"] == "reset"
    assert ("clear", 0) in lib.calls and lib.calls[-1][:4] == ("run", "Hi", "user", 1)
    # the client sends the history back: the runtime continues instead of starting over
    code, headers, body = post(base + "/v1/chat/completions", {"messages": [
        {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "More"}]})
    assert headers["X-Npuzoo-History"] == "continued" and lib.calls[-1][1] == "More"
    assert sum(1 for c in lib.calls if c[0] == "clear") == 1


def test_chat_stream(server):
    base, _ = server
    code, headers, body = post(base + "/v1/chat/completions", {
        "stream": True, "messages": [{"role": "user", "content": "Hi"}]})
    events = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "Hello"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_bad_requests(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/v1/chat/completions", {"messages": [{"role": "assistant", "content": "x"}]})
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/v1/completions", {"prompt": "x"})
    assert e.value.code == 404
