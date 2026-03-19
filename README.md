# py-twins

`pi-mono` 的 Python 重构工程（分阶段推进）。

当前阶段（Stage 1）目标：

- 完成 `coding-agent` 核心本地工具链的 Python 复现
- 提供统一 CLI 入口用于执行工具
- 建立功能文档索引与重构路线图，作为后续阶段基线

当前阶段（Stage 2）新增：

- 按 `pi-mono/packages` 对齐的 Python 核心模块骨架：
  - `ai`
  - `agent`
  - `coding_agent`
  - `mom`
  - `pods`
  - `tui`
  - `web_ui`
- `agent` 工具循环与事件序列最小实现
- `coding_agent.session_manager` 的 JSONL 树结构会话最小实现
- `coding_agent.agent_session` 与 `coding_agent.sdk.create_agent_session` 最小实现
- `parity-check` 核心一致性检查命令

当前阶段（Stage 3）新增：

- `ai` provider 抽象层与注册器：
  - `api_registry` / `stream` / `event_stream`
  - `env_api_keys` / `models`
- 首批真实 provider 适配：
  - `openai-completions`
  - `anthropic-messages`
- provider 重试能力：
  - 429/5xx 与网络错误重试
  - `Retry-After` 支持
  - `max_retry_delay_ms` 限制
- `complete` / `complete_simple` 统一入口
- `AgentSession` 自动恢复能力：
  - retryable error 自动重试（指数退避）
  - 上下文超限/阈值自动 compaction
  - `compact()` 手动上下文压缩
- `compaction` 摘要能力增强：
  - LLM 摘要主路径（含 `previousSummary` 增量更新）
  - split-turn prefix summary
  - LLM 不可用时模板摘要兜底
  - split-turn 双摘要并行生成
  - compact 前 hook 覆盖摘要（扩展点）
- `coding_agent` 扩展运行器初版：
  - `before_agent_start` / `context` / `tool_call` / `tool_result` / `session_before_compact`
  - 扩展工具注册与工具包装
  - `create_event_bus` 事件总线
- `coding_agent` 资源与配置层初版：
  - `settings_manager`
  - `resource_loader`
  - 本地 `extensions` 自动发现与加载
  - `skills` 自动发现与 slash command 暴露
  - `prompt_templates`
  - `slash_commands`
  - `system_prompt` 运行时组装
  - `args/main/print/rpc` 最小可用入口
  - 内置 slash command dispatcher
  - `session/export/reload/model` 基础命令
  - extension command 执行
  - `auth_storage` 与 `login/logout` 基础能力
  - `share` bundle 导出
  - 更完整的 `export-html` 页面渲染
  - interactive mode 最小 REPL 骨架
  - `--list-models` 模型列表输出
  - `--resume` 文本式 session picker
  - `--export` 直接导出 HTML
  - `install/remove/update/list/config` 基础 package manager
  - `coding_agent` 目录已按 `pi-mono` 方式重构为 `cli/core/modes`
  - 原独立 `core` 目录已并入 `coding_agent/core/tools`
  - Python 模块目录已整体平铺到 `src/*`
- `pods` 核心基础：
  - `pods.json` 配置读写
  - active pod 管理
  - 内置模型配置解析与匹配
  - SSH/SCP 命令解析与执行辅助
  - `setup/start/stop/models/logs/prompt-args` 命令 API 与 CLI 入口
- `mom` 基础运行时：
  - workspace 路径模型
  - channel store 与附件下载队列
  - `log.jsonl` 到 session context 的同步
  - immediate / one-shot / periodic 事件调度基础
  - sandbox executor、mom tools、LLM runner 骨架
  - SlackBot 本地适配、`main` 编排、根 CLI `mom` 入口
  - `--download <channel-id>` 历史导出能力
  - app mention / DM 过滤、startup 旧消息跳过、backfill 增量同步
- `tui` 基础层：
  - fuzzy match/filter
  - stdin escape sequence buffering
  - ANSI 可见宽度/截断工具
  - memory terminal 与最小 `TUI/Container` 渲染骨架
  - keys/keybindings/autocomplete
  - kill ring / undo stack
  - `Text/Spacer/Box/TruncatedText/Loader/CancellableLoader` 基础组件
  - `Input/SelectList/SettingsList` 交互组件
  - `Markdown` 渲染组件
  - `Editor` 骨架与 `EditorComponent` 协议

## 已实现（Stage 1）

- 工具：
  - `read`
  - `write`
  - `edit`
  - `bash`
  - `grep`
  - `find`
  - `ls`
- 通用能力：
  - 路径解析与 `~` 展开
  - 输出截断（行数/字节双阈值）
  - 工具执行统一返回结构
  - 命令行调用与 JSON 输入输出
- 文档：
  - `docs/01_feature_documents_index.md`
  - `docs/02_feature_matrix_and_plan.md`

## 快速开始

```bash
cd /Users/wqn/project/python/py-twins
git submodule update --init --recursive
python -m pip install -e .
```

如需重新构建 `web-ui` 前端，注意本仓库保存了针对 `tools/pi-mono` 的本地兼容补丁：

```bash
git -C tools/pi-mono apply ../patches/pi-mono-web-ui-messages.patch
```

列出工具：

```bash
py-twins list-tools
```

列出模块与一致性检查：

```bash
py-twins list-packages
py-twins parity-check
```

执行工具：

```bash
py-twins tool read --input '{"path":"README.md"}'
py-twins tool bash --input '{"command":"pwd"}'
py-twins agent --message "hello"
py-twins coding-agent -p "hello"
py-twins coding-agent --list-models
py-twins coding-agent --resume -p "continue this thread"
py-twins coding-agent -p "hello" --export /tmp/pi-session.html
printf '%s\n' '{"type":"get_state"}' '{"type":"shutdown"}' | py-twins coding-agent --mode rpc
py-twins mom /tmp/pi-mom-workspace
MOM_SLACK_BOT_TOKEN=x py-twins mom --download C123456
```

运行 web-ui 风格集成示例：

```bash
cd /Users/wqn/project/python/py-twins
LLM_BASE_URL=http://192.168.64.22:3001/v1 \
LLM_API_KEY=... \
LLM_MODEL=qwen3.5-122b-vl \
python examples/web_ui_style_example.py --prompt "Reply with exactly OK." --no-tools
```

启动直接复用 upstream `pi-web-ui` 的浏览器界面：

```bash
cd /Users/wqn/project/python/py-twins
py-twins web-ui \
  --cwd /Users/wqn/project/python/py-twins \
  --build-frontend \
  --base-url http://192.168.64.22:3001/v1 \
  --api-key sk-BZhAM3k1kT3UlRsT628904E03071425bBa4690A0F4B25417 \
  --model qwen3.5-122b-vl
```

启动后访问输出的本地地址，例如 `http://127.0.0.1:8765`。

查看功能文档索引：

```bash
py-twins docs-index
```

## 测试

```bash
cd /Users/wqn/project/python/py-twins
pytest -q
```

当前全量测试：`142 passed, 1 skipped`
