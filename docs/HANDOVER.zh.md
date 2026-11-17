# 交接说明（给回国后接手的你，或任何协作者）

更新时间：2026-11-17 凌晨（第二轮，无硬件推进完成后）

## 仓库结构

```
src/npuzoo/
  cli.py            命令入口：doctor / explain / pull / list / run(stub)
  doctor.py         板子体检。每条检查规则的依据都在 docs/UPSTREAM.md 里，有出处
  known_issues.py   真实失败特征库：11 条，全部来自公开渠道别人贴过的日志
  explain.py        npuzoo explain：贴一段报错日志，告诉你真正原因和修法
  registry.py       包索引格式 + pull（本地索引可用，托管注册表未做）
standalone/
  npuzoo-doctor.py  单文件免安装版（生成物，勿手改），curl | python3 即可跑
tools/
  build_standalone.py  从 src/ 生成上面那个文件；有防命名冲突检查
tests/
  test_doctor.py    15 个用例，全部对应真实世界配置
  test_explain.py   日志识别回归测试
  logs/             7 个真实日志夹具（出处见 docs/UPSTREAM.md）
pipeline/           x86 转换 + 板上跑分脚本（骨架）
docs/
  UPSTREAM.md       ★ 最重要的文件：RKLLM 生态的核实事实 + 竞品清单，全部带出处
  outreach/first-post.md  论坛/Reddit 首发帖草稿和回帖守则
```

## 现在就能跑的

```
pip install -e .
python -m pytest tests          # 35 个测试，不需要硬件
npuzoo doctor --demo
npuzoo explain tests/logs/version-mismatch.log
python tools/build_standalone.py   # 改了 src 之后重新生成单文件版
```

## 板子到手那天

1. 官方 Debian 镜像跑 `sudo python3 standalone/npuzoo-doctor.py`，存输出
2. 换 Armbian 再跑一次，存输出
3. 对照输出修 doctor.py 里推错的规则（尤其 _fits 的内存估算和 governor 路径）
4. 每修一条，在 tests/ 里加一个对应夹具

## x86 机器到手那天（云主机即可，32G 内存）

1. 从 airockchip/rknn-llm 的 rkllm-toolkit 目录装 whl（注意 Python 3.10/3.11/3.12，
   3.12 要先 `export BUILD_CUDA_EXT=0`；RWKV 只能 3.12）
2. 跑 pipeline/convert_rkllm.py 做转换兼容矩阵：模型 × toolkit 版本 → 成败 + 报错
3. 矩阵标注"仅转换验证"，发出去——这张表目前没人公开发过

## 重要事实（细节和出处都在 docs/UPSTREAM.md）

- RKLLM 已到 v1.3.1，模型支持更新很快——"原厂滞后"的说法已过时，卖点是封装不是能力
- .rkllm 与运行时版本必须配对，错配只报 `load model file error!`——这是 npuzoo 存在的理由
- w4a16 只在 RK3576/RV1126B 有官方数据，RK3588 只有 w8a8
- 官方 tokens/s 是锁最高频测的，默认 governor 跑不到——"诚实数字"就打这里
- 竞品：rkllama(627★ 活跃)、rkllm-docker、oRKLLM 都做了版本配对的某种形式；
  没人做的是"体检+修复建议"和"实测 NPU vs CPU"。doctor/explain 对他们的用户也有用，
  是切入点不是对手

## 还空着的坑（故意的）

- npuzoo run：等第一批模型包
- 托管注册表 + 下载地址：等 HF 上传第一批包
- 遥测：没做，社区项目第一天就收数据会劝退人
- rkllm_bench 命令名是占位，真实跑分命令等板子到了定
