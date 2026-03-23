# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai import Message, UserMessage, text_block

COMPACTION_SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"
BRANCH_SUMMARY_PREFIX = "The following is a summary of a branch that this conversation came back from:\n\n<summary>\n"
BRANCH_SUMMARY_SUFFIX = "\n</summary>"


@dataclass
class BashExecutionMessage:
    command: str
    output: str
    exit_code: int | None
    cancelled: bool
    truncated: bool
    timestamp: int
    full_output_path: str | None = None
    exclude_from_context: bool | None = None
    role: str = "bashExecution"


@dataclass
class CustomMessage:
    custom_type: str
    content: str | list[dict[str, Any]]
    display: bool
    timestamp: int
    details: Any = None
    role: str = "custom"


@dataclass
class BranchSummaryMessage:
    summary: str
    from_id: str
    timestamp: int
    role: str = "branchSummary"


@dataclass
class CompactionSummaryMessage:
    summary: str
    tokens_before: int
    timestamp: int
    role: str = "compactionSummary"


def bash_execution_to_text(message: BashExecutionMessage) -> str:
    command = message.get("command", "") if isinstance(message, dict) else message.command
    output = message.get("output", "") if isinstance(message, dict) else message.output
    cancelled = bool(message.get("cancelled", False)) if isinstance(message, dict) else message.cancelled
    exit_code = message.get("exitCode", message.get("exit_code")) if isinstance(message, dict) else message.exit_code
    truncated = bool(message.get("truncated", False)) if isinstance(message, dict) else message.truncated
    full_output_path = message.get("fullOutputPath", message.get("full_output_path")) if isinstance(message, dict) else message.full_output_path

    text = f"Ran `{command}`\n"
    if output:
        text += f"```\n{output}\n```"
    else:
        text += "(no output)"
    if cancelled:
        text += "\n\n(command cancelled)"
    elif exit_code not in (None, 0):
        text += f"\n\nCommand exited with code {exit_code}"
    if truncated and full_output_path:
        text += f"\n\n[Output truncated. Full output: {full_output_path}]"
    return text


def create_branch_summary_message(summary: str, from_id: str, timestamp_ms: int) -> BranchSummaryMessage:
    return BranchSummaryMessage(summary=summary, from_id=from_id, timestamp=timestamp_ms)


def create_compaction_summary_message(summary: str, tokens_before: int, timestamp_ms: int) -> CompactionSummaryMessage:
    return CompactionSummaryMessage(summary=summary, tokens_before=tokens_before, timestamp=timestamp_ms)


def create_custom_message(
    custom_type: str,
    content: str | list[dict[str, Any]],
    display: bool,
    details: Any,
    timestamp_ms: int,
) -> CustomMessage:
    return CustomMessage(custom_type=custom_type, content=content, display=display, details=details, timestamp=timestamp_ms)


def _convert_attachments_to_content_blocks(attachments: list[Any]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_type = str(attachment.get("type", ""))
        if attachment_type == "image":
            data = attachment.get("content")
            mime_type = attachment.get("mimeType") or attachment.get("mime_type")
            if data and mime_type:
                content.append({"type": "image", "data": str(data), "mimeType": str(mime_type)})
        elif attachment_type == "document":
            extracted = attachment.get("extractedText") or attachment.get("extracted_text")
            if extracted:
                file_name = str(attachment.get("fileName") or attachment.get("file_name") or "document")
                content.append(text_block(f"\n\n[Document: {file_name}]\n{str(extracted)}"))
    return content


def convert_to_llm(messages: list[Any]) -> list[Message]:
    converted: list[Message] = []
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        if role in {"user", "assistant", "toolResult"}:
            converted.append(message)
            continue
        if role == "user-with-attachments":
            if isinstance(message, dict):
                raw_content = message.get("content", "")
                attachments = message.get("attachments", [])
                timestamp = int(message.get("timestamp", 0))
            else:
                raw_content = getattr(message, "content", "")
                attachments = getattr(message, "attachments", [])
                timestamp = int(getattr(message, "timestamp", 0))

            content: list[dict[str, Any]] = []
            if isinstance(raw_content, list):
                content.extend(block for block in raw_content if isinstance(block, dict))
            elif str(raw_content).strip():
                content.append(text_block(str(raw_content)))

            if isinstance(attachments, list):
                content.extend(_convert_attachments_to_content_blocks(attachments))

            converted.append(UserMessage(content=content, timestamp=timestamp))
            continue
        if role == "bashExecution":
            exclude = (
                bool(message.get("excludeFromContext") or message.get("exclude_from_context"))
                if isinstance(message, dict)
                else bool(getattr(message, "exclude_from_context", False))
            )
            if exclude:
                continue
            timestamp = message.get("timestamp", 0) if isinstance(message, dict) else message.timestamp
            converted.append(UserMessage(content=[text_block(bash_execution_to_text(message))], timestamp=int(timestamp)))
            continue
        if role == "custom":
            if isinstance(message, dict):
                content = message.get("content", "")
                timestamp = int(message.get("timestamp", 0))
            else:
                content = message.content
                timestamp = message.timestamp
            payload = content if isinstance(content, list) else [text_block(str(content))]
            converted.append(UserMessage(content=payload, timestamp=timestamp))
            continue
        if role == "branchSummary":
            summary = message.get("summary", "") if isinstance(message, dict) else message.summary
            timestamp = int(message.get("timestamp", 0)) if isinstance(message, dict) else message.timestamp
            text = BRANCH_SUMMARY_PREFIX + str(summary) + BRANCH_SUMMARY_SUFFIX
            converted.append(UserMessage(content=[text_block(text)], timestamp=timestamp))
            continue
        if role == "compactionSummary":
            summary = message.get("summary", "") if isinstance(message, dict) else message.summary
            timestamp = int(message.get("timestamp", 0)) if isinstance(message, dict) else message.timestamp
            text = COMPACTION_SUMMARY_PREFIX + str(summary) + COMPACTION_SUMMARY_SUFFIX
            converted.append(UserMessage(content=[text_block(text)], timestamp=timestamp))
            continue
    return converted
