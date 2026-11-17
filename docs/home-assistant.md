# Home Assistant, Open WebUI and other clients

`npuzoo serve` makes a board look like an Ollama server and an
OpenAI-compatible server at the same time, so most clients connect to it as
they would to either.

```
npuzoo serve Qwen3-1.7B-w8a8-rk3588.rkllm --port 11434 --model-name qwen3-1.7b
```

Port 11434 is Ollama's default, so clients that assume Ollama find it
without further changes. `--model-name` is the name clients will see.

> **Status:** the server is tested against a stand-in for Rockchip's
> runtime and its data layouts are checked against Rockchip's headers, but it
> has not yet run on a board. If something here does not work on yours,
> please open an issue with the output of `npuzoo doctor`.

## Home Assistant

Use the built-in **Ollama** integration.

1. Settings → Devices & services → Add integration → Ollama.
2. URL: `http://<board-ip>:11434`.
3. Model: choose the name npuzoo lists. It counts as already downloaded, so
   Home Assistant does not try to pull it.
4. Settings → Voice assistants → your assistant → Conversation agent: the
   Ollama entry you just added.

**Controlling the house.** With "Control Home Assistant" on, Home Assistant
offers its actions (turn on, turn off, set brightness, …) as tools. npuzoo
hands them to the runtime, which writes them into the model's own chat
template (RKLLM 1.2.1 and later), and returns the model's calls to Home
Assistant as tool calls; Home Assistant runs them and sends back the results.

Small models get tool calls wrong more often than large ones. Start with a
Qwen2.5 or Qwen3 model of 1.5B parameters or more, and expose only the
entities you want to control: Home Assistant puts every exposed entity into
the prompt, and on the NPU it is reading that prompt (prefill) that takes
the time, more than writing the answer.

**Thinking.** If your Home Assistant version offers "Think before
responding", it asks Qwen3 models to reason first; npuzoo returns the
reasoning separately from the answer. For voice, leave it off: it is slow.

**Context.** A prompt with tools and a few dozen entities easily passes
2,000 tokens. The default `--context 4096` is a sensible start; it cannot
be larger than the context the model was converted with.

## Open WebUI

Either connection works:

- Admin settings → Connections → Ollama API: `http://<board-ip>:11434`
- Admin settings → Connections → OpenAI API: `http://<board-ip>:11434/v1`,
  any API key

Reasoning from Qwen3 and DeepSeek-R1 distills is returned separately
(`reasoning_content` on the OpenAI side, `thinking` on the Ollama side when
the request asks for it).

## Python

```python
from openai import OpenAI

client = OpenAI(base_url="http://<board-ip>:11434/v1", api_key="none")
r = client.chat.completions.create(model="qwen3-1.7b",
                                   messages=[{"role": "user", "content": "Hello"}])
print(r.choices[0].message.content, r.npuzoo)   # npuzoo adds the measured tok/s
```

Tool calls use the usual `tools=[...]` argument and come back as
`message.tool_calls`.

## What to expect

- **One request at a time.** The NPU runs one generation; other requests
  wait their turn.
- **Conversation memory lives in the runtime.** npuzoo continues the
  runtime's history when a request extends the previous conversation, and
  starts over when it does not (a new conversation, an edited message,
  different tools). The `X-Npuzoo-History` response header says which.
- **Speed is what the runtime measures.** Each OpenAI response carries the
  prefill and generate rates in an `npuzoo` field; `npuzoo bench` measures
  the same thing in a repeatable way.
