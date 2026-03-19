from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class MomWorkspace:
    base_dir: str

    def root(self) -> Path:
        return Path(self.base_dir)

    def global_memory_path(self) -> str:
        return str(self.root() / "MEMORY.md")

    def settings_path(self) -> str:
        return str(self.root() / "settings.json")

    def events_dir(self) -> str:
        return str(self.root() / "events")

    def skills_dir(self) -> str:
        return str(self.root() / "skills")

    def channel_dir(self, channel_id: str) -> str:
        return str(self.root() / channel_id)

    def channel_memory_path(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "MEMORY.md")

    def channel_log_path(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "log.jsonl")

    def channel_context_path(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "context.jsonl")

    def channel_attachments_dir(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "attachments")

    def channel_scratch_dir(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "scratch")

    def channel_skills_dir(self, channel_id: str) -> str:
        return str(Path(self.channel_dir(channel_id)) / "skills")
