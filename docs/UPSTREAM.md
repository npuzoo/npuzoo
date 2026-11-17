# What we actually know about the RKLLM stack

Everything `npuzoo doctor` and `npuzoo explain` assert comes from here. If a
claim is not in this file with a source, it does not belong in the code.

Last checked: 2026-11-17.

## Releases

RKLLM is at **v1.3.1**. It moves fast — eight feature releases since v1.0.0,
each adding model families. Rockchip's own CHANGELOG is the authority:
https://github.com/airockchip/rknn-llm/blob/main/CHANGELOG.md

Dates matter less than the pairing rule below, but a rough shape:

| Release | What landed that changes compatibility |
|---|---|
| v1.0.0 | RK3588/RK3576, w8a8 and w4a16, Llama/Qwen/Qwen2/Phi-2 |
| v1.1.0 | group-wise quantization (w4a16 g32/64/128, w8a8 g128/256/512), GGUF in (q4_0, fp16) |
| v1.2.0 | max context to 16K, GRQ Int4, GPTQ-Int8, RK3562, Python 3.9–3.12 |
| v1.2.1 | RWKV7, Qwen3, MiniCPM4, RV1126B, function calling |
| v1.2.2 | Gemma3n, InternVL3, multi-instance inference |
| v1.2.3 | InternVL3.5, DeepSeekOCR, Qwen3-VL |
| v1.3.0 | Qwen3.5, Gemma4, SmolLM3, multiple EOS token IDs |
| v1.3.1 | LFM2.5-VL, Spark-X2.5, audio input interface |

Supported platforms as of v1.3.1: **RK3588, RK3576, RK3562, RV1126B**.

## The pairing rule

A `.rkllm` file is built by one rkllm-toolkit version and loads only on a
matching runtime. There is no graceful degradation: it fails at load.

The runtime prints both versions at init, which is how you check:

```
I rkllm: rkllm-runtime version: 1.2.2, rknpu driver version: 0.9.8, platform: RK3588
I rkllm: rkllm-toolkit version: 1.2.1b1, max_context_limit: 16384, ... model_dtype: W8A8_G512
E RKNN: load model file error!
```

That third line is the whole error you get. This is the problem npuzoo exists
to remove, and it is why every package records chip × driver × runtime ×
toolkit.

Seen in the wild: https://github.com/NotPunchnox/rkllama/issues/86

## Weight formats are not uniform across chips

Rockchip's own benchmark tables publish:

| Chip | Published dtypes |
|---|---|
| RK3588 | w8a8 only |
| RK3576 | w8a8, w4a16, w4a16_g128 |
| RK3562 | w8a8 only |
| RV1126B | w8a8, w4a16, w4a16_g128 |

Source: https://github.com/airockchip/rknn-llm/blob/main/benchmark.md

So "just use the 4-bit version" is not advice you can give an RK3588 owner.
`doctor` says this out loud because the assumption is common and costly.

## Memory

From the same benchmark table (RK3588, w8a8, seqlen 128 — weights only, no
real KV cache):

| Size | Memory | Tokens/s |
|---|---|---|
| 0.5B | ~0.5–0.7 GB | 41–45 |
| 1.1B | ~1.1 GB | 24 |
| 1.5B | ~1.7 GB | 17 |
| 2B | ~2.1–2.8 GB | 10–14 |
| 3B | ~2.8–3.1 GB | 10–32 |
| 4B | ~4.4–4.6 GB | 6 |
| 6B | ~6.0 GB | 5 |

Real sessions land higher. Published community figures: a 3B vision VLM at
about 9.7 GB total, a 7B audio VLM at about 11.6 GB. `doctor`'s sizing uses
the pessimistic end on purpose — a too-generous number sends someone into an
allocation failure.

Important caveat on those tokens/s: Rockchip measures them with CPU and NPU
clocks pinned at maximum via a script in their `scripts/` directory. A board
on its default governor is slower. This is exactly the gap npuzoo measures
and reports instead of repeating.

