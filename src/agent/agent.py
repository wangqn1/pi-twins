# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from copy import deepcopy
from threading import Event, RLock
from time import time
from typing import Any, Callable

from ai import (
    AssistantMessage,
    AssistantMessageEventStream,
    CompleteOptions,
    EchoBackend,
    emit_assistant_message_events,
    Message,
    Model,
    SimpleStreamOptions,
    Usage,
    UserMessage,
    text_block,
)

from .loop import agent_loop, agent_loop_continue
from .types import (
    AbortController,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentState,
    AgentTool,
    AfterToolCall,
    BeforeToolCall,
    StreamFn,
    ThinkingLevel,
)


def default_convert_to_llm(messages: list[AgentMessage]) -> list[Message]:
    return [message for message in messages if getattr(message, "role", None) in {"user", "assistant", "toolResult"}]


def _backend_stream_fn(backend: Any) -> StreamFn:
    def stream_fn(model: Model, context, options: SimpleStreamOptions | None = None) -> AssistantMessageEventStream:  # noqa: ANN001
        stream = AssistantMessageEventStream()
        try:
            complete_options = CompleteOptions(
                reasoning=options.reasoning if options is not None else None,
                api_key=options.api_key if options is not None else None,
                session_id=options.session_id if options is not None else None,
            )
            message = backend.complete(model, context, complete_options)
            partial = AssistantMessage(
                content=[],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="stop",
                timestamp=int(time() * 1000),
            )
            emit_assistant_message_events(stream, partial, message)
        except Exception as exc:  # noqa: BLE001
            error_message = AssistantMessage(
                content=[],
                api=model.api,
                provider=model.provider,
                model=model.id,
                usage=Usage(),
                stop_reason="aborted" if options is not None and getattr(options.signal, "aborted", False) else "error",
                error_message=str(exc),
                timestamp=int(time() * 1000),
            )
            stream.push({"type": "start", "partial": error_message})
            stream.push({"type": "error", "reason": error_message.stop_reason, "error": error_message})
            stream.end(error_message)
        return stream

    return stream_fn


