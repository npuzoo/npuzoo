"""npuzoo run / npuzoo serve — a .rkllm model on the NPU, from the shell or over HTTP.

run prints the runtime's own prefill and generate rates after each answer,
so every run is also an honest measurement. serve speaks the OpenAI chat
API (/v1/chat/completions, streaming or not; /v1/models) and the Ollama API
(/api/chat, /api/generate, /api/tags, /api/show, /api/version), so Home
Assistant's Ollama integration, Open WebUI and the openai client libraries
can use the board directly. Requests that offer tools get structured tool
calls back (runtime 1.2.1+ renders the tools into the model's template);
reasoning comes back apart from the answer.

Both check the file with `npuzoo inspect` against the board's chip and
runtime before loading it: a mismatch is refused with the reason instead of
ending in "load model file error!".

Status: built against the official headers of RKLLM 1.2.1 – 1.3.1 and
checked with tools/check_rkllm_abi.py; not yet run on a board.
"""
import ctypes
import glob
import json
import os
import sys
import threading
import time

from .doctor import collect, _find_lib, _lib_version
from .inspect import inspect_file, INSPECT_ICON
from .rkllm_rt import Session, profile_for, tokens_per_second, RuntimeError_, CPU_BIG, CPU_LITTLE
from .models import family_for_name
from .reply import (ReplyStream, split_reply, split_thinking, calls_key, arguments_json, arguments_dict,
                    opens_thinking)

HOME = os.path.expanduser(os.environ.get("NPUZOO_HOME", "~/.npuzoo"))


class SetupError(Exception):
    pass


def find_runtime(lib_path=None):
    """(path, version, profile) of the RKLLM runtime to use."""
    path = lib_path or os.environ.get("NPUZOO_RKLLM_LIB") or _find_lib(["librkllmrt.so"])
    if not path or not os.path.exists(path):
        raise SetupError("librkllmrt.so not found. Install Rockchip's RKLLM runtime (rknn-llm, "
                         "rkllm-runtime/Linux/librkllm_api/aarch64/) to /usr/lib, or pass --lib PATH. "
                         "Check with: npuzoo doctor")
    version = _lib_version(path, [rb"RKLLM SDK \(version:\s*([\w.]+)", rb"rkllm-runtime version:\s*([\d.]+\w*)"])
    profile = profile_for(version)
    if profile is None:
        raise SetupError("npuzoo run supports RKLLM runtime 1.2.1 to 1.3.1; %s is %s. Upgrade the runtime "
                         "(and use models built by the same toolkit version)." % (path, version or "unknown"))
    return path, version, profile


def resolve_model(name_or_path):
    """A .rkllm path: the argument itself, or the file of a pulled package."""
    if os.path.isfile(name_or_path):
        return name_or_path
    hits = sorted(glob.glob(os.path.join(HOME, "models", name_or_path, "*.rkllm")) +
                  glob.glob(os.path.join(HOME, "community", name_or_path, "**", "*.rkllm"), recursive=True))
    if hits:
        return hits[0]
    raise SetupError("No model file '%s'. Give a .rkllm path, or get one first: npuzoo find %s"
                     % (name_or_path, name_or_path))


def preflight(model, chip, version, force=False, out=sys.stdout):
    findings = inspect_file(model, board=chip, runtime=version)
    bad = [f for f in findings if f["status"] == "FAIL"]
    for f in bad:
        out.write("  %s %-14s %s\n" % (INSPECT_ICON[f["status"]], f["check"], f["detail"]))
        for line in f.get("fix") or []:
            out.write("      %s\n" % line)
    if bad and not force:
        raise SetupError("Not loading %s: the checks above say it will fail. (--force loads it anyway.)" % model)


def cpus_for(chip):
    # the big cores; RK3562 and RV1126B have no big/little split
    return (CPU_BIG, 4) if chip in ("rk3588", "rk3588s", "rk3576") else (CPU_LITTLE, 4)


