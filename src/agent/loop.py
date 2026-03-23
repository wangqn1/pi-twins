# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from time import time
from typing import Any, Callable

from ai import AssistantMessage, LLMContext, ToolResultMessage, UserMessage, text_block

from .types import (
    AbortSignal,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    build_error_message,
)

_STREAM_UPDATE_EVENTS = {
    "text_start",
    "text_delta",
    "text_end",
    "thinking_start",
    "thinking_delta",
    "thinking_end",
    "toolcall_start",
    "toolcall_delta",
    "toolcall_end",
}


def agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    signal: AbortSignal | None = None,
) -> list[AgentMessage]:
    new_messages: list[AgentMessage] = list(prompts)
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages, *prompts],
        tools=list(context.tools),
    )

    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    for prompt in prompts:
        emit({"type": "message_start", "message": prompt})
        emit({"type": "message_end", "message": prompt})

    _run_loop(current_context, new_messages, config, emit, signal=signal, first_turn=True)
    emit({"type": "agent_end", "messages": new_messages})
    return new_messages


def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    signal: AbortSignal | None = None,
) -> list[AgentMessage]:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")
    last = context.messages[-1]
    if getattr(last, "role", None) == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    new_messages: list[AgentMessage] = []
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=list(context.messages),
        tools=list(context.tools),
    )

    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    _run_loop(current_context, new_messages, config, emit, signal=signal, first_turn=True)
    emit({"type": "agent_end", "messages": new_messages})
    return new_messages


def _run_loop(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    *,
    signal: AbortSignal | None,
    first_turn: bool,
) -> None:
    pending_messages = config.get_steering_messages() if config.get_steering_messages else []
    first = first_turn
    turn_count = 0
    tool_call_count = 0

    while True:
        _throw_if_aborted(signal)
        has_more_tool_calls = True
        steering_after_tools: list[AgentMessage] | None = None

        while has_more_tool_calls or pending_messages:
            _throw_if_aborted(signal)
            if config.max_turns is not None and turn_count >= config.max_turns:
                limit_message = _emit_limit_checkpoint(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    signal,
                    reason=f"Reached the maximum turn limit ({config.max_turns}).",
                    turn_count=turn_count,
                    tool_call_count=tool_call_count,
                )
                emit({"type": "turn_end", "message": limit_message, "toolResults": []})
                return
            if first:
                first = False
            else:
                emit({"type": "turn_start"})

            if pending_messages:
                for message in pending_messages:
                    emit({"type": "message_start", "message": message})
                    emit({"type": "message_end", "message": message})
                    current_context.messages.append(message)
                    new_messages.append(message)
                pending_messages = []

            assistant = _stream_once(current_context, config, emit, signal)
            new_messages.append(assistant)
            turn_count += 1

            if assistant.stop_reason in ("error", "aborted"):
                emit({"type": "turn_end", "message": assistant, "toolResults": []})
                return

            tool_calls = [block for block in assistant.content if block.get("type") == "toolCall"]
            has_more_tool_calls = len(tool_calls) > 0
            tool_results: list[ToolResultMessage] = []

            if has_more_tool_calls:
                execution = _execute_tool_calls(
                    current_context.tools,
                    assistant,
                    emit,
                    config.get_steering_messages,
                    signal,
                    current_context,
                    config,
                    remaining_tool_calls=None if config.max_tool_calls is None else max(config.max_tool_calls - tool_call_count, 0),
                )
                tool_results.extend(execution["tool_results"])
                tool_context_messages = execution.get("tool_context_messages", [])
                steering_after_tools = execution.get("steering_messages")
                tool_call_count += int(execution.get("executed_tool_calls", 0))
                for result in tool_results:
                    current_context.messages.append(result)
                    new_messages.append(result)
                for message in tool_context_messages:
                    current_context.messages.append(message)
                    new_messages.append(message)

            emit({"type": "turn_end", "message": assistant, "toolResults": tool_results})

            if bool(execution.get("limit_reached")) if has_more_tool_calls else False:
                limit_message = _emit_limit_checkpoint(
                    current_context,
                    new_messages,
                    config,
                    emit,
                    signal,
                    reason=f"Reached the maximum tool call limit ({config.max_tool_calls}).",
                    turn_count=turn_count,
                    tool_call_count=tool_call_count,
                )
                emit({"type": "turn_end", "message": limit_message, "toolResults": []})
                return

            if steering_after_tools:
                pending_messages = steering_after_tools
                steering_after_tools = None
            else:
                pending_messages = config.get_steering_messages() if config.get_steering_messages else []

        follow_up = config.get_follow_up_messages() if config.get_follow_up_messages else []
        if follow_up:
            pending_messages = follow_up
            continue
        return