class Agent:
    def __init__(
        self,
        *,
        initial_state: AgentState | None = None,
        convert_to_llm: Callable[[list[AgentMessage]], list[Message]] | None = None,
        transform_context: Callable[[list[AgentMessage], object], list[AgentMessage]] | None = None,
        steering_mode: str = "one-at-a-time",
        follow_up_mode: str = "one-at-a-time",
        backend: EchoBackend | None = None,
        stream_fn: StreamFn | None = None,
        session_id: str | None = None,
        get_api_key: Callable[[str], str | None] | None = None,
        on_payload: Callable[[Any, Model], Any | None] | None = None,
        thinking_budgets: dict[str, int] | None = None,
        transport: str = "sse",
        max_retry_delay_ms: int | None = None,
        max_turns: int | None = 12,
        max_tool_calls: int | None = 32,
        options: SimpleStreamOptions | None = None,
    ) -> None:
        default_model = Model(provider="mock", id="echo")
        self._state = initial_state or AgentState(
            system_prompt="",
            model=default_model,
            thinking_level="off",
            tools=[],
            messages=[],
        )
        self._convert_to_llm = convert_to_llm or default_convert_to_llm
        self._transform_context = transform_context
        self._steering_mode = steering_mode
        self._follow_up_mode = follow_up_mode
        self._backend = backend or EchoBackend()
        self._stream_fn = stream_fn or _backend_stream_fn(self._backend)
        self._get_api_key = get_api_key
        self._on_payload = on_payload
        self._thinking_budgets = dict(thinking_budgets or {})
        self._transport = transport
        self._max_retry_delay_ms = max_retry_delay_ms
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls
        self._before_tool_call: BeforeToolCall | None = None
        self._after_tool_call: AfterToolCall | None = None
        self._options = options or SimpleStreamOptions()
        self._listeners: set[Callable[[AgentEvent], None]] = set()
        self._steering_queue: list[AgentMessage] = []
        self._follow_up_queue: list[AgentMessage] = []
        self._session_id: str | None = session_id
        self._abort_controller: AbortController | None = None
        self._idle_event = Event()
        self._idle_event.set()
        self._lock = RLock()

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    @property
    def sessionId(self) -> str | None:
        return self.session_id

    @sessionId.setter
    def sessionId(self, value: str | None) -> None:
        self.session_id = value

    @property
    def thinking_budgets(self) -> dict[str, int]:
        return dict(self._thinking_budgets)

    @thinking_budgets.setter
    def thinking_budgets(self, value: dict[str, int] | None) -> None:
        self._thinking_budgets = dict(value or {})

    @property
    def thinkingBudgets(self) -> dict[str, int]:
        return self.thinking_budgets

    @thinkingBudgets.setter
    def thinkingBudgets(self, value: dict[str, int] | None) -> None:
        self.thinking_budgets = value

    @property
    def transport(self) -> str:
        return self._transport

    @property
    def max_retry_delay_ms(self) -> int | None:
        return self._max_retry_delay_ms

    @max_retry_delay_ms.setter
    def max_retry_delay_ms(self, value: int | None) -> None:
        self._max_retry_delay_ms = value

    @property
    def maxRetryDelayMs(self) -> int | None:
        return self.max_retry_delay_ms

    @maxRetryDelayMs.setter
    def maxRetryDelayMs(self, value: int | None) -> None:
        self.max_retry_delay_ms = value

    @property
    def max_turns(self) -> int | None:
        return self._max_turns

    @max_turns.setter
    def max_turns(self, value: int | None) -> None:
        self._max_turns = value

    @property
    def maxTurns(self) -> int | None:
        return self.max_turns

    @maxTurns.setter
    def maxTurns(self, value: int | None) -> None:
        self.max_turns = value

    @property
    def max_tool_calls(self) -> int | None:
        return self._max_tool_calls

    @max_tool_calls.setter
    def max_tool_calls(self, value: int | None) -> None:
        self._max_tool_calls = value

    @property
    def maxToolCalls(self) -> int | None:
        return self.max_tool_calls

    @maxToolCalls.setter
    def maxToolCalls(self, value: int | None) -> None:
        self.max_tool_calls = value

    @property
    def streamFn(self) -> StreamFn:
        return self._stream_fn

    @streamFn.setter
    def streamFn(self, value: StreamFn) -> None:
        self._stream_fn = value

    @property
    def getApiKey(self) -> Callable[[str], str | None] | None:
        return self._get_api_key

    @getApiKey.setter
    def getApiKey(self, value: Callable[[str], str | None] | None) -> None:
        self._get_api_key = value

    @property
    def onPayload(self) -> Callable[[Any, Model], Any | None] | None:
        return self._on_payload

    @onPayload.setter
    def onPayload(self, value: Callable[[Any, Model], Any | None] | None) -> None:
        self._on_payload = value

    def set_transport(self, value: str) -> None:
        self._transport = value

    def setTransport(self, value: str) -> None:
        self.set_transport(value)

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    def _emit(self, event: AgentEvent) -> None:
        for listener in list(self._listeners):
            listener(event)
        if event["type"] == "message_end":
            self._state.messages.append(event["message"])
            self._state.stream_message = None
        elif event["type"] in {"message_start", "message_update"}:
            self._state.stream_message = event["message"]
        elif event["type"] == "tool_execution_start":
            self._state.pending_tool_calls.add(event["toolCallId"])
        elif event["type"] == "tool_execution_end":
            self._state.pending_tool_calls.discard(event["toolCallId"])
        elif event["type"] == "turn_end":
            message = event["message"]
            if isinstance(message, AssistantMessage) and message.error_message:
                self._state.error = message.error_message
        elif event["type"] == "agent_end":
            self._state.is_streaming = False
            self._state.stream_message = None

    def set_system_prompt(self, prompt: str) -> None:
        self._state.system_prompt = prompt

    def setSystemPrompt(self, prompt: str) -> None:
        self.set_system_prompt(prompt)

    def set_model(self, model: Model) -> None:
        self._state.model = model

    def setModel(self, model: Model) -> None:
        self.set_model(model)

    def set_thinking_level(self, level: ThinkingLevel) -> None:
        self._state.thinking_level = level

    def setThinkingLevel(self, level: ThinkingLevel) -> None:
        self.set_thinking_level(level)

    def set_tools(self, tools: list[AgentTool]) -> None:
        self._state.tools = tools

    def setTools(self, tools: list[AgentTool]) -> None:
        self.set_tools(tools)

    def set_before_tool_call(self, hook: BeforeToolCall | None) -> None:
        self._before_tool_call = hook

    def setBeforeToolCall(self, hook: BeforeToolCall | None) -> None:
        self.set_before_tool_call(hook)

    def set_after_tool_call(self, hook: AfterToolCall | None) -> None:
        self._after_tool_call = hook

    def setAfterToolCall(self, hook: AfterToolCall | None) -> None:
        self.set_after_tool_call(hook)

    def replace_messages(self, messages: list[AgentMessage]) -> None:
        self._state.messages = list(messages)

    def replaceMessages(self, messages: list[AgentMessage]) -> None:
        self.replace_messages(messages)

    def append_message(self, message: AgentMessage) -> None:
        self._state.messages.append(message)

    def appendMessage(self, message: AgentMessage) -> None:
        self.append_message(message)

    def clear_messages(self) -> None:
        self._state.messages = []

    def clearMessages(self) -> None:
        self.clear_messages()

    def set_steering_mode(self, mode: str) -> None:
        self._steering_mode = mode

    def setSteeringMode(self, mode: str) -> None:
        self.set_steering_mode(mode)

    def get_steering_mode(self) -> str:
        return self._steering_mode

    def getSteeringMode(self) -> str:
        return self.get_steering_mode()

    def set_follow_up_mode(self, mode: str) -> None:
        self._follow_up_mode = mode

    def setFollowUpMode(self, mode: str) -> None:
        self.set_follow_up_mode(mode)

    def get_follow_up_mode(self) -> str:
        return self._follow_up_mode

    def getFollowUpMode(self) -> str:
        return self.get_follow_up_mode()

    def steer(self, message: AgentMessage) -> None:
        self._steering_queue.append(message)

    def follow_up(self, message: AgentMessage) -> None:
        self._follow_up_queue.append(message)

    def followUp(self, message: AgentMessage) -> None:
        self.follow_up(message)

    def clear_steering_queue(self) -> None:
        self._steering_queue = []

    def clearSteeringQueue(self) -> None:
        self.clear_steering_queue()

    def clear_follow_up_queue(self) -> None:
        self._follow_up_queue = []

    def clearFollowUpQueue(self) -> None:
        self.clear_follow_up_queue()

    def clear_all_queues(self) -> None:
        self.clear_steering_queue()
        self.clear_follow_up_queue()

    def clearAllQueues(self) -> None:
        self.clear_all_queues()

    def has_queued_messages(self) -> bool:
        return bool(self._steering_queue or self._follow_up_queue)

    def hasQueuedMessages(self) -> bool:
        return self.has_queued_messages()

    def _dequeue_steering_messages(self) -> list[AgentMessage]:
        if self._steering_mode == "one-at-a-time":
            if not self._steering_queue:
                return []
            return [self._steering_queue.pop(0)]
        queued = list(self._steering_queue)
        self._steering_queue = []
        return queued

    def _dequeue_follow_up_messages(self) -> list[AgentMessage]:
        if self._follow_up_mode == "one-at-a-time":
            if not self._follow_up_queue:
                return []
            return [self._follow_up_queue.pop(0)]
        queued = list(self._follow_up_queue)
        self._follow_up_queue = []
        return queued

    def _build_loop_config(self) -> AgentLoopConfig:
        reasoning = None if self._state.thinking_level == "off" else self._state.thinking_level
        options = deepcopy(self._options)
        options.reasoning = reasoning
        options.session_id = self._session_id
        options.on_payload = self._on_payload
        options.transport = self._transport  # type: ignore[assignment]
        options.thinking_budgets = dict(self._thinking_budgets)
        options.max_retry_delay_ms = self._max_retry_delay_ms
        return AgentLoopConfig(
            model=self._state.model,
            convert_to_llm=self._convert_to_llm,
            stream_fn=self._stream_fn,
            transform_context=self._transform_context,
            get_api_key=self._get_api_key,
            get_steering_messages=self._dequeue_steering_messages,
            get_follow_up_messages=self._dequeue_follow_up_messages,
            before_tool_call=self._before_tool_call,
            after_tool_call=self._after_tool_call,
            options=options,
            max_turns=self._max_turns,
            max_tool_calls=self._max_tool_calls,
        )

    def prompt(
        self,
        input_message: str | AgentMessage | list[AgentMessage],
        images: list[dict[str, Any]] | None = None,
    ) -> None:
        if isinstance(input_message, str):
            content = [text_block(input_message)]
            if images:
                content.extend(images)
            prompts: list[AgentMessage] = [UserMessage(content=content, timestamp=int(time() * 1000))]
        elif isinstance(input_message, list):
            prompts = input_message
        else:
            prompts = [input_message]
        self._run_loop(prompts=prompts)

    def continue_run(self) -> None:
        if self._state.messages and getattr(self._state.messages[-1], "role", None) == "assistant":
            queued_steering = self._dequeue_steering_messages()
            if queued_steering:
                self._run_loop(prompts=queued_steering, skip_initial_steering_poll=True)
                return
            queued_follow_up = self._dequeue_follow_up_messages()
            if queued_follow_up:
                self._run_loop(prompts=queued_follow_up)
                return
        self._run_loop(prompts=None)

    def continueRun(self) -> None:
        self.continue_run()

    def continue_(self) -> None:
        self.continue_run()

    def wait_for_idle(self, timeout: float | None = None) -> None:
        self._idle_event.wait(timeout)

    def waitForIdle(self, timeout: float | None = None) -> None:
        self.wait_for_idle(timeout)

    def abort(self) -> None:
        if self._abort_controller is not None:
            self._abort_controller.abort()
        self._state.is_streaming = False

    def reset(self) -> None:
        self._state.messages = []
        self._state.stream_message = None
        self._state.pending_tool_calls = set()
        self._state.error = None
        self._state.is_streaming = False
        self._steering_queue = []
        self._follow_up_queue = []

    def _run_loop(self, *, prompts: list[AgentMessage] | None, skip_initial_steering_poll: bool = False) -> None:
        with self._lock:
            if self._state.is_streaming:
                raise RuntimeError("Agent is already processing a prompt")
            self._state.is_streaming = True
            self._state.error = None
            self._state.stream_message = None
            self._state.pending_tool_calls = set()
            self._abort_controller = AbortController()
            self._idle_event.clear()

        context = AgentContext(
            system_prompt=self._state.system_prompt,
            messages=list(self._state.messages),
            tools=list(self._state.tools),
        )
        config = self._build_loop_config()

        if skip_initial_steering_poll:
            steering_messages = self._dequeue_steering_messages
            skipped = {"done": False}

            def wrapped() -> list[AgentMessage]:
                if not skipped["done"]:
                    skipped["done"] = True
                    return []
                return steering_messages()

            config.get_steering_messages = wrapped

        try:
            if prompts is not None:
                agent_loop(prompts, context, config, self._emit, self._abort_controller.signal)
            else:
                agent_loop_continue(context, config, self._emit, self._abort_controller.signal)
        except Exception as err:  # noqa: BLE001
            error_msg = AssistantMessage(
                content=[text_block("")],
                api=self._state.model.api,
                provider=self._state.model.provider,
                model=self._state.model.id,
                usage=Usage(),
                stop_reason="aborted" if self._abort_controller.signal.aborted else "error",
                error_message=str(err),
                timestamp=int(time() * 1000),
            )
            self.append_message(error_msg)
            self._state.error = str(err)
            self._emit({"type": "agent_end", "messages": [error_msg]})
        finally:
            self._state.is_streaming = False
            self._state.stream_message = None
            self._state.pending_tool_calls = set()
            self._abort_controller = None
            self._idle_event.set()
