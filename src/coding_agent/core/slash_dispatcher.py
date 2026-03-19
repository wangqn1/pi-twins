from __future__ import annotations

from pathlib import Path
from shlex import split as shlex_split

def dispatch_slash_command(session, text: str) -> bool:  # noqa: ANN001
    if not text.startswith("/"):
        return False
    try:
        parts = shlex_split(text[1:])
    except ValueError:
        parts = text[1:].split()
    if not parts:
        return False

    name = parts[0]
    args = parts[1:]

    if name == "session":
        stats = session.get_session_stats()
        session._append_local_assistant_message(  # noqa: SLF001
            f"Session: {stats.session_id}\nMessages: {stats.total_messages}\n"
            f"User: {stats.user_messages}\nAssistant: {stats.assistant_messages}\n"
            f"Tool calls: {stats.tool_calls}\nTool results: {stats.tool_results}\n"
            f"Tokens: {stats.tokens['total']}"
        )
        return True

    if name == "compact":
        result = session.compact(" ".join(args) if args else None)
        session._append_local_assistant_message(  # noqa: SLF001
            f"Compacted context.\nSummary: {result['summary']}\nTokens before: {result['tokensBefore']}"
        )
        return True

    if name == "name":
        value = " ".join(args).strip()
        if not value:
            raise ValueError("Session name cannot be empty")
        session.set_session_name(value)
        session._append_local_assistant_message(f"Session renamed to: {value}")  # noqa: SLF001
        return True

    if name == "new":
        session.new_session()
        session._append_local_assistant_message(f"Started new session: {session.session_id}")  # noqa: SLF001
        return True

    if name == "resume":
        if not args:
            raise ValueError("Usage: /resume <session-path>")
        session.switch_session(args[0])
        session._append_local_assistant_message(f"Resumed session: {session.session_file}")  # noqa: SLF001
        return True

    if name == "reload":
        session.reload()
        session._append_local_assistant_message("Reloaded settings, resources, and prompts")  # noqa: SLF001
        return True

    if name == "export":
        path = args[0] if args else None
        exported = session.export_to_html(path)
        session._append_local_assistant_message(f"Exported session HTML to: {exported}")  # noqa: SLF001
        return True

    if name == "share":
        path = args[0] if args else None
        shared = session.share_session(path)
        session._append_local_assistant_message(f"Created share bundle: {shared}")  # noqa: SLF001
        return True

    if name == "model":
        if not args:
            raise ValueError("Usage: /model <provider/model>")
        model_ref = args[0]
        if "/" in model_ref:
            provider, model_id = model_ref.split("/", 1)
        else:
            provider = session.model.provider
            model_id = model_ref
        session.set_model(type(session.model)(provider=provider, id=model_id, api=session.model.api))
        session._append_local_assistant_message(f"Model set to: {provider}/{model_id}")  # noqa: SLF001
        return True

    if name == "login":
        if len(args) < 2:
            raise ValueError("Usage: /login <provider> <api-key>")
        provider = args[0]
        api_key = args[1]
        session.auth_storage.login(provider, api_key)
        session._append_local_assistant_message(f"Stored credentials for provider: {provider}")  # noqa: SLF001
        return True

    if name == "logout":
        if not args:
            raise ValueError("Usage: /logout <provider>")
        provider = args[0]
        session.auth_storage.logout(provider)
        session._append_local_assistant_message(f"Removed credentials for provider: {provider}")  # noqa: SLF001
        return True

    if name.startswith("skill:"):
        skill_name = name.split(":", 1)[1]
        skill = next((item for item in session.resource_loader.getSkills()["skills"] if item.name == skill_name), None)
        if skill is None:
            raise ValueError(f"Unknown skill: {skill_name}")
        skill_text = Path(skill.file_path).read_text(encoding="utf-8")
        task = " ".join(args).strip()
        prompt = (
            f"Use the following skill instructions from {skill.file_path}.\n\n{skill_text}"
            + (f"\n\nTask: {task}" if task else "")
        )
        session.prompt(prompt)
        return True

    if session.extension_runner is not None:
        command = session.extension_runner.get_command(name)
        if command is not None:
            result = session.extension_runner.execute_command(name, args)
            if isinstance(result, str) and result.strip():
                session._append_local_assistant_message(result)  # noqa: SLF001
            elif isinstance(result, dict) and result.get("message"):
                session._append_local_assistant_message(str(result["message"]))  # noqa: SLF001
            elif result not in (None, ""):
                session._append_local_assistant_message(str(result))  # noqa: SLF001
            return True

    return False
