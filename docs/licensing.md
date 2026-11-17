# What the Rockchip SDK licences allow

Read on 2026-11-17 from the vendor's public repositories. This is our reading
for planning purposes, not legal advice; anything we ship that depends on it
gets a lawyer's review first.

## RKLLM — `airockchip/rknn-llm` (v1.3.1, released 2026-09-29)

The repository has one licence file, at its root. It is a BSD-3-Clause-style
text under Rockchip's copyright, followed by the MIT licence for the parts of
ggml and llama.cpp that Rockchip modified. The toolkit wheels
(`rkllm_toolkit-1.3.1-*.whl`) carry no licence file of their own; their
metadata names Rockchip as author and nothing else.

| Question | Answer from the text |
|---|---|
| Can we redistribute `librkllmrt.so`, e.g. in an image or installer? | Yes, if the copyright notice, conditions and disclaimer go with it in the documentation (clause 2). |
| Can we modify it? | The text permits use "with or without modification". We do not modify vendor binaries. |
| Can we say a package is endorsed or certified by Rockchip? | No — clause 3 forbids using Rockchip's name to endorse or promote derived products without written permission. Factual compatibility statements ("built with rkllm-toolkit 1.3.1 for RK3588") are what we write. |
| Can we publish performance numbers? | Nothing in the text restricts it. Rockchip itself publishes benchmarks and the frequency-locking scripts used to make them (`scripts/fix_freq_*.sh`). |
| Can we redistribute converted `.rkllm` models? | The licence places no condition on the toolkit's output. The original model's licence (Qwen, Llama, Gemma, …) governs the weights, and each package carries it. |
| Reverse engineering? | Not addressed. We do not decode the obfuscated `.rkllm` header anyway; see [rkllm-format.md](rkllm-format.md). |

## RKNN — `airockchip/rknn-toolkit2` ("RKNN SDK License")

Different and more restrictive. It matters to us because multimodal RKLLM
demos use an `.rknn` vision encoder run by `librknnrt.so`, and the rknn-llm
repository itself ships `librknnrt.so` under
`examples/multimodal_model_demo/deploy/3rdparty/`.

- **Grant (1.1):** use, reproduce, modify and create derivative works, and
  redistribute *modifications or derivative works made by you*, solely for the
  design, development and testing of applications compatible with Rockchip
  products. Redistributing the unmodified SDK is not expressly granted.
- **Documentation (1.2):** internal use only. We link to it; we do not mirror it.
- **Restrictions (2.1):** no decompiling or reverse engineering; keep all notices.
- **Termination (9.1):** Rockchip may terminate at any time, with or without cause.
- **Law (10):** PRC law; courts in Fuzhou.
- No clause on publishing performance numbers.

## What we do as a result

1. `librkllmrt.so` may ship inside npuzoo images or installers, with Rockchip's
   notice in the documentation.
2. `librknnrt.so` is never bundled. `npuzoo doctor` tells users where to get it
   from Rockchip; it does not download it for them.
3. Every model package records the original model's licence, and we skip
   models whose licence forbids redistribution.
4. Vision-language packages ship the `.rknn` vision encoder only after a lawyer
   confirms that a converted encoder is a "derivative work made by you" under
   RKNN clause 1.1. Until then, those packages give the conversion command
   instead of the file.
5. No vendor logos, no "certified" or "official" wording, anywhere.
6. Each new chip vendor's licence gets the same reading before we publish
   anything for that chip.