def _stream_once(
    current_context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    signal: AbortSignal | None,
) -> AssistantMessage:
    _throw_if_aborted(signal)
    messages = current_context.messages
    if config.transform_context is not None:
        messages = config.transform_context(messages, signal)
    llm_messages = config.convert_to_llm(messages)
    llm_context = LLMContext(system_prompt=current_context.system_prompt, messages=llm_messages, tools=current_context.tools)

    options = config.options
    api_key = config.get_api_key(config.model.provider) if config.get_api_key else None
    if options is None:
        from ai import SimpleStreamOptions

        options = SimpleStreamOptions(api_key=api_key, signal=signal)
    else:
        if api_key is not None:
            options.api_key = api_key
        options.signal = signal

    response = config.stream_fn(config.model, llm_context, options)
    partial: AssistantMessage | None = None
    started = False

    for event in response:
        event_type = event.get("type")
        if event_type == "start":
            partial = event.get("partial")
            if not isinstance(partial, AssistantMessage):
                continue
            current_context.messages.append(partial)
            started = True
            emit({"type": "message_start", "message": partial})
            continue

        if event_type in _STREAM_UPDATE_EVENTS:
            partial = event.get("partial", partial)
            if isinstance(partial, AssistantMessage):
                if started and current_context.messages:
                    current_context.messages[-1] = partial
                emit({"type": "message_update", "message": partial, "assistantMessageEvent": event})
            continue

        if event_type in {"done", "error"}:
            final_message = response.result()
            if started and current_context.messages:
                current_context.messages[-1] = final_message
            else:
                current_context.messages.append(final_message)
                emit({"type": "message_start", "message": final_message})
            emit({"type": "message_end", "message": final_message})
            return final_message

    if signal is not None and signal.aborted:
        aborted_message = build_error_message(config.model, "Request was aborted", stop_reason="aborted")
        if started and current_context.messages:
            current_context.messages[-1] = aborted_message
        else:
            current_context.messages.append(aborted_message)
            emit({"type": "message_start", "message": aborted_message})
        emit({"type": "message_end", "message": aborted_message})
        return aborted_message

    final_message = response.result()
    if started and current_context.messages:
        current_context.messages[-1] = final_message
    else:
        current_context.messages.append(final_message)
        emit({"type": "message_start", "message": final_message})
    emit({"type": "message_end", "message": final_message})
    return final_message