def open_session(model, lib_path=None, force=False, context=4096, max_new_tokens=1024,
                 temperature=0.8, top_k=1, top_p=0.9, out=sys.stdout, ignore_eos=False):
    path, version, profile = find_runtime(lib_path)
    info = collect()
    chip = info.get("chip")
    model = resolve_model(model)
    preflight(model, chip, version, force=force, out=out)
    lib = ctypes.CDLL(path)
    mask, num = cpus_for(chip)
    out.write("Loading %s on %s with runtime %s ...\n" % (os.path.basename(model), (chip or "?").upper(), version))
    t0 = time.time()
    s = Session(lib, profile, model, max_context_len=context, max_new_tokens=max_new_tokens,
                temperature=temperature, top_k=top_k, top_p=top_p, cpus_mask=mask, cpus_num=num,
                ignore_eos=ignore_eos)
    load_s = time.time() - t0
    out.write("Loaded in %.1f s.\n" % load_s)
    return s, {"chip": chip, "runtime": version, "model": model, "governor": info.get("cpu_governor"),
               "npu_governor": info.get("npu_governor"), "board": info.get("board"),
               "kernel": info.get("kernel"), "npu_driver": info.get("npu_driver"), "mem_gb": info.get("mem_gb"),
               "profile": profile, "load_s": round(load_s, 2)}


def perf_line(perf, meta=None):
    pre, gen = tokens_per_second(perf)
    if not perf:
        return "(the runtime reported no timings)"
    line = "prefill %s tok/s (%d tokens) · generate %s tok/s (%d tokens) · %.0f MB" % (
        pre if pre is not None else "?", perf["prefill_tokens"], gen if gen is not None else "?",
        perf["generate_tokens"], perf["memory_mb"])
    if meta and meta.get("governor") and "performance" not in meta["governor"]:
        line += " · clocks not pinned (governor %s): everyday numbers, not vendor-benchmark ones" % meta["governor"]
    return line


def cmd_run(model, prompt=None, lib_path=None, force=False, context=4096, max_new_tokens=1024,
            temperature=0.8, think=False, as_json=False):
    try:
        session, meta = open_session(model, lib_path, force, context, max_new_tokens, temperature,
                                     out=sys.stderr if as_json else sys.stdout)
    except (SetupError, RuntimeError_, OSError) as e:
        print("✗ %s" % e)
        return 1
    try:
        if prompt is not None:
            res = session.generate(prompt, enable_thinking=think,
                                   on_text=None if as_json else (lambda t: (sys.stdout.write(t), sys.stdout.flush())))
            if as_json:
                pre, gen = tokens_per_second(res["perf"])
                print(json.dumps(dict(res, prefill_tps=pre, generate_tps=gen, **meta), ensure_ascii=False, indent=2))
            else:
                print("\n\n" + perf_line(res["perf"], meta))
            return 0
        print("Type a message; an empty line or Ctrl-D quits. /reset forgets the conversation.\n")
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            if not line.strip():
                break
            if line.strip() == "/reset":
                session.clear_history()
                print("(conversation cleared)")
                continue
            res = session.generate(line, enable_thinking=think, keep_history=True,
                                   on_text=lambda t: (sys.stdout.write(t), sys.stdout.flush()))
            print("\n  [%s]\n" % perf_line(res["perf"], meta))
        return 0
    except RuntimeError_ as e:
        print("\n✗ %s" % e)
        return 1
    finally:
        session.close()


# ------------------------------------------------------------ OpenAI-compatible server

