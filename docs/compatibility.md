# RKLLM compatibility tables

This page exists because the question "which driver version works with which
runtime?" has been open in the rkllama tracker since December 2025 with no
answer, and users have been reverse-engineering it from git tags by hand.

Everything below is read out of the official `librkllmrt.so` at each release
tag, not from documentation. Reproduce it with
`python tools/build_fingerprints.py`, or by hand:

```
strings -a librkllmrt.so | grep 'RKLLM SDK'
```

Last rebuilt: 2026-11-17, against release-v1.1.0 … release-v1.3.1.

---

## Releases, with real build dates

The SDK banner inside each binary carries the build timestamp. Useful because
release tag dates and actual build dates drift, and because it shows the real
cadence — roughly one release a quarter, not the weekly churn people assume.

| Runtime | Built | Log messages | Notes |
|---|---|---|---|
| 1.1.0 | 2024-10-11 | 17 | |
| 1.1.1 | 2024-10-18 | 16 | |
| 1.1.2 | 2024-11-04 | 16 | |
| 1.1.3 | 2024-12-06 | 16 | |
| 1.1.4 | 2024-12-11 | 16 | |
| 1.2.0 | 2025-04-08 | 105 | big diagnostics jump; RV1126B added |
| 1.2.1b1 | 2025-05-02 | 114 | **beta — older than 1.2.1, despite the name** |
| 1.2.1 | 2025-06-25 | 151 | |
| 1.2.2 | 2025-09-20 | 171 | |
| 1.2.3 | 2025-11-22 | 176 | |
| 1.3.0 | 2026-06-16 | 202 | |
| 1.3.1 | 2026-09-28 | 210 | current |

The jump from 16 to 105 messages at 1.2.0 is why `npuzoo explain` can date a
log: before 1.2.0 the runtime said almost nothing.

Watch the beta: **1.2.1b1 is not 1.2.1.** It was built seven weeks earlier. A
model converted by toolkit 1.2.1 can fail on a 1.2.1b1 runtime.

## Platform support, per release

Read from the platform strings compiled into each runtime:

| Runtime | RK3588 | RK3576 | RK3562 | RV1126B |
|---|---|---|---|---|
| 1.0.1 – 1.1.4 | yes | yes | yes | no |
| 1.2.0 – 1.3.1 | yes | yes | yes | yes |

RK3566 and RK3568 appear in no release. They are RKNN targets, not RKLLM ones.

## Weight formats, per chip

From Rockchip's published benchmark tables:

| Chip | Published dtypes |
|---|---|
| RK3588 / RK3588S | w8a8 |
| RK3576 | w8a8, w4a16, w4a16_g128 |
| RK3562 | w8a8 |
| RV1126B | w8a8, w4a16, w4a16_g128 |

Group-wise quantization (`_g128`, `_g256`, `_g512`) arrived in toolkit 1.1.0.
A `_g*` package will not load on a runtime older than that.

## Kernel driver

The runtime checks the driver at init and warns below its own minimum. The
minimum is a compiled-in constant rather than a string, so it cannot be read
out of the binary the way versions can — these values come from reported logs:

| Driver | Behaviour |
|---|---|
| 0.8.x | `Your rknpu driver version is too low`; larger models fail to allocate |
| 0.9.6 | practical floor; works for most packages |
| 0.9.7 | what runtime 1.2.x asks for |
| 0.9.8 | what current board images ship |

Driver and runtime version together, as it appears at init:

```
I rkllm: rkllm-runtime version: 1.2.1, rknpu driver version: 0.9.8, platform: RK3588
```

If your log has no such line, `npuzoo explain` can still date the runtime from
the other messages in it.

## The pairing rule, and the four ways it breaks

A `.rkllm` is built by one toolkit version and loads only on a matching runtime.
There is no graceful degradation. The four distinct failures:

| What you see | What it means | What to do |
|---|---|---|
| `load model file error!` | pair does not match; no further detail given | match the versions |
| `The rkllm-runtime version is lower than the rkllm-toolkit version. Please update rkllm-runtime to X` | model is newer than the runtime | install runtime X |
| `The model version is too old, please use the latest toolkit to reconvert the model` | model predates this runtime | re-convert |
| `The model's target_platform does not match the real platform` | built for a different chip | get the right package |

The first one is the common case and the least informative, which is why
version pinning has to happen before download rather than at load.

## Contributing to this page

Numbers here that come from reported logs rather than binaries are marked as
such. If you have a driver/runtime pair that contradicts the table — especially
a working setup below 0.9.6, or a failure at 0.9.8 — that is worth a
[discussion](https://github.com/npuzoo/npuzoo/discussions). Corrections to this
page are the most valuable contribution right now.

## Model families by release

From Rockchip's changelog ([CHANGELOG.md at 1.3.1](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/CHANGELOG.md)) and the supported list in its README.
A family needs a toolkit *and* a board runtime of that release or newer. `npuzoo support <name>`
prints the same table; `inspect`, `find` and `explain` use it. Generated from `src/npuzoo/models.py`.

| Model family | First RKLLM release |
|---|---|
| Qwen3.5 | 1.3.0 |
| Qwen3-VL | 1.2.3 |
| Qwen2.5-VL | 1.2.0 |
| Qwen2-VL | listed in 1.3.1; first release not stated |
| Qwen3 | 1.2.1 |
| Qwen2 / Qwen2.5 | 1.0.0 |
| Qwen | 1.0.0 |
| Gemma 4 | 1.3.0 |
| Gemma 3n | 1.2.2 |
| Gemma 3 | 1.2.0 |
| Gemma 2 | 1.1.0 |
| Gemma | 1.0.1 |
| SmolLM3 | 1.3.0 |
| SmolVLM | listed in 1.3.1; first release not stated |
| InternVL3.5 | 1.2.3 |
| InternVL3 | 1.2.2 |
| InternVL2 | 1.2.0 |
| InternLM2 | 1.0.1 |
| MiniCPM-V | listed in 1.3.1; first release not stated |
| MiniCPM4 | 1.2.1 |
| MiniCPM3 | 1.1.0 |
| MiniCPM | 1.0.1 |
| Phi-3 | 1.0.1 |
| Phi-2 | 1.0.0 |
| ChatGLM3 | 1.0.1 |
| TeleChat2 | listed in 1.3.1; first release not stated |
| RWKV7 | 1.2.1 |
| Janus | 1.2.0 |
| DeepSeek-OCR | 1.2.3 |
| LFM2.5-VL | 1.3.1 |
| Spark-X2.5 | 1.3.1 |
| Llama 3 | 1.1.0 |
| Llama / TinyLlama | 1.0.0 |

| Chip | First RKLLM release |
|---|---|
| RK3588 | 1.0.0 |
| RK3588S | 1.0.0 |
| RK3576 | 1.0.0 |
| RK3562 | 1.2.0 |
| RV1126B | 1.2.1 |

| Feature | First RKLLM release |
|---|---|
| group-wise quantization (w4a16_g32/64/128, w8a8_g128/256/512) | 1.1.0 |
| GGUF conversion (q4_0, fp16) | 1.1.0 |
| GRQ int4 quantization | 1.2.0 |
| 16K context | 1.2.0 |
| chat_template configuration | 1.2.0 |
| function calling | 1.2.1 |
| multiple EOS tokens | 1.3.0 |
