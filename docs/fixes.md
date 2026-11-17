# Fixes

`npuzoo doctor` links here. Each section is one thing it can tell you, and what
to do about it. Sources for every claim are in [UPSTREAM.md](UPSTREAM.md); the
version tables are in [compatibility.md](compatibility.md).

If none of this gets you moving, open a
[discussion](https://github.com/npuzoo/npuzoo/discussions) with your `doctor`
output. Unanswered reports are how this page grows.

---

## boards

npuzoo targets the chips Rockchip's own RKLLM runtime targets. Verified against
the runtime binaries at every release tag:

| Chip | LLMs on NPU | Notes |
|---|---|---|
| RK3588 / RK3588S | yes | the main target; w8a8 only |
| RK3576 | yes | w8a8 and w4a16 |
| RK3562 | yes | small NPU, w8a8 |
| RV1126B | yes | added in runtime 1.2.0 |
| RK3566 / RK3568 | **no** | RKNN vision/audio works; LLMs run on CPU |

If `doctor` says it cannot recognise your board, it is reading
`/proc/device-tree/model` and `/proc/device-tree/compatible`. On some images
those are missing or generic. That alone is not fatal — check the rest of the
report. Tell us what your board reports and we will add it.

## kernel

The rknpu driver is a **vendor** kernel driver. Mainline, and most community
`edge`/`current` kernels, are built without it. The hardware is present and
completely unreachable; nothing in userspace fixes this.

```
lsmod | grep rknpu          # loaded?
sudo dmesg | grep -i npu    # probed and failed, or never appeared?
```

- Nothing at all → you are on a kernel without the driver. Boot a vendor-kernel
  image (6.1.y on RK3588).
- Present but failing to probe → paste the dmesg lines into a discussion.

Armbian ships both kinds. The `vendor` / `legacy` kernel branch has the NPU;
`edge` / `current` generally does not.

## npu-node

`doctor` looks for any of `/dev/rknpu`, the `rknpu` debugfs directory, or an NPU
devfreq entry. None of them present means the driver is not loaded — see
[kernel](#kernel) above.

Note that `/dev/rknpu` does not exist on every working setup; the driver is
reached through other nodes on some images. That is why `doctor` checks several
and only fails when all are absent.

## driver

The version lives in debugfs and needs root:

```
sudo cat /sys/kernel/debug/rknpu/version
RKNPU driver: v0.9.8
```

**Permission denied is not a missing driver.** Re-run with `sudo npuzoo doctor`.

Thresholds:

- **below 0.9.6** — the runtime prints `Your rknpu driver version is too low` at
  init, and larger models then fail during weight allocation. The allocation
  error is the one people report; the driver warning above it is the cause.
- **0.9.6 and up** — workable.
- **0.9.8** — what current board images ship. Aim here.

Updating:

```
sudo apt install rknpu2-rk3588      # Radxa Debian images
sudo apt install rknpu2-rk356x      # RK356x boards
```

On other images the driver comes with the kernel, so updating means updating the
board image.

## rknnrt

`librknnrt.so` runs the vision and audio encoders. Missing it does not stop a
text LLM, but multimodal packages will not work.

A `.rknn` file built by a newer toolkit than your `librknnrt.so` usually still
runs, with a warning — but accuracy is not guaranteed and some operators fall
back. Keep the pair together:

```
strings /usr/lib/librknnrt.so | grep -i 'rknn sdk'
```

## rkllmrt

`librkllmrt.so` is the LLM runtime. **Its version is the single most important
number on your board**, because a `.rkllm` file only loads on the runtime it was
built for.

```
strings /usr/lib/librkllmrt.so | grep 'RKLLM SDK'
RKLLM SDK (version: 1.3.1 | target: Linux | build: 20cd29809 2026-09-28 ...)
```

Note the line that prints at init — `rkllm-runtime version: %s` — is a format
string inside the binary. Grepping for *that* finds nothing useful; the literal
version is in the SDK banner above.

Mismatches, and what each looks like:

| Message | Meaning |
|---|---|
| `load model file error!` | the pair does not match, no further detail |
| `The rkllm-runtime version is lower than the rkllm-toolkit version` | model is newer; upgrade the runtime |
| `The model version is too old, please use the latest toolkit` | model is older; re-convert it |
| `The model's target_platform does not match the real platform` | built for a different chip |

Full table in [compatibility.md](compatibility.md).

## memory

RK3588 publishes w8a8 only, so budget roughly **1 GB per billion parameters**
for weights, plus the KV cache, plus the system. `doctor` deliberately errs
pessimistic: a too-generous estimate sends you into an allocation failure.

Two different out-of-memory failures, with different fixes:

- `failed to allocate handle ... errno: 12` — the **weights** do not fit. Use a
  smaller model, or a 16 GB board.
- `Failed to allocate buffer for kv cache` — the weights fit, the **context**
  does not. Lower `max_context_len` first; this is cheap and often enough.

## clocks

Rockchip's published tokens/s figures are measured with CPU and NPU clocks
pinned at maximum, using a script in their own repo. A board on its default
governor is slower — that is normal, and it is the gap npuzoo measures rather
than repeats.

If you want to reproduce vendor numbers, pin the clocks. If you want to know
what your product will actually do, do not.

## w4a16 on RK3588

It is not published for RK3588. Rockchip's benchmark tables list w4a16 for
RK3576 and RV1126B only. A 4-bit package built for another chip will not help
you, and will fail with a target-platform error. Do not plan an 8 GB RK3588
product around 4-bit weights.