## Driver versions

The version lives in debugfs and needs root:

```
$ sudo cat /sys/kernel/debug/rknpu/version
RKNPU driver: v0.9.8
```

- Below **0.9.6**: the runtime prints a "driver version is too low" warning and
  larger models fail during weight allocation.
- Runtime 1.2.x asks for **0.9.7**.
- Current board images ship **0.9.8**. Some RK356x images still ship 0.8.8.
- On Radxa Debian images the driver is a package:
  `sudo apt install rknpu2-rk3588` (or `rknpu2-rk356x`).

Sources: https://github.com/airockchip/rknn-llm/issues/290 ·
https://docs.radxa.com/en/som/nx/nx5/ai-dev/rknn-install

## Known failure signatures

Encoded in `src/npuzoo/known_issues.py`, with a fixture per signature in
`tests/logs/`. Each one came from a log someone posted publicly:

| Signature | Means |
|---|---|
| `Your rknpu driver version is too low` | kernel driver older than the runtime wants |
| `failed to allocate handle ... errno: 12` | model does not fit in RAM |
| `can not create weight memory for domain` | same, further along |
| `load model file error!` | toolkit/runtime mismatch |
| `Not support XxxForCausalLM!` | architecture not in this toolkit version |
| `Not found the weight of model.layers.0...` | toolkit too old for this weight layout |
| `RKNN Model version: X not match with rknn runtime version: Y` | librknnrt older than the .rknn |
| `libomp.so: cannot open shared object file` | OpenMP runtime missing next to librkllmrt.so |
| `matmul(w8a8) run failed` | usually downstream of one of the above |
| `No module named 'pkg_resources'` (at `RKLLM()`) | setuptools too new for rkllm-toolkit; pin `setuptools<80` |
| `module 'pyarrow' has no attribute 'PyExtensionType'` | pyarrow too new for toolkit 1.1.x's datasets 2.14.6; pin `pyarrow<15` |

The last two come from npuzoo's own conversion matrix: fresh installs of
rkllm-toolkit 1.2.3 and 1.1.4 on GitHub's runners in November 2026. The
workflow logs are public (`.github/workflows/conversion-matrix.yml`).

## Who else is in this space

Worth knowing before claiming novelty:

| Project | Stars | Last push | What it does |
|---|---|---|---|
| airockchip/rknn-llm | 1771 | 2026-09 | upstream; 283 open issues |
| NotPunchnox/rkllama | 627 | 2026-10 | Ollama-style server for RKLLM; 74 open issues |
| Pelochus/ezrknpu | 255 | 2025-08 | easy install — **inactive 15 months** |
| marty1885/llama.cpp | 122 | 2026-10 | llama.cpp RK3588 NPU backend |
| c0zaut/RKLLM-Gradio | 52 | 2025-02 | Gradio UI — inactive |
| Hanzo-Huang/rkllm-docker | 23 | 2026-10 | pre-converted models as Docker images, toolkit version labelled |
| oRKLLM/oRKLLM | 5 | 2026-10 | auto-matches librkllmrt.so to a model's version |

Read honestly: version-pinning is not a unique idea — rkllm-docker and oRKLLM
both do a form of it. What nobody is doing is **diagnosing a broken board** and
**publishing measured NPU-vs-CPU numbers**. That is where npuzoo should be
sharp, and `doctor` / `explain` are useful to users of every project above,
which makes them a way in rather than a competitor.

The 283 open upstream issues and 74 on rkllama are the demand signal: people
are stuck, repeatedly, on exactly these things.

## Distribution, as it stands today

Pre-converted models are handed out through a Lenovo Box cloud-drive link with
a fetch code, and the SDK through a Filez link with another. Running the demo
means `adb push`, setting `LD_LIBRARY_PATH` by hand, and a binary with
fourteen positional arguments whose image-token values you are told to find by
reading the model's Python source.

That is the gap. Not capability — Rockchip ships plenty. Packaging.
