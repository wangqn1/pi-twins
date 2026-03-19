# 核心模块一致性检查

`py-twins` 提供了 `parity-check` 命令，用于对齐 `tools/pi-mono/packages` 与 `src/*` 下对应模块的核心结构与工具能力。

## 检查范围

- 包目录是否完整对齐（按名称归一化，`-` 与 `_` 视为等价）
- 核心包关键文件是否存在
  - `ai`: `types.py`, `backend.py`
  - `agent`: `types.py`, `loop.py`, `agent.py`
  - `coding_agent`: `main.py`, `core/messages.py`, `core/session_manager.py`, `core/tools/__init__.py`
  - `mom/pods/tui/web_ui`: `__init__.py`
- 内置工具集合是否一致
  - 期望：`read/write/edit/bash/grep/find/ls`

## 使用

```bash
cd /Users/wqn/project/python/py-twins
py-twins parity-check
```

返回码：

- `0`: 检查通过
- `1`: 存在缺失或不一致
