from __future__ import annotations

from coding_agent.core.session_manager import SessionManager


def _role(message: object) -> str | None:
    if isinstance(message, dict):
        return message.get("role")
    return getattr(message, "role", None)


def test_session_context_with_compaction_keeps_expected_messages() -> None:
    session = SessionManager.in_memory("/tmp/project")
    m1 = session.append_message({"role": "user", "content": "u1", "timestamp": 1})
    m2 = session.append_message({"role": "assistant", "content": [{"type": "text", "text": "a1"}], "timestamp": 2})
    m3 = session.append_message({"role": "user", "content": "u2", "timestamp": 3})
    assert m1 and m2 and m3

    session.append_compaction("summary", first_kept_entry_id=m2, tokens_before=1200)
    session.append_message({"role": "assistant", "content": [{"type": "text", "text": "a2"}], "timestamp": 4})

    context = session.build_session_context()
    roles = [_role(message) for message in context.messages]
    assert roles[0] == "compactionSummary"
    assert roles.count("assistant") == 2
    assert roles.count("user") == 1


def test_branch_with_summary_matches_tree_navigation_model() -> None:
    session = SessionManager.in_memory("/tmp/project")
    root = session.append_message({"role": "user", "content": "start", "timestamp": 1})
    session.append_message({"role": "assistant", "content": [{"type": "text", "text": "reply"}], "timestamp": 2})

    session.branch(root)
    summary_entry = session.branch_with_summary(root, "branched summary")
    session.append_message({"role": "user", "content": "new branch", "timestamp": 3})

    context = session.build_session_context()
    assert any(_role(message) == "branchSummary" for message in context.messages)
    assert session.get_entry(summary_entry) is not None


def test_session_manager_accepts_custom_session_id() -> None:
    manager = SessionManager.create("/tmp/project", session_id="custom-session-id")

    assert manager.get_session_id() == "custom-session-id"
    header = manager.get_header()
    assert header is not None
    assert header["id"] == "custom-session-id"

    manager.new_session(session_id="next-session-id")
    assert manager.get_session_id() == "next-session-id"
    next_header = manager.get_header()
    assert next_header is not None
    assert next_header["id"] == "next-session-id"
