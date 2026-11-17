"""Turning the runtime's raw text into what API clients expect.

The runtime hands back the model's words as they come, tags and all. Two
kinds of tags matter to clients:

* <think>...</think> — Qwen3 and DeepSeek-R1-style reasoning. Clients want
  it apart from the answer (Ollama's message.thinking, the
  reasoning_content field that OpenAI-style servers use) or not at all.
* <tool_call>...</tool_call> — function calls, when the request offered
  tools. Rockchip's runtime renders the tools into the model's own chat
  template (rkllm_set_function_tools, runtime 1.2.1+) but returns the call
  as text; clients want it as structured tool_calls. The two formats below
  are the ones Rockchip's own server demo parses: JSON inside the tag
  (Qwen2.5, Qwen3) and <function=...><parameter=...> inside it (Qwen3.5,
  Qwen3-Coder).

ReplyStream does this while the text is still arriving, holding back only
what might turn out to be a tag, so answers still stream word by word.
"""
import json
import re

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
CALL_OPEN, CALL_CLOSE = "<tool_call>", "</tool_call>"

_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
_FUNC = re.compile(r"<function=([^>\s]+)>\s*(.*?)\s*</function>", re.S)
_PARAM = re.compile(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", re.S)
_THINK = re.compile(r"^\s*(?:<think>)?(.*?)</think>\s*", re.S)


def _tail_overlap(text, tag):
    """How many characters at the end of text could be the start of tag."""
    for k in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:k]):
            return k
    return 0


def param_types(tools):
    """{function name: {parameter: JSON-schema type}} from OpenAI or Ollama tool definitions."""
    out = {}
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        f = t.get("function", t)
        props = (f.get("parameters") or {}).get("properties") or {}
        out[f.get("name")] = {k: (v or {}).get("type") for k, v in props.items() if isinstance(v, dict)}
    return out


def _coerce(value, kind):
    """A <parameter> value is text; give it the type the tool's schema declares."""
    if kind in ("integer", "number", "boolean", "object", "array", "null"):
        probe = value.lower() if kind == "boolean" else value
        try:
            return json.loads(probe)
        except ValueError:
            return value
    return value


def parse_tool_calls(text, tools=None):
    """(content, calls) — calls are [{"name", "arguments"}], arguments a dict where possible.

    Text outside complete <tool_call> blocks is the content. A block that
    cannot be read leaves the whole reply as content, so nothing is lost.
    """
    blocks = _BLOCK.findall(text)
    if not blocks:
        return text, []
    types = param_types(tools)
    calls = []
    for block in blocks:
        if block.startswith("{"):
            try:
                obj = json.loads(block)
            except ValueError:
                return text, []
            if not isinstance(obj, dict) or not obj.get("name"):
                return text, []
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    pass
            calls.append({"name": obj["name"], "arguments": args if args is not None else {}})
        else:
            found = _FUNC.findall(block)
            if not found:
                return text, []
            for name, body in found:
                kinds = types.get(name, {})
                calls.append({"name": name, "arguments": {
                    k: _coerce(v.strip(), kinds.get(k)) for k, v in _PARAM.findall(body)}})
    return _BLOCK.sub("", text).strip(), calls


def split_thinking(text):
    """(thinking, answer). Handles both <think>...</think> and R1-style replies
    whose opening tag was part of the prompt."""
    m = _THINK.match(text)
    if not m:
        return "", text
    return m.group(1).strip(), text[m.end():]


def arguments_json(args):
    """OpenAI wants the arguments as a JSON string."""
    return args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)


def arguments_dict(args):
    """Ollama wants them as an object."""
    if isinstance(args, dict):
        return args
    try:
        val = json.loads(args)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def calls_key(calls):
    """A comparable form of tool calls, whether they came from us or back from a client.

    Accepts our [{"name", "arguments"}] and the clients' [{"function": {...}}].
    """
    out = []
    for c in calls or []:
        if not isinstance(c, dict):
            continue
        f = c.get("function", c)
        out.append((f.get("name") or "", json.dumps(arguments_dict(f.get("arguments")), sort_keys=True)))
    return tuple(out)


class ReplyStream(object):
    """Feeds raw text through; calls emit(kind, text) with kind "thinking" or "content".

    With tools=True, anything from <tool_call> on is held until finish(),
    which returns the parsed calls (or emits the text as content if it was
    not a call after all).
    """

    def __init__(self, emit, tools=False, tool_defs=None, thinking=False):
        # thinking=True: the prompt already opened <think> (DeepSeek-R1 distills, *-Thinking-2507)
        self.emit, self.tools, self.tool_defs = emit, tools, tool_defs
        self.text, self.pos, self.mode = "", 0, ("thinking" if thinking else "start")

    def feed(self, piece):
        self.text += piece
        self._pump(final=False)

    def finish(self):
        calls = []
        if self.mode in ("content", "after_think"):
            rest = self.text[self.pos:]
            if self.tools and CALL_OPEN in rest:
                content, calls = parse_tool_calls(rest, self.tool_defs)
                if calls:
                    if content:
                        self.emit("content", content)
                    self.pos = len(self.text)
                    return calls
        self._pump(final=True)
        return calls

    def _out(self, kind, n):
        if n > 0:
            self.emit(kind, self.text[self.pos:self.pos + n])
            self.pos += n

    def _pump(self, final):
        while True:
            rest = self.text[self.pos:]
            if self.mode == "start":
                stripped = rest.lstrip()
                if stripped.startswith(THINK_OPEN):
                    self.pos += len(rest) - len(stripped) + len(THINK_OPEN)
                    self.mode = "thinking"
                    continue
                if not final and THINK_OPEN.startswith(stripped):
                    return                                  # may still turn into <think>
                self.mode = "content"
                continue
            if self.mode == "thinking":
                i = rest.find(THINK_CLOSE)
                if i >= 0:
                    self._out("thinking", i)
                    self.pos += len(THINK_CLOSE)
                    self.mode = "after_think"
                    continue
                self._out("thinking", len(rest) - (0 if final else _tail_overlap(rest, THINK_CLOSE)))
                return
            if self.mode == "after_think":                   # drop the blank lines after </think>
                stripped = rest.lstrip()
                self.pos += len(rest) - len(stripped)
                if not stripped and not final:
                    return
                self.mode = "content"
                continue
            # content
            if final:
                self._out("content", len(rest))
            elif self.tools:
                i = rest.find(CALL_OPEN)
                self._out("content", i if i >= 0 else len(rest) - _tail_overlap(rest, CALL_OPEN))
            else:
                self._out("content", len(rest))
            return


def opens_thinking(model_name):
    """Models whose chat template opens <think> in the prompt, so the reply starts inside it."""
    return bool(re.search(r"r1[-_]?distill|deepseek[-_]?r1|thinking[-_]?2507", model_name or "", re.I))


def split_reply(text, tools=False, tool_defs=None):
    """The whole reply at once: (thinking, content, calls)."""
    thinking, content = [], []
    opened = THINK_CLOSE in text and THINK_OPEN not in text
    s = ReplyStream(lambda kind, t: (thinking if kind == "thinking" else content).append(t), tools, tool_defs,
                    thinking=opened)
    s.feed(text)
    calls = s.finish()
    return "".join(thinking).strip(), "".join(content).strip(), calls
