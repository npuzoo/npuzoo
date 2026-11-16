# npuzoo 🦓

**Run AI models on your NPU board. One command.**

`npuzoo` is a CLI + model registry for single-board computers with NPUs —
starting with Rockchip RK3588 / RK3576 (Orange Pi 5 series, Radxa Rock 5,
NanoPC-T6, …).

The NPU on your board is not a trap. It's just badly packaged.
npuzoo packages it.

```
$ npuzoo doctor          # check board, kernel, NPU driver, runtime libs — and how to fix them
$ npuzoo pull qwen3-1.7b # download a model converted & verified for YOUR board and YOUR driver version
$ npuzoo run qwen3-1.7b  # run it on the NPU (or CPU, if that's honestly faster)
```

## Why

- New models break: `rkllm-toolkit` lags weeks behind releases, and converted
  models on Hugging Face were made with old incompatible versions.
- Non-vendor kernels lose the NPU: no `/dev/rknpu`, no answers.
- Nobody tells you when the CPU is actually faster than the NPU.

Every package in the npuzoo registry is pinned to **chip × driver × runtime
version**, tested on real hardware, and ships with honest NPU-vs-CPU numbers.

## Status

| Component | Status |
|---|---|
| `npuzoo doctor` (RK3588/RK3576) | v0.1 — this repo |
| registry format + `npuzoo pull` | v0.1 — local/file index works, hosted registry WIP |
| `npuzoo run` (RKLLM backend) | stub — lands with first model batch |
| conversion pipeline (x86) | skeleton in `pipeline/` |
| voice pipeline preset | planned (weeks 7–9) |

## Install (dev)

```
pipx install .          # or: pip install -e .
npuzoo doctor            # on a real board
npuzoo doctor --demo     # anywhere, with simulated board data
```

## Supported boards (initial)

Orange Pi 5 / 5 Plus / 5 Max · Radxa Rock 5B / 5B+ · FriendlyElec NanoPC-T6 ·
other RK3588/RK3588S/RK3576 boards (best-effort).

## Contributing

Adding a model = submitting one YAML file. The pipeline converts, benchmarks
on real boards, and publishes with your name on it. See `docs/CONTRIBUTING.md`
(soon).

## License

Apache-2.0. Model weights keep their original licenses — each package's model
card states it.
