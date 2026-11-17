"""npuzoo run / serve against a stand-in for librkllmrt.so (no board needed).

The stand-in receives exactly the ctypes objects the real library would, and
answers through the same callback. tools/check_rkllm_abi.py separately
checks those objects' layouts against Rockchip's headers.
"""
import ctypes
import json
import threading
import urllib.error
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
        self.rkllm_set_function_tools = FakeFn(
            lambda h, sp, tools, tag: self.calls.append(("tools", sp.decode(), tools.decode(), tag.decode())) or 0)
        self.script = []        # optional: one list of chunks per run, used in order

    def _chunks_for_run(self):
        return self.script.pop(0) if self.script else self.chunks

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
        for c in self._chunks_for_run():
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


# ------------------------------------------------------------ Ollama API (Home Assistant, Open WebUI)

def test_ollama_version_tags_show(server):
    base, _ = server
    with urllib.request.urlopen(base + "/api/version", timeout=10) as r:
        assert json.load(r)["version"]
    with urllib.request.urlopen(base + "/api/tags", timeout=10) as r:
        m = json.load(r)["models"][0]
        assert m["name"] == "qwen3-test" and m["details"]["format"] == "rkllm"
    code, _, body = post(base + "/api/show", {"model": "qwen3-test"})
    assert code == 200 and "details" in json.loads(body)
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        assert b"running" in r.read()


def test_ollama_chat_streams_ndjson_by_default(server):
    base, lib = server
    code, headers, body = post(base + "/api/chat", {"model": "qwen3-test",
                                                   "messages": [{"role": "user", "content": "Hi"}]})
    lines = [json.loads(l) for l in body.splitlines() if l.strip()]
    assert headers["Content-Type"] == "application/x-ndjson"
    assert "".join(l["message"]["content"] for l in lines) == "Hello"
    last = lines[-1]
    assert last["done"] and last["done_reason"] == "stop"
    assert last["prompt_eval_count"] == 50 and last["eval_count"] == 12 and last["eval_duration"] == 1000 * 10**6


def test_ollama_chat_without_stream_and_options(server):
    base, lib = server
    code, _, body = post(base + "/api/chat", {"stream": False, "options": {"num_predict": 12},
                                             "messages": [{"role": "user", "content": "Hi"}]})
    out = json.loads(body)
    assert out["message"]["content"] == "Hello" and out["done_reason"] == "length"
    assert lib.calls[-1][-1] == 12


def test_ollama_generate(server):
    base, lib = server
    code, _, body = post(base + "/api/generate", {"prompt": "Say hi", "stream": False})
    out = json.loads(body)
    assert out["response"] == "Hello" and out["done"]
    assert lib.calls[-1][1] == "Say hi" and lib.calls[-1][3] == 0       # no kept history for generate
    code, _, body = post(base + "/api/generate", {"model": "qwen3-test"})
    assert json.loads(body)["done_reason"] == "load"


# ------------------------------------------------------------ tools and reasoning

LIGHT = [{"type": "function", "function": {"name": "set_light", "description": "Switch a light",
                                           "parameters": {"type": "object", "properties": {
                                               "room": {"type": "string"}}}}}]
CALL = b'<tool_call>\n{"name": "set_light", "arguments": {"room": "kitchen"}}\n</tool_call>'


def test_conversation_with_tools_keeps_system_for_the_runtime():
    c = Conversation()
    p = c.plan([{"role": "system", "content": "You run a house."}, {"role": "user", "content": "Lights on"}], LIGHT)
    assert p["reset"] and p["prompt"] == "Lights on" and p["system"] == "You run a house." and p["tools"] == LIGHT
    c.answered(p["after"], "", [{"name": "set_light", "arguments": {"room": "kitchen"}}], p["tools_key"])
    follow = [{"role": "system", "content": "You run a house. It is 10:02."},       # HA changes it every time
              {"role": "user", "content": "Lights on"},
              {"role": "assistant", "content": None, "tool_calls": [
                  {"id": "x", "type": "function", "function": {"name": "set_light", "arguments": '{"room": "kitchen"}'}}]},
              {"role": "tool", "tool_call_id": "x", "content": '{"success": true}'}]
    p = c.plan(follow, LIGHT)
    assert not p["reset"] and p["role"] == "tool" and json.loads(p["prompt"]) == [{"success": True}]
    assert c.plan(follow, LIGHT[:0] or None)["reset"]                               # different tools: start over


def test_conversation_tool_results_without_history_say_what_was_asked():
    p = Conversation().plan([{"role": "user", "content": "Lights on"},
                             {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "f"}}]},
                             {"role": "tool", "content": "ok"}])
    assert p["reset"] and p["role"] == "user" and p["prompt"] == 'Lights on\n\nTool results: ["ok"]'


