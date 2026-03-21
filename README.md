# py-twins

`py-twins` 是一个用 Python 实现的本地 AI 编码与工具执行工程，包含统一的 CLI、可恢复的 agent 会话和浏览器 Web UI。

项目当前主要面向以下场景：

- 在本地工作区中读取、搜索、编辑和写入代码
- 通过 agent 循环调用工具完成多步任务
- 通过浏览器界面与模型和工具交互

## 功能概览

### 核心模块

- `ai`
  - 模型与 provider 抽象
  - `openai-completions` / `anthropic-messages` provider
  - 流式输出、重试、基础多模态请求支持
- `agent`
  - assistant/tool 循环
  - 工具调用事件流
  - 自动中止、轮数与工具调用限制
- `coding_agent`
  - 可恢复的 JSONL 会话
  - prompt template、skills、extensions、settings
  - print / interactive / rpc 三种运行模式
- `web_ui`
  - 浏览器端会话界面
  - prompt、abort、切换模型、导出会话
  - 可选记录最终发往大模型的请求 payload
- `tui`
  - 文本界面基础组件和输入能力

### 内置工具

当前 coding tools 包括：

- `read`
- `write`
- `edit`
- `bash`
- `grep`
- `find`
- `ls`
- `screenshot`

其中：

- `read` 支持图片文件读取并返回多模态 image block
- `screenshot` 在 macOS 上可截图并将图片传入后续模型请求
- `agent` 会把图片型工具结果转换为多模态上下文继续发送给模型

### 会话与恢复能力

- 会话以 JSONL 持久化
- 支持继续最近一次会话
- 支持 session export 为 HTML
- 支持自动 retry 和自动 compaction
- 支持手动 compact

## 安装

要求：

- Python 3.11+

安装方式：

```bash
python -m pip install -e .
```

安装后可直接使用命令：

```bash
py-twins
```

## 快速开始

列出当前可用工具：

```bash
py-twins list-tools
```

列出主要模块：

```bash
py-twins list-packages
```

直接执行单个工具：

```bash
py-twins tool read --input '{"path":"README.md"}'
py-twins tool bash --input '{"command":"pwd"}'
```

运行单轮 agent：

```bash
py-twins agent --message "summarize this repository"
```

## coding-agent

`coding-agent` 提供面向编码任务的会话式运行模式。

一次性输出：

```bash
py-twins coding-agent -p "explain the project structure"
```

继续最近会话：

```bash
py-twins coding-agent --resume -p "continue"
```

导出当前会话为 HTML：

```bash
py-twins coding-agent -p "review the latest changes" --export /tmp/pi-session.html
```

列出模型：

```bash
py-twins coding-agent --list-models
```

RPC 模式：

```bash
printf '%s\n' '{"type":"get_state"}' '{"type":"shutdown"}' | py-twins coding-agent --mode rpc
```

常用参数：

```bash
py-twins coding-agent \
  --cwd /path/to/workspace \
  --workspace /path/to/workspace/.pi \
  --thinking medium \
  --skill /path/to/skills \
  --extension /path/to/extensions
```

默认情况下，`coding-agent` 会把智能体工作空间放在 `<cwd>/.pi`，会话默认写入 `<cwd>/.pi/sessions`。

## Web UI

启动浏览器界面：

```bash
py-twins web-ui \
  --cwd /path/to/workspace \
  --workspace /path/to/workspace/.pi \
  --host 127.0.0.1 \
  --port 8765 \
  --base-url http://your-llm-endpoint/v1 \
  --api-key your-api-key \
  --model your-model
```

启动后访问：

```text
http://127.0.0.1:8765
```

常用参数：

- `--resume`
- `--workspace /path/to/workspace/.pi`
- `--no-tools`
- `--thinking-level off|minimal|low|medium|high|xhigh`
- `--session-dir /path/to/sessions`
- `--llm-request-log /tmp/web-ui-requests.jsonl`

默认情况下，`web-ui` 启动时创建的智能体会使用 `<cwd>/.pi` 作为默认工作空间，并把会话保存在 `<cwd>/.pi/sessions`。

Web UI 默认直接使用仓库内置的静态前端资源；如果你有单独构建好的前端目录，也可以显式指定：

```bash
py-twins web-ui --frontend-dir /path/to/dist
```

仓库中还包含一个最小示例：

```bash
python examples/web_ui_style_example.py --prompt "Reply with exactly OK." --no-tools
```

## 配置与资源

默认配置目录位于：

```text
~/.pi/agent
```

项目级配置通常位于：

```text
<workspace>/.pi/settings.json
```

支持的资源包括：

- settings
- prompt templates
- skills
- extensions
- sessions

## 测试

运行测试：

```bash
pytest -q
```

如果只想运行某一组测试：

```bash
pytest -q tests/test_agent_loop_parity.py
pytest -q tests/test_ai_provider_parity.py
pytest -q tests/test_web_ui_example_parity.py
```
