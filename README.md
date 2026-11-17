# npuzoo 🦓

**Run AI models on your NPU board. One command.**

`npuzoo` is a CLI + model registry for single-board computers with NPUs —
starting with Rockchip RK3588 / RK3576 (Orange Pi 5 series, Radxa Rock 5,
NanoPC-T6, …).

The NPU on your board is not a trap. It's just badly packaged.
npuzoo packages it.

```
$ npuzoo doctor           # board, kernel, NPU driver, runtime libs — and how to fix them
$ npuzoo explain err.log  # paste a failing RKLLM/RKNN log, get the actual cause
$ npuzoo inspect m.rkllm  # before copying: is it really a model, for this chip, for this runtime?
$ npuzoo find qwen3 1.7b  # community .rkllm files on Hugging Face that fit YOUR board and runtime
$ npuzoo pull qwen3-1.7b  # a model converted & verified for YOUR board and YOUR runtime
$ npuzoo run qwen3-1.7b   # run it on the NPU (or CPU, if that's honestly faster)
```

`explain` can date a log that contains no version line at all. The runtime's
message catalogue grew from 17 strings in v1.1.0 to 210 in v1.3.1, so the
messages present in your log put a floor under the runtime that produced it:

```
$ printf 'E rkllm: Failed to allocate buffer for kv cache\n' | npuzoo explain
Runtime version is not in this log, but it is at least 1.2.2:
   "Failed to allocate buffer for kv cache..." was introduced in 1.2.2
```

## Check your board right now — nothing to install

```
curl -fsSL https://raw.githubusercontent.com/npuzoo/npuzoo/main/standalone/npuzoo-doctor.py | python3
```

One file, no dependencies, Python 3.6+. It reads `/proc`, `/sys` and your
runtime `.so` files and prints what is wrong and how to fix it. It sends
nothing anywhere.

If something is failing, pipe the log through it:

```
./your-demo 2>&1 | python3 npuzoo-doctor.py --explain
```

Before copying a downloaded model to the board, check it can load at all —
Git LFS pointers, saved error pages, GGUF files and wrong-chip builds are the
usual suspects:

```
python3 npuzoo-doctor.py --inspect qwen3-4b-rk3588-w8a8.rkllm --board rk3588 --runtime 1.3.1
```

## Find a model someone already converted

Hundreds of people publish `.rkllm` files on Hugging Face. Which of them load on
your board is the part nobody tells you before a 2 GB download.

```
$ npuzoo find qwen3 1.7b --board rk3588 --runtime 1.2.1     # (example repos)
  ✓ someone/Qwen3-1.7B-rk3588
      Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm
      2.3 GB · toolkit 1.2.1 · updated 2026-10-03 · 912 downloads/30d

  ? other/Qwen3-1.7B-NPU
      model.rkllm
      2.1 GB · toolkit ? · updated 2026-09-12 · 4000 downloads/30d

  3 file(s) hidden because their names say they will not load here (--all shows them).

  ✓ name fits   ? name does not say enough   ✗ will not load
  Get one:  npuzoo get someone/Qwen3-1.7B-rk3588 Qwen3-1.7B-rk3588-w8a8-1.2.1.rkllm
```

On a board, `--board` and `--runtime` are detected for you.

`get` downloads from the author's repo (resumable; `HF_ENDPOINT=https://hf-mirror.com`
works), checks size and SHA-256 against what Hugging Face published, then runs
`inspect`. The index of every public `.rkllm` file is rebuilt weekly — see
[index/README.md](index/README.md). These files are their authors' work and are
not tested by us; the verdicts come from what the file names claim.

## Why

Rockchip ships plenty of capability — RKLLM is at v1.3.1 and supports Qwen3.5,
Gemma4, InternVL3.5, Qwen3-VL and more. What's missing is packaging, and that
costs people days:

- **A `.rkllm` file only loads on the runtime it was built for.** Mismatch it
  and you get `load model file error!` and nothing else to go on.
- **Advice doesn't transfer between boards.** w4a16 is published for RK3576 and
  RV1126B, not RK3588. "Just use the 4-bit one" is wrong half the time.
