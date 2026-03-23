# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from ai import AssistantMessage, LLMContext, Model, SimpleStreamOptions, UserMessage, complete_simple, text_block

from .messages import (
    convert_to_llm,
    create_branch_summary_message,
    create_compaction_summary_message,
    create_custom_message,
)


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16_384
    keep_recent_tokens: int = 20_000


@dataclass
class RetrySettings:
    enabled: bool = True
    max_retries: int = 3
    base_delay_ms: int = 2_000
    max_delay_ms: int = 60_000


@dataclass
class ContextUsageEstimate:
    tokens: int
    usage_tokens: int
    trailing_tokens: int
    last_usage_index: int | None


def get_latest_compaction_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if isinstance(entry, dict) and entry.get("type") == "compaction":
            return entry
    return None


SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. Your task is to read a conversation between a user and an AI coding "
    "assistant, then produce a structured summary following the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."
)

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

TURN_PREFIX_SUMMARIZATION_PROMPT = """This is the PREFIX of a turn that was too large to keep. The SUFFIX (recent work) is retained.

Summarize the prefix to provide context for the retained suffix:

## Original Request
[What did the user ask for in this turn?]

## Early Progress
- [Key decisions and work done in the prefix]

## Context for Suffix
- [Information needed to understand the retained recent work]

Be concise. Focus on what's needed to understand the kept suffix."""


def calculate_context_tokens(usage: dict[str, Any]) -> int:
    total = int(usage.get("totalTokens", 0) or 0)
    if total > 0:
        return total
    return (
        int(usage.get("input", 0) or 0)
        + int(usage.get("output", 0) or 0)
        + int(usage.get("cacheRead", 0) or 0)
        + int(usage.get("cacheWrite", 0) or 0)
    )


def _role(message: Any) -> str | None:
    if isinstance(message, dict):
        return message.get("role")
    return getattr(message, "role", None)


