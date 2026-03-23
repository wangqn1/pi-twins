# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .messages import create_branch_summary_message, create_compaction_summary_message, create_custom_message
from .workspace import resolve_session_dir

CURRENT_SESSION_VERSION = 3


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _short_id() -> str:
    return uuid4().hex[:8]


def _to_json_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_json_value(v) for k, v in value.items()}
    return value


@dataclass
class SessionContext:
    messages: list[Any]
    thinking_level: str
    model: dict[str, str] | None


class SessionManager:
    def __init__(
        self,
        cwd: str,
        session_dir: str,
        session_file: str | None,
        persist: bool,
        session_id: str | None = None,
    ) -> None:
        self.cwd = cwd
        self.session_dir = session_dir
        self.session_file = session_file
        self.persist = persist

        self.session_id = ""
        self.file_entries: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.labels_by_id: dict[str, str] = {}
        self.leaf_id: str | None = None

        if self.persist:
            Path(self.session_dir).mkdir(parents=True, exist_ok=True)

        if session_file is not None:
            self.set_session_file(session_file)
        else:
            self.new_session(session_id=session_id)

    def _rebuild_index(self) -> None:
        self.by_id = {}
        self.labels_by_id = {}
        self.leaf_id = None
        for entry in self.file_entries:
            if entry["type"] == "session":
                continue
            self.by_id[entry["id"]] = entry
            self.leaf_id = entry["id"]
            if entry["type"] == "label":
                target_id = entry["targetId"]
                label = entry.get("label")
                if label:
                    self.labels_by_id[target_id] = label
                elif target_id in self.labels_by_id:
                    del self.labels_by_id[target_id]

    def _rewrite_file(self) -> None:
        if not self.persist or self.session_file is None:
            return
        lines = [json.dumps(entry, ensure_ascii=False) for entry in self.file_entries]
        Path(self.session_file).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_entry(self, entry: dict[str, Any]) -> None:
        self.file_entries.append(entry)
        self.by_id[entry["id"]] = entry
        self.leaf_id = entry["id"]
        if entry["type"] == "label":
            if entry.get("label"):
                self.labels_by_id[entry["targetId"]] = entry["label"]
            elif entry["targetId"] in self.labels_by_id:
                del self.labels_by_id[entry["targetId"]]
        self._rewrite_file()

    def new_session(self, parent_session: str | None = None, session_id: str | None = None) -> str | None:
        self.session_id = session_id or str(uuid4())
        now = _iso_now()
        header: dict[str, Any] = {
            "type": "session",
            "version": CURRENT_SESSION_VERSION,
            "id": self.session_id,
            "timestamp": now,
            "cwd": self.cwd,
        }
        if parent_session is not None:
            header["parentSession"] = parent_session

        self.file_entries = [header]
        self.by_id = {}
        self.labels_by_id = {}
        self.leaf_id = None

        if self.persist:
            file_stamp = now.replace(":", "-").replace(".", "-")
            self.session_file = str(Path(self.session_dir) / f"{file_stamp}_{self.session_id}.jsonl")
        self._rewrite_file()
        return self.session_file

    def set_session_file(self, path: str) -> None:
        self.session_file = str(Path(path).resolve())
        if not Path(self.session_file).exists():
            self.new_session()
            self.session_file = str(Path(path).resolve())
            return

        loaded: list[dict[str, Any]] = []
        for raw_line in Path(self.session_file).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                loaded.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not loaded or loaded[0].get("type") != "session":
            self.new_session()
            self.session_file = str(Path(path).resolve())
            self._rewrite_file()
            return

        self.file_entries = loaded
        self.session_id = loaded[0]["id"]
        self._rebuild_index()

    def get_cwd(self) -> str:
        return self.cwd

    def get_session_dir(self) -> str:
        return self.session_dir

    def get_session_id(self) -> str:
        return self.session_id

    def get_session_file(self) -> str | None:
        return self.session_file

    def is_persisted(self) -> bool:
        return self.persist

    def append_message(self, message: Any) -> str:
        entry = {
            "type": "message",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "message": _to_json_value(message),
        }
        self._append_entry(entry)
        return entry["id"]

    def append_thinking_level_change(self, thinking_level: str) -> str:
        entry = {
            "type": "thinking_level_change",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "thinkingLevel": thinking_level,
        }
        self._append_entry(entry)
        return entry["id"]

    def append_model_change(self, provider: str, model_id: str) -> str:
        entry = {
            "type": "model_change",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "provider": provider,
            "modelId": model_id,
        }
        self._append_entry(entry)
        return entry["id"]

    def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: Any = None,
        from_hook: bool | None = None,
    ) -> str:
        entry = {
            "type": "compaction",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "summary": summary,
            "firstKeptEntryId": first_kept_entry_id,
            "tokensBefore": tokens_before,
        }
        if details is not None:
            entry["details"] = _to_json_value(details)
        if from_hook is not None:
            entry["fromHook"] = from_hook
        self._append_entry(entry)
        return entry["id"]

    def append_custom_entry(self, custom_type: str, data: Any = None) -> str:
        entry = {
            "type": "custom",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "customType": custom_type,
            "data": _to_json_value(data),
        }
        self._append_entry(entry)
        return entry["id"]

    def append_custom_message_entry(
        self,
        custom_type: str,
        content: str | list[dict[str, Any]],
        display: bool,
        details: Any = None,
    ) -> str:
        entry = {
            "type": "custom_message",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "customType": custom_type,
            "content": _to_json_value(content),
            "display": bool(display),
        }
        if details is not None:
            entry["details"] = _to_json_value(details)
        self._append_entry(entry)
        return entry["id"]

    def append_label_change(self, target_id: str, label: str | None) -> str:
        if target_id not in self.by_id:
            raise ValueError(f"Entry {target_id} not found")
        entry = {
            "type": "label",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "targetId": target_id,
            "label": label,
        }
        self._append_entry(entry)
        return entry["id"]

    def append_session_info(self, name: str) -> str:
        entry = {
            "type": "session_info",
            "id": _short_id(),
            "parentId": self.leaf_id,
            "timestamp": _iso_now(),
            "name": name.strip(),
        }
        self._append_entry(entry)
        return entry["id"]

    def get_session_name(self) -> str | None:
        for entry in reversed(self.get_entries()):
            if entry["type"] == "session_info" and entry.get("name"):
                return str(entry["name"])
        return None

    def get_leaf_id(self) -> str | None:
        return self.leaf_id

    def get_leaf_entry(self) -> dict[str, Any] | None:
        if self.leaf_id is None:
            return None
        return self.by_id.get(self.leaf_id)

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self.by_id.get(entry_id)

    def get_entries(self) -> list[dict[str, Any]]:
        return [entry for entry in self.file_entries if entry["type"] != "session"]

    def get_header(self) -> dict[str, Any] | None:
        return self.file_entries[0] if self.file_entries and self.file_entries[0]["type"] == "session" else None

    def get_branch(self, from_id: str | None = None) -> list[dict[str, Any]]:
        start_id = from_id if from_id is not None else self.leaf_id
        path: list[dict[str, Any]] = []
        current = self.by_id.get(start_id) if start_id else None
        while current is not None:
            path.insert(0, current)
            parent_id = current.get("parentId")
            current = self.by_id.get(parent_id) if parent_id else None
        return path

    def get_children(self, parent_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self.by_id.values() if entry.get("parentId") == parent_id]

    def get_label(self, entry_id: str) -> str | None:
        return self.labels_by_id.get(entry_id)

    def branch(self, branch_from_id: str) -> None:
        if branch_from_id not in self.by_id:
            raise ValueError(f"Entry {branch_from_id} not found")
        self.leaf_id = branch_from_id

    def reset_leaf(self) -> None:
        self.leaf_id = None

    def branch_with_summary(
        self,
        branch_from_id: str | None,
        summary: str,
        details: Any = None,
        from_hook: bool | None = None,
    ) -> str:
        if branch_from_id is not None and branch_from_id not in self.by_id:
            raise ValueError(f"Entry {branch_from_id} not found")
        self.leaf_id = branch_from_id
        entry = {
            "type": "branch_summary",
            "id": _short_id(),
            "parentId": branch_from_id,
            "timestamp": _iso_now(),
            "fromId": branch_from_id or "root",
            "summary": summary,
        }
        if details is not None:
            entry["details"] = _to_json_value(details)
        if from_hook is not None:
            entry["fromHook"] = from_hook
        self._append_entry(entry)
        return entry["id"]

    def create_branched_session(self, leaf_id: str) -> str | None:
        path_entries = self.get_branch(leaf_id)
        if not path_entries:
            raise ValueError(f"Entry {leaf_id} not found")

        previous_session = self.session_file
        self.new_session(parent_session=previous_session)
        for entry in path_entries:
            copied = dict(entry)
            self.file_entries.append(copied)
        self._rebuild_index()
        self._rewrite_file()
        return self.session_file

    def get_tree(self) -> list[dict[str, Any]]:
        nodes: dict[str, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for entry in self.get_entries():
            nodes[entry["id"]] = {"entry": entry, "children": [], "label": self.labels_by_id.get(entry["id"])}
        for entry in self.get_entries():
            node = nodes[entry["id"]]
            parent_id = entry.get("parentId")
            if parent_id is None or parent_id not in nodes:
                roots.append(node)
            else:
                nodes[parent_id]["children"].append(node)
        return roots

    def build_session_context(self) -> SessionContext:
        path = self.get_branch()
        thinking_level = "off"
        model: dict[str, str] | None = None
        compaction: dict[str, Any] | None = None

        for entry in path:
            if entry["type"] == "thinking_level_change":
                thinking_level = str(entry["thinkingLevel"])
            elif entry["type"] == "model_change":
                model = {"provider": str(entry["provider"]), "modelId": str(entry["modelId"])}
            elif entry["type"] == "message":
                message = entry["message"]
                if isinstance(message, dict) and message.get("role") == "assistant":
                    model = {"provider": str(message.get("provider", "")), "modelId": str(message.get("model", ""))}
            elif entry["type"] == "compaction":
                compaction = entry

        def append_message(messages: list[Any], entry: dict[str, Any]) -> None:
            if entry["type"] == "message":
                messages.append(entry["message"])
            elif entry["type"] == "custom_message":
                timestamp_ms = int(datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
                messages.append(
                    create_custom_message(
                        custom_type=entry["customType"],
                        content=entry["content"],
                        display=bool(entry["display"]),
                        details=entry.get("details"),
                        timestamp_ms=timestamp_ms,
                    )
                )
            elif entry["type"] == "branch_summary" and entry.get("summary"):
                timestamp_ms = int(datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
                messages.append(
                    create_branch_summary_message(
                        summary=str(entry["summary"]),
                        from_id=str(entry.get("fromId", "root")),
                        timestamp_ms=timestamp_ms,
                    )
                )

        messages: list[Any] = []
        if compaction is not None:
            timestamp_ms = int(datetime.fromisoformat(compaction["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
            messages.append(
                create_compaction_summary_message(
                    summary=str(compaction["summary"]),
                    tokens_before=int(compaction["tokensBefore"]),
                    timestamp_ms=timestamp_ms,
                )
            )
            compaction_index = next(index for index, entry in enumerate(path) if entry["id"] == compaction["id"])
            found_first_kept = False
            for entry in path[:compaction_index]:
                if entry["id"] == compaction["firstKeptEntryId"]:
                    found_first_kept = True
                if found_first_kept:
                    append_message(messages, entry)
            for entry in path[compaction_index + 1 :]:
                append_message(messages, entry)
        else:
            for entry in path:
                append_message(messages, entry)

        return SessionContext(messages=messages, thinking_level=thinking_level, model=model)

    @staticmethod
    def _default_session_dir(cwd: str) -> str:
        root = Path(resolve_session_dir(cwd))
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    @classmethod
    def create(cls, cwd: str, session_dir: str | None = None, session_id: str | None = None) -> SessionManager:
        directory = session_dir or cls._default_session_dir(cwd)
        return cls(cwd=cwd, session_dir=directory, session_file=None, persist=True, session_id=session_id)

    @classmethod
    def open(cls, path: str, session_dir: str | None = None) -> SessionManager:
        resolved = str(Path(path).resolve())
        cwd = Path.cwd().as_posix()
        if Path(resolved).exists():
            try:
                first_line = Path(resolved).read_text(encoding="utf-8").splitlines()[0]
                header = json.loads(first_line)
                if isinstance(header, dict) and "cwd" in header:
                    cwd = str(header["cwd"])
            except Exception:  # noqa: BLE001
                pass
        directory = session_dir or str(Path(resolved).parent)
        return cls(cwd=cwd, session_dir=directory, session_file=resolved, persist=True)

    @classmethod
    def continue_recent(cls, cwd: str, session_dir: str | None = None) -> SessionManager:
        directory = Path(session_dir or cls._default_session_dir(cwd))
        directory.mkdir(parents=True, exist_ok=True)
        files = sorted(directory.glob("*.jsonl"), key=lambda file: file.stat().st_mtime, reverse=True)
        if files:
            return cls(cwd=cwd, session_dir=str(directory), session_file=str(files[0]), persist=True)
        return cls(cwd=cwd, session_dir=str(directory), session_file=None, persist=True)

    @classmethod
    def in_memory(cls, cwd: str | None = None) -> SessionManager:
        return cls(cwd=cwd or Path.cwd().as_posix(), session_dir="", session_file=None, persist=False)

    @classmethod
    def fork_from(cls, source_path: str, target_cwd: str, session_dir: str | None = None) -> SessionManager:
        source = Path(source_path).resolve()
        if not source.exists():
            raise ValueError(f"Source session not found: {source_path}")

        source_entries: list[dict[str, Any]] = []
        for raw_line in source.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                source_entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not source_entries or source_entries[0].get("type") != "session":
            raise ValueError(f"Invalid source session: {source_path}")

        manager = cls.create(target_cwd, session_dir=session_dir)
        manager.new_session(parent_session=str(source))
        manager.file_entries.extend(entry for entry in source_entries if entry.get("type") != "session")
        manager._rebuild_index()
        manager._rewrite_file()
        return manager

    @classmethod
    def list(cls, cwd: str, session_dir: str | None = None) -> list[dict[str, Any]]:
        directory = Path(session_dir or cls._default_session_dir(cwd))
        if not directory.exists():
            return []
        results: list[dict[str, Any]] = []
        for file in sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                lines = file.read_text(encoding="utf-8").splitlines()
                if not lines:
                    continue
                header = json.loads(lines[0])
                if not isinstance(header, dict) or header.get("type") != "session":
                    continue
                results.append(
                    {
                        "path": str(file),
                        "id": str(header.get("id", "")),
                        "cwd": str(header.get("cwd", "")),
                        "created": str(header.get("timestamp", "")),
                        "modified": file.stat().st_mtime,
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return results

    @classmethod
    def list_all(cls, root_sessions_dir: str | None = None) -> list[dict[str, Any]]:
        if root_sessions_dir is None:
            root = Path.home() / ".pi" / "agent" / "sessions"
        else:
            root = Path(root_sessions_dir)
        if not root.exists():
            return []

        results: list[dict[str, Any]] = []
        for directory in root.iterdir():
            if not directory.is_dir():
                continue
            try:
                entries = cls.list(cwd="", session_dir=str(directory))
                results.extend(entries)
            except Exception:  # noqa: BLE001
                continue
        results.sort(key=lambda item: float(item.get("modified", 0)), reverse=True)
        return results