def test_openai_tool_call_round_trip(server):
    base, lib = server
    lib.script = [[b"Sure. ", CALL], [b"The kitchen light is on."]]
    msgs = [{"role": "system", "content": "You run a house."}, {"role": "user", "content": "Kitchen light on"}]
    code, headers, body = post(base + "/v1/chat/completions", {"messages": msgs, "tools": LIGHT})
    out = json.loads(body)["choices"][0]
    assert out["finish_reason"] == "tool_calls" and out["message"]["content"] == "Sure."
    call = out["message"]["tool_calls"][0]
    assert call["function"]["name"] == "set_light" and json.loads(call["function"]["arguments"]) == {"room": "kitchen"}
    assert ("tools", "You run a house.", json.dumps(LIGHT), "tool_response") in lib.calls
    assert lib.calls[-1][1:3] == ("Kitchen light on", "user")                       # system went with the tools
    msgs += [out["message"], {"role": "tool", "tool_call_id": call["id"], "content": '{"ok": true}'}]
    code, headers, body = post(base + "/v1/chat/completions", {"messages": msgs, "tools": LIGHT})
    assert headers["X-Npuzoo-History"] == "continued"
    assert lib.calls[-1][1:4] == ('[{"ok": true}]', "tool", 1)
    assert json.loads(body)["choices"][0]["message"]["content"] == "The kitchen light is on."


def test_openai_streamed_tool_call(server):
    base, lib = server
    lib.script = [[b"On it. <tool", b"_call>\n", CALL[12:]]]
    code, headers, body = post(base + "/v1/chat/completions", {
        "stream": True, "tools": LIGHT, "messages": [{"role": "user", "content": "Kitchen light on"}]})
    events = [json.loads(l[6:]) for l in body.split("\n\n") if l.startswith("data: {")]
    deltas = [e["choices"][0]["delta"] for e in events]
    assert "".join(d.get("content", "") for d in deltas) == "On it. "
    calls = [d["tool_calls"] for d in deltas if "tool_calls" in d][0]
    assert calls[0]["function"]["name"] == "set_light" and events[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_tools_are_taken_out_again(server):
    base, lib = server
    lib.script = [[CALL], [b"Hi"]]
    post(base + "/v1/chat/completions", {"tools": LIGHT, "messages": [{"role": "user", "content": "a"}]})
    post(base + "/v1/chat/completions", {"messages": [{"role": "user", "content": "b"}]})
    assert [c for c in lib.calls if c[0] == "tools"][-1] == ("tools", "", "[]", "tool_response")


def test_openai_reasoning_is_separate(server):
    base, lib = server
    lib.script = [[b"<think>\nchecking\n</think>\n\n", b"Yes."]]
    code, _, body = post(base + "/v1/chat/completions", {"messages": [{"role": "user", "content": "?"}],
                                                       "enable_thinking": True})
    msg = json.loads(body)["choices"][0]["message"]
    assert msg["content"] == "Yes." and msg["reasoning_content"] == "checking"
    assert lib.calls[-1][0] == "run"


def test_ollama_tool_call_and_thinking(server):
    base, lib = server
    lib.script = [[b"<think>hmm</think>", CALL]]
    code, _, body = post(base + "/api/chat", {"tools": LIGHT, "think": True,
                                             "messages": [{"role": "user", "content": "Kitchen light on"}]})
    lines = [json.loads(l) for l in body.splitlines() if l.strip()]
    assert "".join(l["message"].get("thinking", "") for l in lines) == "hmm"
    calls = [l["message"]["tool_calls"] for l in lines if l["message"].get("tool_calls")][0]
    assert calls == [{"function": {"name": "set_light", "arguments": {"room": "kitchen"}}}] and lines[-1]["done"]
    # reasoning that was not asked for is left out
    lib.script = [[b"<think>hmm</think>", b"Done."]]
    code, _, body = post(base + "/api/chat", {"stream": False, "messages": [{"role": "user", "content": "x"}]})
    msg = json.loads(body)["message"]
    assert msg["content"] == "Done." and "thinking" not in msg


def test_ollama_show_capabilities(server):
    base, _ = server
    code, _, body = post(base + "/api/show", {"model": "qwen3-test"})
    assert {"completion", "tools", "thinking"} <= set(json.loads(body)["capabilities"])


def test_head_and_pull(server):
    base, _ = server
    req = urllib.request.Request(base + "/", method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
    assert json.loads(post(base + "/api/pull", {"model": "qwen3-test:latest"})[2])["status"] == "success"
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/api/pull", {"model": "llama3.2"})
    assert e.value.code == 404
