# npuzoo 🦓

**一条命令，让 AI 模型在你的 NPU 开发板上跑起来。**

[English](README.md) · 中文

`npuzoo` 是面向 NPU 开发板的命令行工具和模型库，先支持瑞芯微 RK3588 / RK3576
（香橙派 5 系列、Radxa ROCK 5、友善 NanoPC-T6 等）。

板子上的 NPU 并不难用，难的是版本对不上、模型找不到、报错看不懂。npuzoo 把这些问题一条命令解决掉。

```
$ npuzoo doctor           # 体检：板子、内核、NPU 驱动、运行时库，有问题直接给修法
$ npuzoo explain err.log  # 贴一段 RKLLM/RKNN 报错日志，告诉你真正的原因
$ npuzoo inspect m.rkllm  # 拷到板子之前：这真的是模型吗？芯片对吗？运行时版本对吗？
$ npuzoo find qwen3 1.7b  # 搜别人转好的 .rkllm 模型（Hugging Face 和魔搭），只显示你这块板子、这个运行时能用的
$ npuzoo support qwen3    # 这个模型从 RKLLM 哪个版本开始支持（工具和运行时都要这个版本以上）
$ npuzoo pull qwen3-1.7b  # 下载为你的板子、你的运行时转换并验证过的模型包（制作中）
$ npuzoo run m.rkllm      # 在 NPU 上对话，结束后显示运行时自己统计的预填充、生成速度
$ npuzoo serve m.rkllm    # 提供 OpenAI 和 Ollama 兼容接口（:8080），Home Assistant、Open WebUI 等可直接接入
$ npuzoo bench m.rkllm    # 每块板子都跑同样两组测试；分享的结果汇总在 docs/benchmarks.md

# 在负责转换模型的 x86 电脑上：
$ npuzoo doctor --pc                                  # 检查转换工具、Python、依赖版本、内存
$ npuzoo convert Qwen/Qwen3-1.7B --chip rk3588        # 检查、校准、转换，并按规范命名输出文件
```

`run` 和 `serve` 支持 RKLLM 运行时 1.2.1–1.3.1，按瑞芯微官方头文件编写，结构体布局在 CI 里逐项核对过；**还没有在真板子上跑过**，欢迎反馈。`serve` 同时兼容 OpenAI 和 Ollama 接口，支持工具调用（Home Assistant 控制家居要用到）和思考内容分离，接入方法见 [docs/home-assistant.zh.md](docs/home-assistant.zh.md)。

## 不用安装，现在就体检

```
curl -fsSL https://raw.githubusercontent.com/npuzoo/npuzoo/main/standalone/npuzoo-doctor.py | python3
```

一个文件，没有依赖。只读 `/proc`、`/sys` 和运行时 `.so` 文件，不往任何地方发数据。
GitHub 访问慢的话，先把这个文件下载到板子上再运行，效果一样。

模型跑不起来，把日志喂给它：

```
./your-demo 2>&1 | python3 npuzoo-doctor.py --explain
```

下载来的模型拷上板子之前先查一遍。常见的坑是：下到的其实是 Git LFS 指针或者报错网页、拿了 GGUF 当 NPU 模型、芯片或量化格式不对：

```
python3 npuzoo-doctor.py --inspect qwen3-4b-rk3588-w8a8.rkllm --board rk3588 --runtime 1.3.1
```

## 最常见的几个坑

- **`.rkllm` 模型只能在对应版本的运行时上加载。** 版本不对时，只报一句 `load model file error!`，别的什么都不说。
  转换工具版本比板子上的运行时新，一定加载失败。
- **RK3588 没有官方的 w4a16。** 瑞芯微只给 RK3576 和 RV1126B 发布了 w4a16，「用 4 位量化省内存」在 RK3588 上行不通。
- **老驱动不会马上报错。** NPU 驱动低于 0.9.6 时，先是一句警告，然后是看起来像内存不够的分配失败。驱动版本在 debugfs 里，要 root 才能看。
- **社区内核常常没有 NPU 驱动**，所以根本没有 `/dev/rknpu`。
- **新模型需要新版本。** 例如 Qwen3 从 RKLLM 1.2.1 才开始支持，Qwen3.5 和 Gemma 4 从 1.3.0 开始。用 `npuzoo support <模型>` 查。
- **转换电脑上也有坑。** 现在直接装 rkllm-toolkit 1.2.3 会报 `No module named 'pkg_resources'`，装 1.1.4 会报 `pyarrow` 没有 `PyExtensionType`。
  `npuzoo doctor --pc` 能提前查出来，`npuzoo explain` 会给出修法。

## 找别人已经转好的模型

Hugging Face 和魔搭（ModelScope）上已经有几百个仓库发布了 `.rkllm` 文件，但哪些能在你的板子上加载，下载之前没人告诉你。

```
$ npuzoo find qwen3 1.7b --board rk3588 --runtime 1.2.1
```

- ✓ 文件名和你的板子、运行时对得上；? 文件名信息不够，判断不了；✗ 一定加载不了（默认隐藏）。
- 在板子上运行时，芯片和运行时版本会自动检测。
- `npuzoo get` 从原作者的仓库下载（支持断点续传），核对大小和 SHA-256，再自动检查一遍文件。
- 国内访问 Hugging Face 慢的话：`HF_ENDPOINT=https://hf-mirror.com npuzoo get ...`，或者只看魔搭上的：`npuzoo find qwen3 --source modelscope`
- 默认从 Hugging Face 下载；想默认用魔搭，设置 `NPUZOO_SOURCE=modelscope`。
- 这些文件是作者本人的作品，我们没有测试过；判断只依据文件名。清单每周自动更新，见 [index/README.md](index/README.md)。

## 转换结果表

我们在 GitHub 的免费 x86 机器上用不同版本的 rkllm-toolkit 转换常见的小模型，记录每次转换成功还是失败、在哪一步失败、耗时、内存，见
[docs/conversion-matrix.md](docs/conversion-matrix.md)。只验证转换，不代表在板子上的速度和效果。

## 依据

工具里每一条判断都有出处：生态事实见 [docs/UPSTREAM.md](docs/UPSTREAM.md)；版本对应关系从官方运行时二进制里逐版本读出，见
[docs/compatibility.md](docs/compatibility.md)；修法见 [docs/fixes.md](docs/fixes.md)；瑞芯微 SDK 许可条款的解读见
[docs/licensing.md](docs/licensing.md)。

## 参与

最有用的贡献：**在你的板子上跑一遍上面的体检命令，把输出发上来，尤其是出问题的时候。**

- 板子体检结果、跑不起来的日志：[提一个 issue](https://github.com/npuzoo/npuzoo/issues/new/choose)（有现成的表单）
- 问题、想法：[Discussions](https://github.com/npuzoo/npuzoo/discussions)
- 新的故障特征：把日志放进 `tests/logs/`，在 `src/npuzoo/known_issues.py` 里加一条，再加一条测试断言即可。

## 开发

```
pip install -e .
npuzoo doctor --demo     # 没有板子也能看效果
python -m pytest tests   # 全部测试都不需要硬件
```

## 许可

Apache-2.0。模型权重沿用原模型的许可，每个模型包的说明里会写明。