def _execute_tool_calls(
    tools: list[AgentTool],
    assistant_message: AssistantMessage,
    emit: Callable[[AgentEvent], None],
    get_steering_messages: Callable[[], list[AgentMessage]] | None,
    signal: AbortSignal | None,
    current_context: AgentContext,
    config: AgentLoopConfig,
    remaining_tool_calls: int | None = None,
) -> dict[str, list[Any]]:
    tool_calls = [block for block in assistant_message.content if block.get("type") == "toolCall"]
    results: list[ToolResultMessage] = []
    tool_context_messages: list[UserMessage] = []
    steering_messages: list[AgentMessage] | None = None
    executed_tool_calls = 0
    limit_reached = False

    for index, tool_call in enumerate(tool_calls):
        _throw_if_aborted(signal)
        if remaining_tool_calls is not None and executed_tool_calls >= remaining_tool_calls:
            limit_reached = True
            break
        tool_call_id = str(tool_call.get("id", f"call-{index}"))
        tool_name = str(tool_call.get("name", ""))
        arguments = tool_call.get("arguments", {})
        is_error = False
        tool_result: AgentToolResult

        try:
            tool = next((candidate for candidate in tools if getattr(candidate, "name", None) == tool_name), None)
            if tool is None:
                raise RuntimeError(f"Tool {tool_name} not found")
            validated_args = _validate_tool_arguments(tool, arguments)
            emit({"type": "tool_execution_start", "toolCallId": tool_call_id, "toolName": tool_name, "args": validated_args})

            before_result = None
            if config.before_tool_call is not None:
                before_result = config.before_tool_call(
                    {
                        "assistantMessage": assistant_message,
                        "toolCall": tool_call,
                        "args": validated_args,
                        "context": current_context,
                    },
                    signal,
                )
            if isinstance(before_result, dict) and before_result.get("block"):
                raise RuntimeError(str(before_result.get("reason") or "Tool execution was blocked"))

            def on_update(partial: AgentToolResult) -> None:
                emit(
                    {
                        "type": "tool_execution_update",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "args": validated_args,
                        "partialResult": partial,
                    }
                )

            tool_result = tool.execute(tool_call_id, validated_args, signal, on_update)
            _throw_if_aborted(signal)
        except Exception as exc:  # noqa: BLE001
            tool_result = AgentToolResult(content=[text_block(str(exc))], details={})
            is_error = True

        if config.after_tool_call is not None:
            after_result = config.after_tool_call(
                {
                    "assistantMessage": assistant_message,
                    "toolCall": tool_call,
                    "args": validated_args if "validated_args" in locals() else arguments,
                    "result": tool_result,
                    "isError": is_error,
                    "context": current_context,
                },
                signal,
            )
            if isinstance(after_result, dict):
                if "content" in after_result:
                    tool_result = AgentToolResult(content=list(after_result["content"]), details=tool_result.details)
                if "details" in after_result:
                    tool_result = AgentToolResult(content=tool_result.content, details=after_result["details"])
                if "isError" in after_result:
                    is_error = bool(after_result["isError"])

        emit(
            {
                "type": "tool_execution_end",
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "result": tool_result,
                "isError": is_error,
            }
        )

        message = ToolResultMessage(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=tool_result.content,
            details=tool_result.details,
            is_error=is_error,
            timestamp=int(time() * 1000),
        )
        results.append(message)
        emit({"type": "message_start", "message": message})
        emit({"type": "message_end", "message": message})

        multimodal_context_message = None
        if _should_inject_multimodal_tool_context(config):
            multimodal_context_message = _build_multimodal_tool_context_message(tool_name, tool_result)
        if multimodal_context_message is not None:
            tool_context_messages.append(multimodal_context_message)
            emit({"type": "message_start", "message": multimodal_context_message})
            emit({"type": "message_end", "message": multimodal_context_message})

        if get_steering_messages is not None:
            steering = get_steering_messages()
            if steering:
                steering_messages = steering
                remaining = tool_calls[index + 1 :]
                for skipped in remaining:
                    results.append(_skip_tool_call(skipped, emit))
                break
        executed_tool_calls += 1

    output = {
        "tool_results": results,
        "tool_context_messages": tool_context_messages,
        "executed_tool_calls": executed_tool_calls,
        "limit_reached": limit_reached,
    }
    if steering_messages:
        output["steering_messages"] = steering_messages
    return output


