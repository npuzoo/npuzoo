# What an .rkllm file tells you without a board

Last checked: 2026-11-17, against the first bytes of 44 public `.rkllm` files on
Hugging Face — June 2024 to November 2026, toolkit 1.0.x to 1.3.1, RK3588 and
RK3576 targets, Qwen2/Qwen2.5/Qwen3/Qwen3.5, Llama 3.2, Gemma 2/3n, Phi-3,
ChatGLM3, InternLM2 and MiniCPM-V builds. Only byte ranges at the start of
each file were fetched; no model was downloaded in full.

## What is readable

| Bytes | What we saw | Use |
|---|---|---|
| 0–3 | `da ee b3 36` in 43 of 44 files | identifies a Rockchip-format `.rkllm` |
| 4–7 | `3` in all 43 | container field; did **not** change from toolkit 1.0.x to 1.3.1 |

Everything a developer actually wants to know — toolkit version, target chip,
weight format, context length — is **not** in readable form. Two files of the
same model, one built for RK3576 w4a16 and one for RK3588 w8a8, were
byte-identical for the first 64 KB.

## What we deliberately do not do

Past those fields the header is obfuscated by the toolkit. We do not decode
it. Rockchip ships the SDK under its own proprietary licence, which we have
not finished reviewing, and npuzoo works with chip and board vendors rather
than around them. Decoding a vendor's obfuscated format would be neither.

The runtime already reports what the header holds: it names its own version,
and it refuses a mismatched model with one of four messages
([compatibility.md](compatibility.md#the-pairing-rule-and-the-four-ways-it-breaks)). On a board,
`npuzoo explain` turns that report into a fix. Off the board, `npuzoo inspect`
checks only what is visible.

## What `npuzoo inspect` checks

Most "load model file error!" reports we have read are not version problems
at all. The file is simply not a model:

- **Git LFS pointer.** A ~130-byte text file left by `git clone` without
  `git-lfs`. The pointer states the real size, which inspect prints.
- **Error page.** An HTML page or JSON error saved under the model's name,
  usually from a `blob/` URL instead of `resolve/`, or a gated repo.
- **GGUF.** llama.cpp's format. The NPU runtime only loads `.rkllm`.
- **Third-party `.rkllm`.** One of the 44 samples used the `.rkllm` extension
  for a different format: ASCII `RKLL`, a version, then the architecture name
  and a llama.cpp-style quantization tag. Rockchip's runtime will most likely
  refuse it; inspect says so and names the architecture.
- **Truncated download.** A file with the signature but a few megabytes long,
  or a size or SHA-256 that does not match what the model page lists
  (`--size`, `--sha256`; on Hugging Face the SHA-256 is the LFS `oid`).

Then it checks what the **filename** claims — chip, weight format, group size,
toolkit version — against what the chip can do and what the board runs:

- `w4a16` on RK3588: Rockchip publishes w8a8 only for RK3588. Repositories
  routinely ship an RK3576 w4a16 file next to the RK3588 w8a8 one.
- Chip in the name differs from the board (`--board`, or detected on a board):
  the runtime will refuse it with *"The model's target_platform does not match
  the real platform"*.
- Toolkit in the name newer than the runtime (`--runtime`): refused.
- Toolkit in the name older than the runtime: a **warning**, not a verdict.
  Rockchip does not document which older models newer runtimes still load, and
  we will not guess until we have tested on hardware.

Filename claims are labelled as claims. Nothing about the file's real target
is asserted beyond what the bytes and the name show.
