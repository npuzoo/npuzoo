# Next chips: what supporting them would take

Notes for the second stage (after Rockchip), gathered from public sources in
November 2026. Each section says how models are built and run, what the
licences say as published, how developers get the software, and what npuzoo
would need. Nothing here has been tried on hardware yet.

## AXERA (爱芯元智) — AX650N / AX8850, incl. the AX8850 M.2 card

- **Runtime:** `ax-llm` / `axllm`, AXERA's own LLM runtime, is on GitHub under
  BSD-3-Clause, as is its Python API (`pyaxengine`). It installs with a one-line
  script and has `axllm run` and `axllm serve` (OpenAI-compatible, with a
  `/health` endpoint).
- **Toolchain:** Pulsar2 (`pulsar2 llm_build`). Its documentation states
  "All rights are reserved by Axera or its licensors"; the licence of the
  toolchain itself needs reading before we publish anything built with it.
  LLM build is documented for AX650A/AX650N/AX8850 with SDK ≥ 3.6.2; listed
  verified models include Qwen3, Qwen2.5, DeepSeek-R1-Distill, MiniCPM4,
  InternVL2.5/3, ChatGLM3 and SmolLM2.
- **Models:** AXERA publishes ready-to-run packages on Hugging Face
  (`AXERA-TECH/...`), many with a `SHA256SUMS` file and a validated `axllm`
  binary inside the package. A package is a directory (`*.axmodel` per layer
  plus embeddings and tokenizer), not one file.
- **Reach:** the AX8850 also ships as an M.2 card that third parties document
  for the Raspberry Pi 5, so the same users as our RK3588 audience, and more.
- **What npuzoo needs:** `doctor` checks for the card or SoC and the AXCL / BSP
  version; `find` over `AXERA-TECH` and community packages (directory-shaped
  entries, verified against `SHA256SUMS`); `explain` signatures from `axllm`
  logs. Running is already covered by `axllm`; npuzoo should call it, not
  replace it.

## CIX (此芯) — P1 (CD8180), Radxa Orion O6 / O6N, Orange Pi 6 Plus

- **NPU:** Arm China Zhouyi; the user-mode driver is open source
  (`Arm-China/Compass_NPU_Driver`), so the C API is public.
- **SDK:** "NeuralONE" / NOE (`cixbuild` compiler, `.cix` model files, NOE UMD
  runtime). Radxa redistributes the SDK on its own download server; CIX's
  developer site asks for an account with e-mail and phone number and manual
  approval. The AI model hub in the SDK ships an `EULA.md` and a `LICENSE`,
  which need reading.
- **LLMs:** a public issue on CIX's Linux repository reports MatMul-heavy
  workloads running on one NPU core well below the expected rate, and that
  llama.cpp on the CPU was faster for LLM inference on that setup. That is
  exactly the question npuzoo's NPU-versus-CPU numbers are meant to settle per
  release, with the vendor's right of reply.
- **What npuzoo needs:** `doctor` for the NOE driver and UMD versions; `run`
  through the NOE runtime or through llama.cpp, whichever measures faster.

## Houmo (后摩智能) — M50, LQ50 M.2 card

- **Hardware:** 160 TOPS INT8 at about 10 W, up to 48 GB of memory; M.2 cards
  and accelerator cards as well as the chip.
- **Toolchain:** "后摩大道" (Houmo Dadao), downloaded from Houmo's developer
  community. Its published flow: GPTQ 4-bit quantization, compilation to HMM
  files for one or two chips, and conversion of the result to GGUF so that
  `llama-server` can serve it over an OpenAI-compatible API.
- **What npuzoo needs:** access to the toolchain (an account), a card, and the
  licence text; then `doctor` for the card and driver, and `find` / `get` for
  HMM / GGUF packages.

## Before any of this is published

Read each vendor's licence the way [licensing.md](licensing.md) reads
Rockchip's: can numbers be published, can converted files be redistributed,
may the runtime be bundled. Use only public software and publicly sold
hardware; send any comparison to the vendor 14 days before it is published.
