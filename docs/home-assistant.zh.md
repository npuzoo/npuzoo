# 接入 Home Assistant、Open WebUI 等客户端

`npuzoo serve` 让开发板同时像一台 Ollama 服务器和一台 OpenAI 兼容服务器，大多数客户端按接 Ollama 或 OpenAI 的方式接上就行。

```
npuzoo serve Qwen3-1.7B-w8a8-rk3588.rkllm --port 11434 --model-name qwen3-1.7b
```

11434 是 Ollama 的默认端口，默认连 Ollama 的客户端不用再改设置。`--model-name` 是客户端里看到的模型名。

> **现状：**服务端用瑞芯微运行时的替身做了测试，数据结构按官方头文件逐项核对过，但还没有在真板子上跑过。如果在你的板子上不工作，请附上 `npuzoo doctor` 的输出提 issue。

## Home Assistant

用 Home Assistant 自带的 **Ollama** 集成。

1. 设置 → 设备与服务 → 添加集成 → Ollama。
2. 地址填 `http://板子IP:11434`。
3. 模型选 npuzoo 列出的那个名字。它会被当作已下载，Home Assistant 不会去拉取。
4. 设置 → 语音助手 → 你的助手 → 对话代理：选刚加的 Ollama。

**控制家里的设备。**打开「控制 Home Assistant」后，Home Assistant 会把开灯、关灯、调亮度等操作作为工具交给模型。npuzoo 把工具交给运行时，由运行时写进模型自己的对话模板（RKLLM 1.2.1 起支持），再把模型的调用以工具调用的形式返回给 Home Assistant 去执行，执行结果再送回模型。

小模型调用工具更容易出错。建议从 1.5B 以上的 Qwen2.5 或 Qwen3 开始，并且只暴露需要控制的实体：Home Assistant 会把每个暴露的实体都写进提示词，而在 NPU 上，读提示词（prefill）比生成回答更花时间。

**思考模式。**如果你的 Home Assistant 版本有「回答前先思考」，它会让 Qwen3 先推理；npuzoo 把推理过程和回答分开返回。语音场景建议关掉，太慢。

**上下文长度。**带工具、再加几十个实体的提示词很容易超过 2000 个 token。默认的 `--context 4096` 是合适的起点；它不能超过模型转换时设定的上下文长度。

## Open WebUI

两种连接方式都可以：

- 管理员设置 → 连接 → Ollama API：`http://板子IP:11434`
- 管理员设置 → 连接 → OpenAI API：`http://板子IP:11434/v1`，API Key 随便填

Qwen3 和 DeepSeek-R1 蒸馏模型的推理过程单独返回（OpenAI 接口里是 `reasoning_content`；Ollama 接口在请求要求思考时放在 `thinking`）。

## Python

```python
from openai import OpenAI

client = OpenAI(base_url="http://板子IP:11434/v1", api_key="none")
r = client.chat.completions.create(model="qwen3-1.7b",
                                   messages=[{"role": "user", "content": "你好"}])
print(r.choices[0].message.content, r.npuzoo)   # npuzoo 字段里是实测的 tok/s
```

工具调用用常规的 `tools=[...]` 参数，结果在 `message.tool_calls` 里。

## 开机自启

用 systemd 服务让它重启后自动运行。把下面内容存为 `/etc/systemd/system/npuzoo.service`，用户名和路径换成你自己的：

```ini
[Unit]
Description=npuzoo serve
After=network-online.target
Wants=network-online.target

[Service]
User=orangepi
ExecStart=/home/orangepi/.local/bin/npuzoo serve /home/orangepi/models/qwen3-1.7b.rkllm --port 11434 --model-name qwen3-1.7b
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

然后执行 `sudo systemctl daemon-reload && sudo systemctl enable --now npuzoo`，用 `journalctl -u npuzoo -f` 看日志。这个用户能用 `npuzoo doctor` 查到 NPU，服务就能用；如果这个用户读不了 NPU 设备，把用户加进设备所属的组（常见是 `render` 或 `video`），不要用 root 跑服务。

## 预期

- **一次处理一个请求。**NPU 同时只跑一个生成，其他请求排队。
- **对话记忆在运行时里。**新请求延续上一轮对话时，npuzoo 接着运行时里的历史往下说；不是延续（新对话、改过消息、工具变了）就从头开始。响应头 `X-Npuzoo-History` 会说明是哪种。
- **速度是运行时自己测的。**OpenAI 接口的每个响应都在 `npuzoo` 字段里带上 prefill 和生成速度；`npuzoo bench` 用可重复的方式测同样的指标。
