# 功能矩阵与阶段计划

## 目标

围绕当前项目的本地编码主链路逐步完善核心能力，最终覆盖：

1. 多 Provider LLM 统一层（`ai`）
2. Agent 状态机与工具循环（`agent`）
3. 交互式 coding CLI（`coding-agent`）
4. TUI/Web UI（`tui` + `web-ui`，后续阶段）

## 功能映射（当前状态）

| 模块 | 目标能力 | Python 状态 |
|---|---|---|
| Core Tools | `read/write/edit/bash/grep/find/ls` | Stage 1 已实现 |
| Truncation | 行数/字节双阈值、head/tail 截断 | Stage 1 已实现 |
| CLI | 统一入口、工具执行协议 | Stage 1 已实现 |
| Session | JSONL 会话树、分支、恢复 | Stage 3 增强（含 compaction/retry 恢复） |
| Agent Loop | 事件流、tool call、follow-up/steering | Stage 2 最小实现完成 |
| LLM Provider Layer | OpenAI/Anthropic/Google 等统一接口 | Stage 3 增强（OpenAI/Anthropic + retry） |
| Extensions/Skills | 插件、技能装载、资源发现 | Stage 3 已落地扩展运行器、本地 extension loader、skills discovery、settings/resource loader、prompt templates、slash commands、system prompt 组装 |
| RPC/JSON Mode | 进程协议与机器可读输出 | Stage 3 已落地 `coding_agent` print/json/rpc 最小链路 |
| TUI Core | 终端抽象、输入缓冲、差分渲染、基础组件 | Stage 3 已落地 fuzzy/stdin-buffer/utils/terminal/minimal TUI foundation，以及 keys/keybindings/autocomplete/kill-ring/undo-stack/basic + interactive components + markdown + editor skeleton |

## 分阶段实施

### Stage 1（已完成）

- 功能文档总索引建立
- Python 工程骨架建立
- 核心工具链复现：`read/write/edit/bash/grep/find/ls`
- 单元测试基线建立

### Stage 2（已完成，最小可用）

- 引入 `agent`（事件流 + 工具循环 + 队列消息）
- 引入 `coding_agent.session_manager`（JSONL 树结构 + context 构建）
- 引入 `coding_agent.agent_session/sdk`（Agent 与 Session 生命周期打通）
- 引入 `ai`（模型/消息抽象 + 脚本后端）
- 增加 `parity-check` 命令执行核心模块检查

### Stage 3（进行中）

- Provider 抽象层：`api_registry` + `stream/complete` 已落地
- OpenAI/Anthropic provider 已落地并覆盖基础映射测试
- provider retry（429/5xx/network + Retry-After + delay cap）已落地
- AgentSession 自动恢复：retry + context compaction 已落地（最小可用）
- context compaction 的 LLM 摘要主路径与 split-turn prefix 摘要已落地
- compaction 扩展点：before-compact hook 覆盖摘要已落地
- stale usage 防误判逻辑已落地（避免 compact 后旧 usage 触发二次 auto-compaction）
- 扩展运行器初版已落地：`before_agent_start` / `context` / `tool_call` / `tool_result` / `session_before_compact`
- 扩展工具注册与工具包装已落地（可拦截、阻断、改写工具结果）
- `coding_agent` 资源层初版已落地：`settings_manager`、`resource_loader`、本地 `extension loader`、`skills discovery`、`prompt_templates`、`slash_commands`、`system_prompt`
- `coding_agent` 运行入口初版已落地：`args`、`main`、`print/json/rpc mode`、根 CLI `coding-agent`
- `coding_agent` CLI 辅助能力已增强：`--list-models`、文本式 `--resume`、`--export`
- `coding_agent` package manager 初版已落地：本地 source 的 `install/remove/update/list/config`
- `coding_agent` 目录结构已整理为 `cli/core/modes`，原独立 `core` 目录已移除并并入 `coding_agent/core/tools`
- Python 模块目录已整体平铺到 `src/*`
- `coding_agent` 命令层初版已落地：slash command dispatcher、`session/name/new/resume/reload/export/model/compact`
- `coding_agent` 扩展/认证层增强已落地：extension command execution、`auth_storage`、`login/logout`
- `coding_agent` 分享/导出层增强已落地：`share` bundle、增强版 `export-html`、RPC `share_session`
- `tui` 基础层已落地：fuzzy match、stdin buffer、ANSI 宽度/截断工具、memory terminal、最小 `TUI/Container`
- `tui` 编辑状态层已落地：keys、keybindings、autocomplete、kill ring、undo stack
- `tui` 基础组件已落地：`Text`、`Spacer`、`Box`、`TruncatedText`、`Loader`、`CancellableLoader`
- `tui` 交互组件已落地：`Input`、`SelectList`、`SettingsList`
- `tui` 渲染组件已落地：`Markdown`
- `tui` 编辑器骨架已落地：`EditorComponent` 协议、`word_wrap_line`、最小 `Editor`
- 仍待补齐：更完整的 OAuth/share 发布链路 / interactive UI / 更完整的会话事件与中断语义

### Stage 4

- 扩展体系（extensions + skills + prompt templates）
- 交互式终端 UI（最小可用版）
- RPC 协议兼容层

### Stage 5

- 安全策略、权限隔离、部署脚本
- 回归测试与兼容性收敛
