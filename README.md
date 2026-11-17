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
$ npuzoo pull qwen3-1.7b  # a model converted & verified for YOUR board and YOUR runtime
$ npuzoo run qwen3-1.7b   # run it on the NPU (or CPU, if that's honestly faster)
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
What `doctor` and `explain` assert is sourced in
[docs/UPSTREAM.md](docs/UPSTREAM.md) — no claim in the code without a source.

## Status

| Component | Status |
|---|---|
| `npuzoo doctor` (RK3588/RK3576/RK3562/RV1126B) | v0.1 — works now, calibrating against real boards |
| `npuzoo explain` (log → diagnosis) | v0.1 — 11 failure signatures, each with a test fixture |
| standalone one-file doctor | v0.1 — works now |
| registry format + `npuzoo pull` | v0.1 — local/file index works, hosted registry WIP |
| `npuzoo run` (RKLLM backend) | stub — lands with the first model batch |
| conversion pipeline (x86) | skeleton in `pipeline/` |
| voice pipeline preset | planned |

`doctor`'s thresholds are currently derived from public reports, not from
boards we own. That is exactly what we need help with — see Community.

## Install (dev)

```
pipx install .           # or: pip install -e .
npuzoo doctor            # on a real board
npuzoo doctor --demo     # anywhere, with simulated board data
python -m pytest tests   # 35 tests, no hardware needed
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