def _skip_tool_call(tool_call: dict[str, Any], emit: Callable[[AgentEvent], None]) -> ToolResultMessage:
    skipped_call_id = str(tool_call.get("id", "skipped"))
    skipped_name = str(tool_call.get("name", ""))
    skipped_args = tool_call.get("arguments", {})
    skip_result = AgentToolResult(content=[text_block("Skipped due to queued user message.")], details={})
    emit(
        {
            "type": "tool_execution_start",
            "toolCallId": skipped_call_id,
            "toolName": skipped_name,
            "args": skipped_args,
        }
    )
    emit(
        {
            "type": "tool_execution_end",
            "toolCallId": skipped_call_id,
            "toolName": skipped_name,
            "result": skip_result,
            "isError": True,
        }
    )
    skipped_message = ToolResultMessage(
        tool_call_id=skipped_call_id,
        tool_name=skipped_name,
        content=skip_result.content,
        details=skip_result.details,
        is_error=True,
        timestamp=int(time() * 1000),
    )
    emit({"type": "message_start", "message": skipped_message})
    emit({"type": "message_end", "message": skipped_message})
    return skipped_message


def _validate_tool_arguments(tool: AgentTool, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise RuntimeError("Tool arguments must be an object")

    schema = getattr(tool, "parameters", None)
    if not isinstance(schema, dict):
        return arguments

    required = schema.get("required", [])
    if isinstance(required, list):
        for key in required:
            if key not in arguments:
                raise RuntimeError(f"Missing required tool argument: {key}")

    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for key, value in arguments.items():
            spec = properties.get(key)
            if isinstance(spec, dict) and not _matches_schema_type(value, spec.get("type")):
                raise RuntimeError(f"Invalid type for tool argument: {key}")

    return arguments


def _matches_schema_type(value: Any, expected_type: Any) -> bool:
    if expected_type in (None, "any"):
        return True
    if isinstance(expected_type, list):
        return any(_matches_schema_type(value, item) for item in expected_type)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True


def _build_multimodal_tool_context_message(tool_name: str, tool_result: AgentToolResult) -> UserMessage | None:
    images: list[dict[str, Any]] = []
    text_lines: list[str] = []

    for block in tool_result.content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "image":
            data = block.get("data")
            if data:
                images.append(
                    {
                        "type": "image",
                        "data": str(data),
                        "mimeType": str(block.get("mimeType") or block.get("mime_type") or "image/png"),
                    }
                )
        elif block_type == "text":
            text = str(block.get("text", "")).strip()
            if text:
                text_lines.append(text)

    if not images:
        return None

    details = tool_result.details if isinstance(tool_result.details, dict) else {}
    path = details.get("path") if isinstance(details, dict) else None
    note = f"Tool `{tool_name}` produced image content. Use it as multimodal context for the next response."
    if isinstance(path, str) and path:
        note += f"\nImage path: {path}"
    if text_lines:
        note += "\n" + "\n".join(text_lines)

    return UserMessage(content=[text_block(note), *images], timestamp=int(time() * 1000))


def _should_inject_multimodal_tool_context(config: AgentLoopConfig) -> bool:
    return config.model.api not in {"anthropic-messages"}


def _emit_limit_checkpoint(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], None],
    signal: AbortSignal | None,
    *,
    reason: str,
    turn_count: int,
    tool_call_count: int,
) -> AssistantMessage:
    emit({"type": "turn_start"})
    checkpoint_prompt = UserMessage(
        content=[
            text_block(
                f"{reason}\n"
                f"Turns completed: {turn_count}\n"
                f"Tool calls executed: {tool_call_count}\n"
                "Briefly summarize the current progress, mention the limit that was reached, and ask the user whether to continue. "
                "Do not call tools."
            )
        ],
        timestamp=int(time() * 1000),
    )
    checkpoint_context = AgentContext(
        system_prompt=current_context.system_prompt,
        messages=[*current_context.messages, checkpoint_prompt],
        tools=[],
    )
    assistant = _stream_once(checkpoint_context, config, emit, signal)
    current_context.messages.append(assistant)
    new_messages.append(assistant)
    return assistant


def _throw_if_aborted(signal: AbortSignal | None) -> None:
    if signal is not None:
        signal.throw_if_aborted()