def _text(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


TOOL_TAG = "tool_response"      # the marker Rockchip's own server demo gives the runtime


def _maybe_json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _key(m):
    """What a message must look like for the runtime's history to still match it."""
    role = m.get("role")
    text = _text(m.get("content"))
    if role == "assistant":
        return (role, split_thinking(text)[1].strip(), calls_key(m.get("tool_calls")))
    return (role, text)


def tools_key(tools):
    return json.dumps(tools, sort_keys=True) if tools else None


class Conversation(object):
    """Maps stateless API requests onto the runtime's kept history.

    The runtime keeps the conversation in its KV cache. A request whose
    messages extend what has been answered so far (and offers the same
    tools) continues it; anything else clears the cache and starts over from
    the latest user message. Without tools, the system message, which the
    runtime's built-in template cannot take as such, is placed before the
    first user message of each fresh conversation; with tools it goes to the
    runtime together with them.

    Tool results go to the runtime as role "tool", their contents as one
    JSON array, as in Rockchip's server demo.
    """

    def __init__(self):
        self.seen = []          # keys of what the runtime has in its history
        self.tools = None       # tools_key of the tools the runtime was given
        self.runtime_tools = False

    def plan(self, messages, tools=None):
        system = "\n".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
        conv = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
        if not conv or conv[-1].get("role") not in ("user", "tool"):
            raise ValueError("the last message must come from the user (or a tool)")
        # the new inputs are the user/tool messages after the last assistant reply
        i = len(conv)
        while i > 0 and conv[i - 1].get("role") in ("user", "tool"):
            i -= 1
        new = conv[i:]
        keys = [_key(m) for m in conv]
        tk = tools_key(tools)
        continuing = bool(self.seen) and keys[:i] == self.seen and tk == self.tools
        if all(m.get("role") == "tool" for m in new):
            results = json.dumps([_maybe_json(_text(m.get("content"))) for m in new], ensure_ascii=False)
            if continuing:
                role, text = "tool", results
            else:
                # the call these results answer is not in the runtime's history: say what was asked
                asked = next((_text(m.get("content")) for m in reversed(conv[:i]) if m.get("role") == "user"), "")
                role, text = "user", (asked + "\n\n" if asked else "") + "Tool results: " + results
        else:
            role, text = "user", "\n".join(_text(m.get("content")) for m in new)
        if not continuing and system and not tools:
            text = system + "\n\n" + text
        return {"reset": not continuing, "role": role, "prompt": text, "after": keys,
                "system": system, "tools": tools or None, "tools_key": tk}

    def answered(self, conv, reply, calls=None, tools_key=None):
        """conv: plan["after"]; reply: the answer as the client got it (no thinking, no call tags)."""
        self.seen = list(conv) + [("assistant", split_thinking(reply)[1].strip(), calls_key(calls))]
        self.tools = tools_key

    def forget(self):
        self.seen = []
        self.tools = None


def _chunk(cid, model, created, delta, finish=None):
    return {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


OLLAMA_VERSION = "0.6.0"       # the Ollama API level these endpoints follow; clients check it


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ollama_model_entry(model_name, meta=None):
    meta = meta or {}
    path = meta.get("model") or ""
    size = os.path.getsize(path) if path and os.path.exists(path) else 0
    from .inspect import parse_name
    from .models import family_for_name
    claims = parse_name(path or model_name)
    fam = family_for_name(model_name) or family_for_name(path)
    return {
        "name": model_name, "model": model_name, "modified_at": _now(), "size": size, "digest": "",
        "details": {"format": "rkllm", "family": fam["key"] if fam else "", "families": None,
                    "parameter_size": "", "quantization_level": claims.get("dtype") or ""},
    }


def ollama_stats(res, limit):
    """Ollama's closing counters, from the runtime's own (durations in nanoseconds)."""
    perf = (res or {}).get("perf") or {}
    pre_ms, gen_ms = perf.get("prefill_ms") or 0.0, perf.get("generate_ms") or 0.0
    return {
        "done_reason": _finish(res or {}, limit),
        "total_duration": int((pre_ms + gen_ms) * 1e6), "load_duration": 0,
        "prompt_eval_count": perf.get("prefill_tokens", 0), "prompt_eval_duration": int(pre_ms * 1e6),
        "eval_count": perf.get("generate_tokens", 0), "eval_duration": int(gen_ms * 1e6),
    }


def make_handler(session, model_name, lock, conversation, max_new_tokens, meta=None):
    from http.server import BaseHTTPRequestHandler
    starts_thinking = opens_thinking(model_name) or opens_thinking((meta or {}).get("model"))
    fam = family_for_name(model_name) or family_for_name((meta or {}).get("model") or "")
    can_think = starts_thinking or bool(fam and fam["key"] in ("qwen3", "qwen3.5"))

    def run_turn(plan, limit, think, emit=None, chat=True):
        """One turn; the caller holds the lock. emit(kind, text) streams the reply.

        Returns (res, thinking, content, calls)."""
        if plan["reset"]:
            session.clear_history(keep_system_prompt=False)
            conversation.forget()
            if plan.get("tools"):
                session.set_function_tools(plan["system"], json.dumps(plan["tools"], ensure_ascii=False), TOOL_TAG)
                conversation.runtime_tools = True
            elif conversation.runtime_tools:
                # take the tools out of the template again (an empty list renders no tools section)
                session.set_function_tools("", "[]", TOOL_TAG)
                conversation.runtime_tools = False
        tools = plan.get("tools")
        if emit:
            got = {"thinking": [], "content": []}

            def sink(kind, text):
                got[kind].append(text)
                emit(kind, text)
            rs = ReplyStream(sink, tools=bool(tools), tool_defs=tools, thinking=starts_thinking)
            res = session.generate(plan["prompt"], role=plan["role"], keep_history=chat, max_new_tokens=limit,
                                   enable_thinking=bool(think), on_text=rs.feed)
            calls = rs.finish()
            thinking, content = "".join(got["thinking"]).strip(), "".join(got["content"]).strip()
        else:
            res = session.generate(plan["prompt"], role=plan["role"], keep_history=chat, max_new_tokens=limit,
                                   enable_thinking=bool(think))
            thinking, content, calls = split_reply(res["text"], tools=bool(tools), tool_defs=tools)
        if chat:
            conversation.answered(plan["after"], content, calls, plan.get("tools_key"))
        return res, thinking, content, calls

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "npuzoo"

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        def _json(self, code, obj, headers=None):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code, message, kind="invalid_request_error"):
            self._json(code, {"error": {"message": message, "type": kind}})

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(req, dict):
                raise ValueError("the request body must be a JSON object")
            return req

        def _start_stream(self, ctype, headers=None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.close_connection = True

        # ---------------------------------------------------------------- Ollama
        def _ollama(self, path):
            """Ollama's /api/chat and /api/generate: streams NDJSON by default, like Ollama."""
            chat = path == "/api/chat"
            try:
                req = self._body()
                if chat:
                    plan = conversation.plan(req.get("messages") or [], req.get("tools"))
                else:
                    if not (req.get("prompt") or "").strip():
                        # Ollama answers an empty generate request by (pre)loading the model
                        return self._json(200, {"model": model_name, "created_at": _now(), "response": "",
                                                "done": True, "done_reason": "load"})
                    prompt = req["prompt"] if not req.get("system") else req["system"] + "\n\n" + req["prompt"]
                    plan = {"reset": True, "role": "user", "prompt": prompt, "after": None}
            except (ValueError, TypeError) as e:
                return self._json(400, {"error": str(e)})
            stream = req.get("stream", True) is not False
            think = req.get("think")
            opts = req.get("options") or {}
            n = opts.get("num_predict")
            limit = n if isinstance(n, int) and n > 0 else None

            def message(content="", thinking="", calls=None):
                if not chat:
                    obj = {"response": content}
                    if thinking:
                        obj["thinking"] = thinking
                    return obj
                msg = {"role": "assistant", "content": content}
                if thinking:
                    msg["thinking"] = thinking
                if calls:
                    msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": arguments_dict(c["arguments"])}}
                                         for c in calls]
                return {"message": msg}

            def frame(body, done=False, res=None):
                obj = {"model": model_name, "created_at": _now()}
                obj.update(body)
                obj["done"] = done
                if done:
                    obj.update(ollama_stats(res, limit or max_new_tokens))
                return obj

            with lock:
                if stream:
                    self._start_stream("application/x-ndjson")

                    def send(obj):
                        self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()

                    def emit(kind, text):
                        if kind == "content":
                            send(frame(message(text)))
                        elif think:                       # reasoning only when it was asked for
                            send(frame(message("", text)))
                    try:
                        res, _, _, calls = run_turn(plan, limit, think, emit, chat)
                    except RuntimeError_ as e:
                        send({"error": str(e)})
                        return
                    if calls:
                        send(frame(message("", "", calls)))
                    send(frame(message(""), True, res))
                    return
                try:
                    res, thinking, content, calls = run_turn(plan, limit, think, None, chat)
                except RuntimeError_ as e:
                    return self._json(500, {"error": str(e)})
            self._json(200, frame(message(content, thinking if think else "", calls), True, res))

        # ---------------------------------------------------------------- OpenAI
        def _openai(self):
            try:
                req = self._body()
                plan = conversation.plan(req.get("messages") or [], req.get("tools"))
            except (ValueError, TypeError) as e:
                return self._error(400, str(e))
            stream = bool(req.get("stream"))
            limit = req.get("max_tokens") or req.get("max_completion_tokens")
            think = req.get("enable_thinking", (req.get("chat_template_kwargs") or {}).get("enable_thinking"))
            cid, created = "chatcmpl-%d" % int(time.time() * 1000), int(time.time())
            with lock:
                headers = {"X-Npuzoo-History": "reset" if plan["reset"] else "continued"}
                if stream:
                    self._start_stream("text/event-stream", headers)

                    def send(obj):
                        self.wfile.write(("data: %s\n\n" % json.dumps(obj, ensure_ascii=False)).encode("utf-8"))
                        self.wfile.flush()

                    def emit(kind, text):
                        field = "content" if kind == "content" else "reasoning_content"
                        send(_chunk(cid, model_name, created, {field: text}))
                    send(_chunk(cid, model_name, created, {"role": "assistant"}))
                    try:
                        res, _, _, calls = run_turn(plan, limit, think, emit)
                    except RuntimeError_ as e:
                        send({"error": {"message": str(e), "type": "runtime_error"}})
                        self.wfile.write(b"data: [DONE]\n\n")
                        return
                    if calls:
                        send(_chunk(cid, model_name, created, {"tool_calls": [
                            {"index": i, "id": "call_%d_%d" % (created, i), "type": "function",
                             "function": {"name": c["name"], "arguments": arguments_json(c["arguments"])}}
                            for i, c in enumerate(calls)]}))
                    finish = "tool_calls" if calls else _finish(res, limit or max_new_tokens)
                    send(_chunk(cid, model_name, created, {}, finish))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    return
                try:
                    res, thinking, content, calls = run_turn(plan, limit, think)
                except RuntimeError_ as e:
                    return self._error(500, str(e), "runtime_error")
            perf = res["perf"] or {}
            pre, gen = tokens_per_second(res["perf"])
            msg = {"role": "assistant", "content": content if (content or not calls) else None}
            if thinking:
                msg["reasoning_content"] = thinking
            if calls:
                msg["tool_calls"] = [{"id": "call_%d_%d" % (created, i), "type": "function",
                                      "function": {"name": c["name"], "arguments": arguments_json(c["arguments"])}}
                                     for i, c in enumerate(calls)]
            self._json(200, {
                "id": cid, "object": "chat.completion", "created": created, "model": model_name,
                "choices": [{"index": 0, "message": msg,
                             "finish_reason": "tool_calls" if calls else _finish(res, limit or max_new_tokens)}],
                "usage": {"prompt_tokens": perf.get("prefill_tokens", 0),
                          "completion_tokens": perf.get("generate_tokens", 0),
                          "total_tokens": perf.get("prefill_tokens", 0) + perf.get("generate_tokens", 0)},
                "npuzoo": {"prefill_tps": pre, "generate_tps": gen, "memory_mb": perf.get("memory_mb")},
            }, headers)

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/api/version":
                return self._json(200, {"version": OLLAMA_VERSION})
            if path == "/api/tags":
                return self._json(200, {"models": [ollama_model_entry(model_name, meta)]})
            if path == "/api/ps":
                return self._json(200, {"models": [dict(ollama_model_entry(model_name, meta), size_vram=0)]})
            if path in ("/v1/models", "/models"):
                return self._json(200, {"object": "list", "data": [
                    {"id": model_name, "object": "model", "created": 0, "owned_by": "npuzoo"}]})
            if path == "":
                body = b"npuzoo is running (OpenAI and Ollama APIs)"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if path == "/health":
                return self._json(200, {"status": "ok", "model": model_name, "runtime": (meta or {}).get("runtime")})
            self._error(404, "unknown path %s" % self.path)

        def do_HEAD(self):
            # Ollama clients check that the server is up with HEAD /
            self.send_response(200 if self.path.split("?")[0].rstrip("/") == "" else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            path = self.path.split("?")[0].rstrip("/")
            if path in ("/api/chat", "/api/generate"):
                return self._ollama(path)
            if path == "/api/pull":
                try:
                    want = (self._body().get("model") or "").split(":")[0]
                except (ValueError, TypeError):
                    want = ""
                if want in ("", model_name):
                    return self._json(200, {"status": "success"})
                return self._json(404, {"error": "this server runs one model, %s; put another on the board with "
                                                 "`npuzoo get` and serve that" % model_name})
            if path == "/api/show":
                entry = ollama_model_entry(model_name, meta)
                caps = ["completion", "tools"] + (["thinking"] if can_think else [])
                return self._json(200, {"modelfile": "", "parameters": "", "template": "",
                                        "details": entry["details"], "model_info": {}, "capabilities": caps})
            if path in ("/v1/chat/completions", "/chat/completions"):
                return self._openai()
            self._error(404, "unknown path %s" % self.path)

    return Handler


def _finish(res, limit):
    perf = res.get("perf") or {}
    return "length" if limit and perf.get("generate_tokens", 0) >= int(limit) else "stop"


def cmd_serve(model, host="0.0.0.0", port=8080, lib_path=None, force=False, context=4096,
              max_new_tokens=1024, temperature=0.8, name=None):
    from http.server import ThreadingHTTPServer
    try:
        session, meta = open_session(model, lib_path, force, context, max_new_tokens, temperature)
    except (SetupError, RuntimeError_, OSError) as e:
        print("✗ %s" % e)
        return 1
    model_name = name or os.path.splitext(os.path.basename(meta["model"]))[0]
    handler = make_handler(session, model_name, threading.Lock(), Conversation(), max_new_tokens, meta)
    httpd = ThreadingHTTPServer((host, port), handler)
    print("Serving %s at http://%s:%d  (OpenAI API under /v1, Ollama API under /api; Ctrl-C stops)"
          % (model_name, host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        session.close()
    return 0