- **An old kernel driver fails late, not loudly.** Below 0.9.6 you get a warning
  and then an allocation failure that looks like an out-of-memory bug. The
  version lives in debugfs, behind root.
- **Non-vendor kernels ship without the NPU driver at all** — the classic
  "no `/dev/rknpu`" on mainline and edge images.
- **Distribution is a cloud-drive link with a fetch code**, then `adb push`,
  then `LD_LIBRARY_PATH` by hand, then a binary with fourteen positional
  arguments.
- **Published tokens/s are measured with clocks pinned at maximum.** Your board
  on its default governor is slower, and nobody tells you that either.

Every package in the npuzoo registry is pinned to **chip × driver × runtime ×
toolkit**, tested on real hardware, and ships with honest NPU-vs-CPU numbers.
What `doctor` and `explain` assert is sourced:
[docs/UPSTREAM.md](docs/UPSTREAM.md) for the ecosystem,
[docs/compatibility.md](docs/compatibility.md) for the version tables (read out
of the official runtime binaries at every release tag), and
[docs/fixes.md](docs/fixes.md) for what to actually do. No claim in the code
without a source.

## Status

| Component | Status |
|---|---|
| `npuzoo doctor` (RK3588/RK3576/RK3562/RV1126B) | v0.1 — works now, calibrating against real boards |
| `npuzoo explain` (log → diagnosis) | v0.1 — 23 failure signatures; 7 real logs as regression fixtures |
| `npuzoo inspect` (model file → can it load?) | v0.1 — LFS pointers, error pages, GGUF, third-party `.rkllm`, wrong chip or format, version order, checksum. See [docs/rkllm-format.md](docs/rkllm-format.md) |
| `npuzoo find` / `npuzoo get` (community files) | v0.1 — weekly index of every public `.rkllm` on Hugging Face; fit judged from names, downloads verified |
| runtime dating from a version-less log | v0.1 — 89 fingerprints across 12 releases |
| standalone one-file doctor | v0.1 — works now; includes `--explain` and `--inspect` |
| registry format + `npuzoo pull` | v0.1 — local/file index works, hosted registry WIP |
| `npuzoo run` (RKLLM backend) | stub — lands with the first model batch |
| conversion pipeline (x86) | skeleton in `pipeline/` |
| voice pipeline preset | planned |

Version and platform tables are read out of the official runtime binaries, so
they are exact. The driver thresholds and the memory sizing still come from
public reports rather than boards we own — that is what we most need help with;
see Community.

## Install (dev)

```
pipx install .           # or: pip install -e .
npuzoo doctor            # on a real board
npuzoo doctor --demo     # anywhere, with simulated board data
python -m pytest tests   # 55 tests, no hardware needed
```

## Supported boards (initial)

Orange Pi 5 / 5 Plus / 5 Max · Radxa Rock 5B / 5B+ · FriendlyElec NanoPC-T6 ·
other RK3588/RK3588S/RK3576 boards (best-effort). RK3562 and RV1126B are
recognised; untested.

## Contributing

Adding a model = submitting one YAML file. The pipeline converts, benchmarks
on real boards, and publishes with your name on it. See `docs/CONTRIBUTING.md`
(soon).

Adding a failure signature is smaller still: drop the log in `tests/logs/`,
add an entry to `src/npuzoo/known_issues.py`, add one assertion. That is the
whole contract.

## Community

Run the one-liner above on your board and paste the output — **especially when
something is broken**. Every failure mode we see makes the tool better for the
next person, and right now that is the single most useful thing anyone can
contribute.

- [Discussions](https://github.com/npuzoo/npuzoo/discussions) — questions, board reports, ideas
- [Discord](https://discord.gg/vStcJ23Tb) — `#help` for board problems, `#benchmarks` for numbers
- [Hugging Face](https://huggingface.co/npuzoo) — the model packages
- [@npuzoo](https://x.com/npuzoo) — release notes

## License

Apache-2.0. Model weights keep their original licenses — each package's model
card states it.
