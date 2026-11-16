# {{name}} · {{chip}}

Verified package for the npuzoo registry. **Every number below was measured on
the exact versions listed — change any of them and your results may differ.**

## Quickstart

```
npuzoo pull {{name}}
npuzoo run {{name}}
```

## Pinned versions

| What | Value |
|---|---|
| Source model | {{repo}} @ {{revision}} |
| Target chip | {{chip}} |
| Backend / quant | {{backend}} / {{quant}} |
| Max context | {{context}} |
| rkllm-toolkit (conversion) | {{toolkit}} |
| NPU driver (tested) | {{npu_driver}} |
| Test board | {{board}} |
| Test date | {{date}} |

## Measured performance

| Path | tokens/s |
|---|---|
| NPU | {{npu_tps}} |
| CPU (llama.cpp, same board) | {{cpu_tps}} |

**npuzoo recommends: {{recommend}}** — we publish both numbers and pick the
honest winner. TOPS is marketing; tokens/s on your board is reality.

## License

Inherits the source model's license. Conversion scripts: Apache-2.0.

## Reproduce

Converted and benchmarked by the open npuzoo pipeline:
`pipeline/convert_rkllm.py` → `pipeline/bench_on_board.sh` → `pipeline/publish.py`.