def _content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def estimate_tokens(message: Any) -> int:
    role = _role(message)
    chars = 0

    if role == "user":
        content = _content(message)
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chars += len(str(block.get("text", "")))
    elif role == "assistant":
        content = _content(message)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    chars += len(str(block.get("text", "")))
                elif block_type == "thinking":
                    chars += len(str(block.get("thinking", "")))
                elif block_type == "toolCall":
                    chars += len(str(block.get("name", ""))) + len(str(block.get("arguments", {})))
    elif role in {"toolResult", "custom"}:
        content = _content(message)
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        chars += len(str(block.get("text", "")))
                    if block.get("type") == "image":
                        chars += 4_800
    elif role == "bashExecution":
        command = message.get("command", "") if isinstance(message, dict) else getattr(message, "command", "")
        output = message.get("output", "") if isinstance(message, dict) else getattr(message, "output", "")
        chars = len(str(command)) + len(str(output))
    elif role in {"branchSummary", "compactionSummary"}:
        summary = message.get("summary", "") if isinstance(message, dict) else getattr(message, "summary", "")
        chars = len(str(summary))

    return max((chars + 3) // 4, 0)


def _assistant_usage(message: Any) -> dict[str, Any] | None:
    if _role(message) != "assistant":
        return None

    stop_reason = message.get("stopReason") if isinstance(message, dict) else getattr(message, "stop_reason", None)
    if stop_reason in {"aborted", "error"}:
        return None

    usage = message.get("usage") if isinstance(message, dict) else getattr(message, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "to_dict"):
        return usage.to_dict()
    return None


def estimate_context_tokens(messages: list[Any]) -> ContextUsageEstimate:
    usage_info: tuple[dict[str, Any], int] | None = None
    for index in range(len(messages) - 1, -1, -1):
        usage = _assistant_usage(messages[index])
        if usage:
            usage_info = (usage, index)
            break

    if usage_info is None:
        estimate = sum(estimate_tokens(message) for message in messages)
        return ContextUsageEstimate(tokens=estimate, usage_tokens=0, trailing_tokens=estimate, last_usage_index=None)

    usage_tokens = calculate_context_tokens(usage_info[0])
    trailing_tokens = sum(estimate_tokens(messages[index]) for index in range(usage_info[1] + 1, len(messages)))
    return ContextUsageEstimate(
        tokens=usage_tokens + trailing_tokens,
        usage_tokens=usage_tokens,
        trailing_tokens=trailing_tokens,
        last_usage_index=usage_info[1],
    )


def should_compact(context_tokens: int, context_window: int, settings: CompactionSettings) -> bool:
    if not settings.enabled:
        return False
    return context_tokens > (context_window - settings.reserve_tokens)


def _entry_to_message(entry: dict[str, Any]) -> Any | None:
    entry_type = entry.get("type")
    if entry_type == "message":
        return entry.get("message")
    if entry_type == "custom_message":
        return create_custom_message(
            custom_type=str(entry.get("customType", "")),
            content=entry.get("content", ""),
            display=bool(entry.get("display", True)),
            details=entry.get("details"),
            timestamp_ms=0,
        )
    if entry_type == "branch_summary":
        return create_branch_summary_message(
            summary=str(entry.get("summary", "")),
            from_id=str(entry.get("fromId", "root")),
            timestamp_ms=0,
        )
    if entry_type == "compaction":
        return create_compaction_summary_message(
            summary=str(entry.get("summary", "")),
            tokens_before=int(entry.get("tokensBefore", 0) or 0),
            timestamp_ms=0,
        )
    return None


def _is_valid_cut_message(message: Any | None) -> bool:
    role = _role(message)
    return role in {"user", "assistant", "custom", "bashExecution", "branchSummary", "compactionSummary"}


def _find_valid_cut_points(entries: list[dict[str, Any]], start: int, end: int) -> list[int]:
    points: list[int] = []
    for index in range(start, end):
        message = _entry_to_message(entries[index])
        if _is_valid_cut_message(message):
            points.append(index)
    return points


def _find_turn_start_index(entries: list[dict[str, Any]], entry_index: int, start_index: int) -> int:
    for index in range(entry_index, start_index - 1, -1):
        message = _entry_to_message(entries[index])
        role = _role(message)
        if role in {"user", "bashExecution", "custom", "branchSummary"}:
            return index
    return -1


def _find_cut_point(entries: list[dict[str, Any]], start: int, end: int, keep_recent_tokens: int) -> dict[str, Any]:
    candidate_indexes = _find_valid_cut_points(entries, start, end)
    if not candidate_indexes:
        return {"firstKeptEntryIndex": start, "turnStartIndex": -1, "isSplitTurn": False}

    cut_index = candidate_indexes[0]
    accumulated = 0
    for index in range(end - 1, start - 1, -1):
        message = _entry_to_message(entries[index])
        if message is None:
            continue
        accumulated += estimate_tokens(message)
        if accumulated >= keep_recent_tokens:
            selected = next((candidate for candidate in candidate_indexes if candidate >= index), None)
            cut_index = selected if selected is not None else candidate_indexes[-1]
            break

    while cut_index > start:
        previous = entries[cut_index - 1]
        if previous.get("type") == "compaction":
            break
        if _entry_to_message(previous) is not None:
            break
        cut_index -= 1

    cut_message = _entry_to_message(entries[cut_index])
    is_user_cut = _role(cut_message) in {"user", "bashExecution", "custom", "branchSummary"}
    turn_start = -1 if is_user_cut else _find_turn_start_index(entries, cut_index, start)
    return {
        "firstKeptEntryIndex": cut_index,
        "turnStartIndex": turn_start,
        "isSplitTurn": (not is_user_cut) and turn_start != -1,
    }


def _extract_file_ops(messages: list[Any]) -> tuple[list[str], list[str]]:
    read_files: set[str] = set()
    written_files: set[str] = set()
    edited_files: set[str] = set()

    for message in messages:
        if _role(message) != "assistant":
            continue
        blocks = _content(message)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "toolCall":
                continue
            args = block.get("arguments", {})
            path = args.get("path") if isinstance(args, dict) else None
            if not isinstance(path, str):
                continue
            name = str(block.get("name", ""))
            if name == "read":
                read_files.add(path)
            elif name == "write":
                written_files.add(path)
            elif name == "edit":
                edited_files.add(path)

    modified = written_files | edited_files
    read_only = sorted(path for path in read_files if path not in modified)
    return read_only, sorted(modified)


def prepare_compaction(path_entries: list[dict[str, Any]], settings: CompactionSettings) -> dict[str, Any] | None:
    if not path_entries:
        return None
    if path_entries[-1].get("type") == "compaction":
        return None

    previous_compaction_index = -1
    for index in range(len(path_entries) - 1, -1, -1):
        if path_entries[index].get("type") == "compaction":
            previous_compaction_index = index
            break

    boundary_start = previous_compaction_index + 1
    boundary_end = len(path_entries)
    usage_start = previous_compaction_index if previous_compaction_index >= 0 else 0

    usage_messages: list[Any] = []
    for index in range(usage_start, boundary_end):
        message = _entry_to_message(path_entries[index])
        if message is not None:
            usage_messages.append(message)
    tokens_before = estimate_context_tokens(usage_messages).tokens

    cut_point = _find_cut_point(path_entries, boundary_start, boundary_end, settings.keep_recent_tokens)
    cut_index = int(cut_point["firstKeptEntryIndex"])
    first_kept = path_entries[cut_index] if 0 <= cut_index < len(path_entries) else None
    first_kept_entry_id = first_kept.get("id") if isinstance(first_kept, dict) else None
    if not first_kept_entry_id:
        return None

    history_end = int(cut_point["turnStartIndex"]) if bool(cut_point["isSplitTurn"]) else cut_index
    messages_to_summarize: list[Any] = []
    for index in range(boundary_start, history_end):
        message = _entry_to_message(path_entries[index])
        if message is not None:
            messages_to_summarize.append(message)

    turn_prefix_messages: list[Any] = []
    if bool(cut_point["isSplitTurn"]):
        turn_start = int(cut_point["turnStartIndex"])
        for index in range(turn_start, cut_index):
            message = _entry_to_message(path_entries[index])
            if message is not None:
                turn_prefix_messages.append(message)

    previous_summary = None
    if previous_compaction_index >= 0:
        previous_summary = path_entries[previous_compaction_index].get("summary")

    read_files, modified_files = _extract_file_ops(messages_to_summarize)
    if turn_prefix_messages:
        extra_read, extra_modified = _extract_file_ops(turn_prefix_messages)
        read_files = sorted(set(read_files) | set(extra_read))
        modified_files = sorted(set(modified_files) | set(extra_modified))
    details = {"readFiles": read_files, "modifiedFiles": modified_files}
    return {
        "firstKeptEntryId": str(first_kept_entry_id),
        "messagesToSummarize": messages_to_summarize,
        "turnPrefixMessages": turn_prefix_messages,
        "isSplitTurn": bool(cut_point["isSplitTurn"]),
        "tokensBefore": int(tokens_before),
        "previousSummary": str(previous_summary) if previous_summary else None,
        "details": details,
        "settings": settings,
    }


def _extract_first_user_goal(messages: list[Any]) -> str:
    for message in messages:
        if _role(message) != "user":
            continue
        content = _content(message)
        if isinstance(content, str) and content.strip():
            return content.strip().splitlines()[0][:200]
        if isinstance(content, list):
            text_parts = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
            joined = "\n".join(part for part in text_parts if part).strip()
            if joined:
                return joined.splitlines()[0][:200]
    return "(No explicit goal captured in compacted range)"


def _assistant_progress(messages: list[Any]) -> list[str]:
    items: list[str] = []
    for message in messages:
        if _role(message) != "assistant":
            continue
        blocks = _content(message)
        if not isinstance(blocks, list):
            continue
        texts = [str(block.get("text", "")).strip() for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
        for text in texts:
            if text:
                items.append(text.splitlines()[0][:160])
            if len(items) >= 3:
                return items
    return items


def generate_compaction_summary(
    messages: list[Any],
    *,
    previous_summary: str | None = None,
    custom_instructions: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    goal = _extract_first_user_goal(messages)
    done_items = _assistant_progress(messages)
    read_files = details.get("readFiles", []) if isinstance(details, dict) else []
    modified_files = details.get("modifiedFiles", []) if isinstance(details, dict) else []

    lines = [
        "## Goal",
        goal,
        "",
        "## Constraints & Preferences",
        "- (none)",
        "",
        "## Progress",
        "### Done",
    ]
    if done_items:
        lines.extend(f"- [x] {item}" for item in done_items)
    else:
        lines.append("- [x] Conversation history compacted and preserved")
    lines.extend(
        [
            "",
            "### In Progress",
            "- [ ] Continue from recent retained context",
            "",
            "### Blocked",
            "- (none)",
            "",
            "## Key Decisions",
            "- **Compaction applied**: Older context summarized to preserve token budget.",
            "",
            "## Next Steps",
            "1. Continue from the most recent messages retained after compaction.",
            "",
            "## Critical Context",
        ]
    )
    if read_files:
        lines.append(f"- Read files: {', '.join(read_files)}")
    if modified_files:
        lines.append(f"- Modified files: {', '.join(modified_files)}")
    if not read_files and not modified_files:
        lines.append("- (none)")

    if custom_instructions:
        lines.extend(["", f"Custom focus: {custom_instructions}"])
    if previous_summary:
        lines.extend(["", "Previous summary context was merged in this checkpoint."])

    return "\n".join(lines)


def _truncate_for_summary(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... {truncated} more characters truncated]"


def _serialize_conversation(messages: list[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        role = _role(message)
        if role == "user":
            content = _content(message)
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text")
            else:
                text = ""
            if text:
                parts.append(f"[User]: {text}")
        elif role == "assistant":
            content = _content(message)
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[str] = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif block_type == "thinking":
                        thinking_parts.append(str(block.get("thinking", "")))
                    elif block_type == "toolCall":
                        arguments = block.get("arguments", {})
                        tool_calls.append(f"{block.get('name', '')}({arguments})")
            if thinking_parts:
                parts.append(f"[Assistant thinking]: {' '.join(thinking_parts)}")
            if text_parts:
                parts.append(f"[Assistant]: {' '.join(text_parts)}")
            if tool_calls:
                parts.append(f"[Assistant tool calls]: {'; '.join(tool_calls)}")
        elif role == "toolResult":
            content = _content(message)
            if isinstance(content, list):
                text = "".join(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text")
            else:
                text = str(content) if content is not None else ""
            if text:
                parts.append(f"[Tool result]: {_truncate_for_summary(text, 2000)}")
    return "\n\n".join(parts)


def _extract_text_from_assistant(message: AssistantMessage) -> str:
    texts = [str(block.get("text", "")) for block in message.content if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(part for part in texts if part).strip()


def generate_summary(
    current_messages: list[Any],
    model: Model,
    reserve_tokens: int,
    *,
    api_key: str | None = None,
    custom_instructions: str | None = None,
    previous_summary: str | None = None,
    complete_fn: Callable[[Model, LLMContext, SimpleStreamOptions | None], AssistantMessage] = complete_simple,
) -> str:
    if not current_messages and previous_summary:
        return previous_summary

    max_tokens = max(512, int(0.8 * reserve_tokens))
    base_prompt = UPDATE_SUMMARIZATION_PROMPT if previous_summary else SUMMARIZATION_PROMPT
    if custom_instructions:
        base_prompt = f"{base_prompt}\n\nAdditional focus: {custom_instructions}"

    llm_messages = convert_to_llm(current_messages)
    conversation = _serialize_conversation(llm_messages)
    prompt = f"<conversation>\n{conversation}\n</conversation>\n\n"
    if previous_summary:
        prompt += f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
    prompt += base_prompt

    options = SimpleStreamOptions(max_tokens=max_tokens)
    if api_key:
        options.api_key = api_key
    if model.reasoning:
        options.reasoning = "high"

    response = complete_fn(
        model,
        LLMContext(
            system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
            messages=[UserMessage(content=[text_block(prompt)], timestamp=0)],
            tools=[],
        ),
        options,
    )
    if response.stop_reason == "error":
        raise RuntimeError(response.error_message or "Summarization failed")
    text = _extract_text_from_assistant(response)
    if not text:
        raise RuntimeError("Summarization returned empty output")
    return text


def generate_turn_prefix_summary(
    turn_prefix_messages: list[Any],
    model: Model,
    reserve_tokens: int,
    *,
    api_key: str | None = None,
    complete_fn: Callable[[Model, LLMContext, SimpleStreamOptions | None], AssistantMessage] = complete_simple,
) -> str:
    max_tokens = max(256, int(0.4 * reserve_tokens))
    llm_messages = convert_to_llm(turn_prefix_messages)
    conversation = _serialize_conversation(llm_messages)
    prompt = f"<conversation>\n{conversation}\n</conversation>\n\n{TURN_PREFIX_SUMMARIZATION_PROMPT}"

    options = SimpleStreamOptions(max_tokens=max_tokens)
    if api_key:
        options.api_key = api_key
    if model.reasoning:
        options.reasoning = "high"

    response = complete_fn(
        model,
        LLMContext(
            system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
            messages=[UserMessage(content=[text_block(prompt)], timestamp=0)],
            tools=[],
        ),
        options,
    )
    if response.stop_reason == "error":
        raise RuntimeError(response.error_message or "Turn-prefix summarization failed")
    text = _extract_text_from_assistant(response)
    if not text:
        raise RuntimeError("Turn-prefix summarization returned empty output")
    return text


def compact(
    preparation: dict[str, Any],
    model: Model,
    *,
    api_key: str | None = None,
    custom_instructions: str | None = None,
    parallel: bool = True,
    complete_fn: Callable[[Model, LLMContext, SimpleStreamOptions | None], AssistantMessage] = complete_simple,
) -> dict[str, Any]:
    messages_to_summarize = list(preparation.get("messagesToSummarize", []))
    turn_prefix_messages = list(preparation.get("turnPrefixMessages", []))
    is_split_turn = bool(preparation.get("isSplitTurn", False))
    tokens_before = int(preparation.get("tokensBefore", 0))
    previous_summary = preparation.get("previousSummary")
    details = preparation.get("details")
    settings = preparation.get("settings")
    reserve_tokens = settings.reserve_tokens if isinstance(settings, CompactionSettings) else 16_384

    try:
        if is_split_turn and turn_prefix_messages:
            if parallel:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    history_future = pool.submit(
                        generate_summary,
                        messages_to_summarize,
                        model,
                        reserve_tokens,
                        api_key=api_key,
                        custom_instructions=custom_instructions,
                        previous_summary=previous_summary,
                        complete_fn=complete_fn,
                    )
                    prefix_future = pool.submit(
                        generate_turn_prefix_summary,
                        turn_prefix_messages,
                        model,
                        reserve_tokens,
                        api_key=api_key,
                        complete_fn=complete_fn,
                    )
                    history = history_future.result()
                    prefix = prefix_future.result()
            else:
                history = generate_summary(
                    messages_to_summarize,
                    model,
                    reserve_tokens,
                    api_key=api_key,
                    custom_instructions=custom_instructions,
                    previous_summary=previous_summary,
                    complete_fn=complete_fn,
                )
                prefix = generate_turn_prefix_summary(
                    turn_prefix_messages,
                    model,
                    reserve_tokens,
                    api_key=api_key,
                    complete_fn=complete_fn,
                )
            summary = f"{history}\n\n---\n\n**Turn Context (split turn):**\n\n{prefix}"
        else:
            summary = generate_summary(
                messages_to_summarize,
                model,
                reserve_tokens,
                api_key=api_key,
                custom_instructions=custom_instructions,
                previous_summary=previous_summary,
                complete_fn=complete_fn,
            )
    except Exception:  # noqa: BLE001
        summary = generate_compaction_summary(
            messages_to_summarize,
            previous_summary=previous_summary,
            custom_instructions=custom_instructions,
            details=details if isinstance(details, dict) else None,
        )

    return {
        "summary": summary,
        "firstKeptEntryId": str(preparation["firstKeptEntryId"]),
        "tokensBefore": tokens_before,
        "details": details,
    }
