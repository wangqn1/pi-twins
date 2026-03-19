from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


def export_session_to_html(
    *,
    session_file: str,
    header: dict[str, Any] | None = None,
    entries: list[dict[str, Any]],
    output_path: str | None = None,
    title: str | None = None,
) -> str:
    source = Path(session_file)
    if not source.exists():
        raise ValueError(f"Session file not found: {session_file}")

    destination = Path(output_path) if output_path else source.with_suffix(".html")
    page_title = title or f"pi session: {source.stem}"

    html = _build_html(page_title, session_file=source.as_posix(), header=header, entries=entries)
    destination.write_text(html, encoding="utf-8")
    return destination.as_posix()


def _build_html(title: str, *, session_file: str, header: dict[str, Any] | None, entries: list[dict[str, Any]]) -> str:
    body_parts: list[str] = []
    for entry in entries:
        entry_type = str(entry.get("type", "unknown"))
        if entry_type == "message":
            message = entry.get("message", {})
            role = str(message.get("role", "unknown"))
            content = _message_html(message)
            meta = _entry_meta(entry)
            body_parts.append(
                f'<section class="entry message role-{_escape(role)}"><header><h2>{_escape(role)}</h2>{meta}</header>{content}</section>'
            )
        elif entry_type == "compaction":
            summary = _escape(str(entry.get("summary", "")))
            meta = _entry_meta(entry)
            tokens = _escape(str(entry.get("tokensBefore", "")))
            body_parts.append(
                f'<section class="entry compaction"><header><h2>compaction</h2>{meta}</header>'
                f'<p class="meta-line">tokens before: {tokens}</p><pre>{summary}</pre></section>'
            )
        elif entry_type == "branch_summary":
            summary = _escape(str(entry.get("summary", "")))
            meta = _entry_meta(entry)
            body_parts.append(f'<section class="entry branch"><header><h2>branch summary</h2>{meta}</header><pre>{summary}</pre></section>')
        elif entry_type == "session_info":
            name = _escape(str(entry.get("name", "")))
            meta = _entry_meta(entry)
            body_parts.append(f'<section class="entry info"><header><h2>session</h2>{meta}</header><pre>{name}</pre></section>')
        elif entry_type == "custom_message":
            content = entry.get("content", "")
            if isinstance(content, list):
                text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            else:
                text = str(content)
            meta = _entry_meta(entry)
            custom_type = _escape(str(entry.get("customType", "custom")))
            body_parts.append(
                f'<section class="entry custom"><header><h2>{custom_type}</h2>{meta}</header><pre>{_escape(text)}</pre></section>'
            )
        elif entry_type == "label":
            label = _escape(str(entry.get("label", "")))
            meta = _entry_meta(entry)
            body_parts.append(f'<section class="entry label"><header><h2>label</h2>{meta}</header><pre>{label}</pre></section>')

    body = "\n".join(body_parts)
    summary = _summary_cards(session_file=session_file, header=header, entries=entries)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: linear-gradient(180deg, #0b1220 0%, #111827 100%); color: #e5e7eb; margin: 0; padding: 24px; }}
    main {{ max-width: 1040px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 18px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .summary-card {{ border: 1px solid #253046; border-radius: 10px; padding: 14px; background: rgba(17, 24, 39, 0.9); }}
    .summary-card strong {{ display: block; color: #93c5fd; font-size: 12px; text-transform: uppercase; margin-bottom: 8px; }}
    .entry {{ border: 1px solid #374151; border-radius: 10px; padding: 16px; margin-bottom: 16px; background: rgba(31, 41, 55, 0.95); box-shadow: 0 10px 30px rgba(0,0,0,0.18); }}
    .entry header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 12px; }}
    .entry h2 {{ margin: 0; font-size: 14px; text-transform: uppercase; color: #93c5fd; }}
    .entry.role-user h2 {{ color: #86efac; }}
    .entry.role-assistant h2 {{ color: #f9a8d4; }}
    .entry pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; line-height: 1.5; }}
    .timestamp {{ color: #94a3b8; font-size: 12px; }}
    .meta-line {{ color: #cbd5e1; margin: 0 0 12px; font-size: 13px; }}
    .blocks {{ display: grid; gap: 10px; }}
    .block {{ border-radius: 8px; padding: 12px; }}
    .block-text {{ background: rgba(15, 23, 42, 0.65); }}
    .block-tool {{ background: rgba(30, 41, 59, 0.9); border: 1px solid #334155; }}
    .block-tool strong {{ display: block; color: #fcd34d; margin-bottom: 8px; }}
    .block-tool code {{ color: #e5e7eb; }}
    .fallback {{ background: rgba(15, 23, 42, 0.65); }}
  </style>
</head>
<body>
  <main>
    <h1>{_escape(title)}</h1>
    {summary}
    {body}
  </main>
</body>
</html>
"""


def _message_html(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return f'<div class="blocks"><pre class="block block-text">{_escape(content)}</pre></div>'
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(f'<pre class="block block-text">{_escape(str(block.get("text", "")))}</pre>')
            elif block.get("type") == "toolCall":
                args = block.get("arguments")
                args_text = _escape(str(args)) if args is not None else ""
                parts.append(
                    f'<div class="block block-tool"><strong>tool call: {_escape(str(block.get("name", "")))}</strong>'
                    f'<code>{args_text}</code></div>'
                )
            else:
                parts.append(f'<pre class="block fallback">{_escape(str(block))}</pre>')
        return f'<div class="blocks">{"".join(parts)}</div>'
    return f'<pre class="block fallback">{_escape(str(content))}</pre>'


def _entry_meta(entry: dict[str, Any]) -> str:
    timestamp = str(entry.get("timestamp", ""))
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        text = dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    except ValueError:
        text = timestamp
    return f'<span class="timestamp">{_escape(text)}</span>'


def _summary_cards(*, session_file: str, header: dict[str, Any] | None, entries: list[dict[str, Any]]) -> str:
    user_count = 0
    assistant_count = 0
    tool_results = 0
    for entry in entries:
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        role = message.get("role")
        if role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1
        elif role == "toolResult":
            tool_results += 1
    session_id = str((header or {}).get("id", ""))
    return (
        '<section class="summary">'
        f'<div class="summary-card"><strong>Session ID</strong><span>{_escape(session_id or "unknown")}</span></div>'
        f'<div class="summary-card"><strong>Source</strong><span>{_escape(session_file)}</span></div>'
        f'<div class="summary-card"><strong>User Messages</strong><span>{user_count}</span></div>'
        f'<div class="summary-card"><strong>Assistant Messages</strong><span>{assistant_count}</span></div>'
        f'<div class="summary-card"><strong>Tool Results</strong><span>{tool_results}</span></div>'
        f'<div class="summary-card"><strong>Total Entries</strong><span>{len(entries)}</span></div>'
        "</section>"
    )


def _escape(value: str) -> str:
    return escape(value, quote=True)
