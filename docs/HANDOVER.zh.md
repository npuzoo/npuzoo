# npuzoo 交接说明（中文）

目的：创始人回国后换任何编码助手（Qwen Coder / DeepSeek / Kimi）都能无缝接手。

## 仓库结构

```
npuzoo/
├── src/npuzoo/           # pip 包，命令行入口 `npuzoo`
│   ├── cli.py           # 子命令分发：doctor / pull / list / run
│   ├── doctor.py        # 环境自检：板型、内核、NPU 驱动、运行库 + 修复建议
│   ├── registry.py      # 索引格式（文件头注释里有 schema）、pull、list
│   └── data/index.demo.json   # 开发用假索引
├── pipeline/            # 在 x86 转换机 + 板子上跑的流水线
│   ├── convert_rkllm.py # HF 模型 → .rkllm，没装 toolkit 时自动 dry-run
│   ├── bench_on_board.sh# 板上基准：NPU vs CPU，各输出 tokens/s，追加 jsonl
│   └── publish.py       # 合并转换记录 + 基准 → index.json + 模型卡
├── templates/MODEL_CARD.md
└── docs/
```

## 现在就能跑的

```
pip install -e .
npuzoo doctor --demo      # 模拟 Orange Pi 5 Plus 的输出
npuzoo doctor --json --demo
npuzoo list               # 读 demo 索引
python pipeline/convert_rkllm.py --model Qwen/Qwen3-1.7B --dry-run
```

## 板子到了之后（按顺序）

1. 官方 Debian/Ubuntu 镜像：`npuzoo doctor`，把输出发 issue 存档。
2. 换 Armbian：再跑一次，确认能准确报出"NPU 设备缺失"并给对修复建议。
3. doctor 的检查规则都在 `doctor.py` 顶部的常量里（最低驱动版本等），按实测改。

## x86 转换机到了之后

1. `pip install rkllm-toolkit`（从 airockchip/rknn-llm releases 装）。
2. `convert_rkllm.py` 去掉 --dry-run 跑真转换；失败的模型把完整日志存进 issue。
3. 转出的 .rkllm 拷到板上，跑 `bench_on_board.sh`，再 `publish.py` 出索引和模型卡。

## 已知空位（故意留的）

- `npuzoo run`：等第一批模型包定了运行时版本再写（rkllm runtime 的 C API 包一层）。
- 下载地址：index.demo.json 里 files 为空；真模型传 HF 后由 publish.py 填。
- 遥测：计划在 pull 时匿名计数（设备数、板型），首次运行要明示并可关。还没写。
- librkllmrt 版本探测的正则（doctor.py `_lib_version`）没在真库上验证过，拿到真库后校准。
- bench_on_board.sh 里的 `rkllm_bench` 是占位命令名，实际要用 rknn-llm 仓库 examples 编出来的 benchmark 程序，名字以实物为准。

## 命名

工具和社区名 npuzoo（栖）。域名 npuzoo.dev 与 npuzoo.com；GitHub、HF、PyPI 均为 npuzoo。
