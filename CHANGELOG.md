# Changelog

## 0.2.0 — 2026-11-17

Everything here works without a board except where it says otherwise.

- `npuzoo inspect FILE` — checks a downloaded `.rkllm` before it is copied to the
  board: Git LFS pointers, saved error pages, GGUF, a third-party format that
  reuses the extension, wrong chip or weight format, toolkit newer than the
  runtime, size and SHA-256.
- `npuzoo find` / `npuzoo get` — a weekly index of every public `.rkllm` on
  Hugging Face (and ModelScope), judged against your board and runtime from
  what the file names claim; `get` downloads from the author's repo, resumes,
  verifies, and inspects.
- `npuzoo support NAME` — which RKLLM release added a model family or chip,
  from Rockchip's changelog. `inspect`, `find` and `explain` use the same table.
- `npuzoo doctor --pc` — the x86 machine that converts models: toolkit,
  Python, dependency pins, `pkg_resources`, pyarrow, memory.
- `npuzoo run`, `npuzoo serve`, `npuzoo bench` — chat, a server that speaks
  both the OpenAI and the Ollama API (so Home Assistant's Ollama integration
  and Open WebUI connect as they would to Ollama), and a fixed benchmark, through a ctypes binding to librkllmrt for
  runtimes 1.2.1–1.3.1. Struct layouts are checked against Rockchip's headers
  for aarch64 in CI. **Not yet run on a board.**
- `explain` — 25 failure signatures, including two toolkit install failures
  found by the conversion matrix.
- Conversion matrix — rkllm-toolkit releases × models × chip formats,
  converted on GitHub's CPU runners: `docs/conversion-matrix.md`.
- The standalone script gained `--inspect` and `--pc`.
- Docs: `licensing.md` (what Rockchip's licences allow), `next-chips.md`
  (AXERA, CIX, Houmo), a Chinese README, issue forms for board reports,
  failing logs and benchmark results.

## 0.1.0 — 2026-11-14

- `npuzoo doctor`, `npuzoo explain` (with runtime dating from version-less
  logs), the standalone one-file doctor, the registry format and `pull`.
