"""Reasoning and tool calls in the runtime's raw text."""
import json

from npuzoo.reply import (ReplyStream, split_reply, parse_tool_calls, split_thinking, calls_key,
                          arguments_json, arguments_dict, opens_thinking)

TOOLS = [{"type": "function", "function": {"name": "set_light", "parameters": {
    "type": "object", "properties": {"room": {"type": "string"}, "level": {"type": "integer"},
                                     "on": {"type": "boolean"}}}}}]


def test_json_tool_call():
    text = 'Sure.\n<tool_call>\n{"name": "set_light", "arguments": {"room": "kitchen", "level": 40}}\n</tool_call>'
    content, calls = parse_tool_calls(text)
    assert content == "Sure." and calls == [{"name": "set_light", "arguments": {"room": "kitchen", "level": 40}}]


def test_two_calls_and_string_arguments():
    text = ('<tool_call>{"name": "a", "arguments": "{\\"x\\": 1}"}</tool_call>'
            '<tool_call>{"name": "b", "arguments": {}}</tool_call>')
    content, calls = parse_tool_calls(text)
    assert content == "" and calls == [{"name": "a", "arguments": {"x": 1}}, {"name": "b", "arguments": {}}]


def test_xml_style_call_uses_schema_types():
    text = ("<tool_call>\n<function=set_light>\n<parameter=room>\nliving room\n</parameter>\n"
            "<parameter=level>\n70\n</parameter>\n<parameter=on>\nTrue\n</parameter>\n</function>\n</tool_call>")
    content, calls = parse_tool_calls(text, TOOLS)
    assert calls == [{"name": "set_light", "arguments": {"room": "living room", "level": 70, "on": True}}]


def test_unreadable_call_stays_text():
    for text in ("<tool_call>{not json}</tool_call>", "<tool_call>{\"arguments\": {}}</tool_call>",
                 "<tool_call>{\"name\": \"a\"", "plain answer"):
        assert parse_tool_calls(text) == (text, [])


def test_split_thinking_both_styles():
    assert split_thinking("<think>\nhmm\n</think>\n\nYes.") == ("hmm", "Yes.")
    assert split_thinking("hmm, so\n</think>\nYes.") == ("hmm, so", "Yes.")
    assert split_thinking("Yes.") == ("", "Yes.")


def test_split_reply():
    assert split_reply("<think>a</think>\n\nB") == ("a", "B", [])
    assert split_reply("reasoning</think>B") == ("reasoning", "B", [])
    t, c, calls = split_reply('<think>x</think>\n<tool_call>{"name": "f", "arguments": {}}</tool_call>', tools=True)
    assert (t, c) == ("x", "") and calls[0]["name"] == "f"
    # without tools on offer, a tag is just text
    assert split_reply('<tool_call>{"name": "f"}</tool_call>')[2] == []


def _stream(text, step=1, **kw):
    out = []
    s = ReplyStream(lambda kind, t: out.append((kind, t)), **kw)
    for i in range(0, len(text), step):
        s.feed(text[i:i + step])
    calls = s.finish()
    merged = {}
    for kind, t in out:
        merged[kind] = merged.get(kind, "") + t
    return out, merged, calls


def test_stream_plain_text_passes_straight_through():
    out, merged, calls = _stream("Hello <b>world</b>", step=3)
    assert merged == {"content": "Hello <b>world</b>"} and not calls
    assert len(out) > 1                                  # it really streamed


def test_stream_holds_back_only_a_possible_tag():
    out, merged, calls = _stream('Turning it on. <tool_call>{"name": "set_light", "arguments": {"on": true}}'
                                 '</tool_call>', tools=True, tool_defs=TOOLS)
    assert merged == {"content": "Turning it on. "} and calls == [{"name": "set_light", "arguments": {"on": True}}]
    out, merged, calls = _stream("a < b and <tool", tools=True)
    assert merged == {"content": "a < b and <tool"} and not calls


def test_stream_broken_call_is_flushed_as_text():
    out, merged, calls = _stream("<tool_call>{oops</tool_call>", tools=True)
    assert merged == {"content": "<tool_call>{oops</tool_call>"} and not calls


def test_stream_thinking():
    out, merged, calls = _stream("<think>\nfirst\n</think>\n\nAnswer.", step=2)
    assert merged == {"thinking": "\nfirst\n", "content": "Answer."}
    out, merged, calls = _stream("plan</think>\n\nAnswer.", thinking=True)
    assert merged == {"thinking": "plan", "content": "Answer."}
    out, merged, calls = _stream("<thin", step=1)          # never became a tag
    assert merged == {"content": "<thin"}


def test_calls_key_matches_client_echoes():
    ours = [{"name": "set_light", "arguments": {"room": "kitchen", "level": 40}}]
    openai = [{"id": "c1", "type": "function",
               "function": {"name": "set_light", "arguments": '{"level": 40, "room": "kitchen"}'}}]
    ollama = [{"function": {"name": "set_light", "arguments": {"level": 40, "room": "kitchen"}}}]
    assert calls_key(ours) == calls_key(openai) == calls_key(ollama)
    assert calls_key(None) == ()


def test_argument_shapes_and_thinking_models():
    assert json.loads(arguments_json({"a": 1})) == {"a": 1} and arguments_json('{"a": 1}') == '{"a": 1}'
    assert arguments_dict('{"a": 1}') == {"a": 1} and arguments_dict("nope") == {} and arguments_dict({"b": 2}) == {"b": 2}
    assert opens_thinking("DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588") and opens_thinking("Qwen3-4B-Thinking-2507")
    assert not opens_thinking("Qwen3-1.7B")
