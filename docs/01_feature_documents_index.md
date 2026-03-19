# pi-mono 功能文档总索引

说明：该索引面向“功能复现”，优先收录 `README.md` 与 `packages/*/docs/*.md` 中直接描述能力、配置、协议、交互的文档（不含 changelog/测试夹具）。

附：`py-twins` 本地一致性检查说明见 `docs/03_core_parity_check.md`。

## 根文档

| 路径 | 主题 |
|---|---|
| `README.md` | monorepo 总览与包清单 |

## packages/ai

| 路径 | 主题 |
|---|---|
| `packages/ai/README.md` | 统一多 Provider LLM API、流式事件、工具调用、图像输入、推理模式、OAuth、上下文序列化 |

## packages/agent

| 路径 | 主题 |
|---|---|
| `packages/agent/README.md` | Agent 状态机、事件流、工具执行循环、steering/follow-up、低层 loop API |

## packages/coding-agent

| 路径 | 主题 |
|---|---|
| `packages/coding-agent/README.md` | 交互式编码 CLI、会话管理、扩展体系、命令体系、运行模式 |
| `packages/coding-agent/docs/providers.md` | Provider 与鉴权配置 |
| `packages/coding-agent/docs/models.md` | 模型选择与自定义模型 |
| `packages/coding-agent/docs/settings.md` | 设置项语义与优先级 |
| `packages/coding-agent/docs/keybindings.md` | 键位系统与可配置绑定 |
| `packages/coding-agent/docs/session.md` | 会话 JSONL 结构 |
| `packages/coding-agent/docs/tree.md` | 会话树导航与分支操作 |
| `packages/coding-agent/docs/compaction.md` | 上下文压缩与分支摘要 |
| `packages/coding-agent/docs/json.md` | JSON 事件流输出格式 |
| `packages/coding-agent/docs/rpc.md` | RPC 模式协议 |
| `packages/coding-agent/docs/sdk.md` | SDK 嵌入式使用方式 |
| `packages/coding-agent/docs/extensions.md` | 扩展机制（命令/工具/UI/生命周期事件） |
| `packages/coding-agent/docs/skills.md` | 技能发现与执行 |
| `packages/coding-agent/docs/prompt-templates.md` | 提示词模板系统 |
| `packages/coding-agent/docs/themes.md` | 主题系统 |
| `packages/coding-agent/docs/packages.md` | Pi 包安装/更新/启用 |
| `packages/coding-agent/docs/tui.md` | TUI 组件与渲染 |
| `packages/coding-agent/docs/custom-provider.md` | 自定义 provider 方式 |
| `packages/coding-agent/docs/development.md` | 开发与调试流程 |
| `packages/coding-agent/docs/terminal-setup.md` | 终端能力与配置建议 |
| `packages/coding-agent/docs/tmux.md` | tmux 使用建议 |
| `packages/coding-agent/docs/shell-aliases.md` | shell alias 集成 |
| `packages/coding-agent/docs/windows.md` | Windows 平台适配 |
| `packages/coding-agent/docs/termux.md` | Termux 平台适配 |

## packages/mom

| 路径 | 主题 |
|---|---|
| `packages/mom/README.md` | Slack Bot 主流程、数据目录、记忆与技能、事件调度、安全模型 |
| `packages/mom/docs/slack-bot-minimal-guide.md` | 最小化 Slack 接入 |
| `packages/mom/docs/sandbox.md` | Docker/Host 沙箱语义 |
| `packages/mom/docs/events.md` | 事件文件协议与定时唤醒 |
| `packages/mom/docs/artifacts-server.md` | Artifacts 服务 |
| `packages/mom/docs/new.md` | 多平台重构设计说明 |
| `packages/mom/docs/v86.md` | v86 沙箱评估 |

## packages/pods

| 路径 | 主题 |
|---|---|
| `packages/pods/README.md` | GPU Pod 部署管理、vLLM 启停、模型配置、agent 测试入口 |
| `packages/pods/docs/models.md` | 预置模型配置清单 |
| `packages/pods/docs/qwen3-coder.md` | Qwen3-Coder 部署实践 |
| `packages/pods/docs/gml-4.5.md` | GLM-4.5 部署说明 |
| `packages/pods/docs/gpt-oss.md` | GPT-OSS 运行建议 |
| `packages/pods/docs/kimi-k2.md` | Kimi-K2 部署指南 |
| `packages/pods/docs/plan.md` | pods 规划草案 |
| `packages/pods/docs/implementation-plan.md` | pods 实施计划草案 |

## packages/tui

| 路径 | 主题 |
|---|---|
| `packages/tui/README.md` | 终端差分渲染框架、组件体系、输入处理、IME 支持 |

## packages/web-ui

| 路径 | 主题 |
|---|---|
| `packages/web-ui/README.md` | Web Chat 组件、附件处理、Artifacts、存储层、CORS 代理、自定义工具渲染 |

## 示例与参考文档（用于能力补充）

| 路径 | 主题 |
|---|---|
| `packages/coding-agent/examples/README.md` | examples 总入口 |
| `packages/coding-agent/examples/extensions/README.md` | extension 示例集合 |
| `packages/coding-agent/examples/extensions/plan-mode/README.md` | plan mode 扩展示例 |
| `packages/coding-agent/examples/extensions/subagent/README.md` | subagent 扩展示例 |
| `packages/coding-agent/examples/extensions/doom-overlay/README.md` | 自定义 overlay 示例 |
| `packages/coding-agent/examples/sdk/README.md` | SDK 示例集合 |
