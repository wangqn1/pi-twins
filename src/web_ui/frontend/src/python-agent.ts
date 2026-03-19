export interface BridgeModel {
  provider: string;
  id: string;
  name?: string;
  api?: string;
  baseUrl?: string;
  reasoning?: boolean;
  contextWindow?: number;
  maxTokens?: number;
  input?: string[];
  headers?: Record<string, string>;
}

export interface BridgeState {
  model: BridgeModel | null;
  thinkingLevel: string;
  messages: any[];
  tools: any[];
  isStreaming: boolean;
  streamMessage: any | null;
  pendingToolCalls: string[];
  error?: string | null;
  sessionId?: string | null;
  sessionFile?: string | null;
  sessionTitle?: string | null;
  cwd?: string | null;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
}

function mergeTools(backendTools: any[], uiTools: any[]): any[] {
  const merged = new Map<string, any>();
  for (const tool of backendTools) {
    if (tool?.name) merged.set(String(tool.name), tool);
  }
  for (const tool of uiTools) {
    if (!tool?.name) continue;
    const name = String(tool.name);
    const existing = merged.get(name);
    merged.set(name, existing ? { ...existing, ...tool } : tool);
  }
  return Array.from(merged.values());
}

export class PythonAgent {
  apiBaseUrl: string;
  state: any;
  streamFn: unknown;
  getApiKey?: (provider: string) => Promise<string | undefined>;
  sessionId: string | null;
  sessionFile: string | null;
  sessionTitle: string | null;
  cwd: string | null;

  private listeners = new Set<(event: any) => void>();
  private backendTools: any[] = [];
  private uiTools: any[] = [];

  constructor(apiBaseUrl: string) {
    this.apiBaseUrl = apiBaseUrl.replace(/\/$/, "");
    this.streamFn = async () => undefined;
    this.sessionId = null;
    this.sessionFile = null;
    this.sessionTitle = null;
    this.cwd = null;
    this.state = this.normalizeState({
      model: null,
      thinkingLevel: "off",
      messages: [],
      tools: [],
      isStreaming: false,
      streamMessage: null,
      pendingToolCalls: []
    });
  }

  subscribe(listener: (event: any) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  async refreshState(): Promise<any> {
    const response = await this.request("/state");
    this.applyState(response.state);
    this.emit({ type: "state-update", state: this.state });
    return this.state;
  }

  async prompt(message: string | Record<string, unknown> | unknown[]): Promise<void> {
    this.state.isStreaming = true;
    this.emit({ type: "agent_start" });
    this.emit({ type: "state-update", state: this.state });

    const response = await fetch(`${this.apiBaseUrl}/prompt/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ message })
    });
    if (!response.ok || !response.body) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex >= 0) {
        const line = buffer.slice(0, newlineIndex).trim();
        buffer = buffer.slice(newlineIndex + 1);
        if (line) {
          const payload = JSON.parse(line);
          if (payload.ok === false) {
            throw new Error(String(payload.error || "Stream request failed"));
          }
          if (payload.kind === "event") {
            const event = this.normalizeEvent(payload.event);
            this.applyEvent(event);
            this.emit(event);
            this.emit({ type: "state-update", state: this.state });
          } else if (payload.kind === "state") {
            this.applyState(payload.state);
            this.emit({ type: "state-update", state: this.state });
          } else if (payload.kind === "error") {
            throw new Error(String(payload.error || "Streaming failed"));
          }
        }
        newlineIndex = buffer.indexOf("\n");
      }
      if (done) {
        break;
      }
    }
  }

  async abort(): Promise<void> {
    const response = await this.request("/abort", { method: "POST", body: {} });
    this.applyState(response.state);
    this.emit({ type: "agent_end" });
    this.emit({ type: "state-update", state: this.state });
  }

  async setModel(model: BridgeModel): Promise<void> {
    const response = await this.request("/model", { method: "POST", body: model });
    this.applyState(response.state);
    this.emit({ type: "state-update", state: this.state });
  }

  async setThinkingLevel(level: string): Promise<void> {
    const response = await this.request("/thinking", { method: "POST", body: { level } });
    this.applyState(response.state);
    this.emit({ type: "state-update", state: this.state });
  }

  setTools(tools: any[]): void {
    this.uiTools = Array.isArray(tools) ? tools : [];
    this.state.tools = mergeTools(this.backendTools, this.uiTools);
    this.emit({ type: "state-update", state: this.state });
  }

  async newSession(): Promise<void> {
    const response = await this.request("/session/new", { method: "POST", body: {} });
    this.applyState(response.state);
    this.emit({ type: "state-update", state: this.state });
  }

  async reloadSession(): Promise<void> {
    const response = await this.request("/session/reload", { method: "POST", body: {} });
    this.applyState(response.state);
    this.emit({ type: "state-update", state: this.state });
  }

  async exportHtml(path?: string): Promise<{ path: string }> {
    const response = await this.request("/export", { method: "POST", body: { path } });
    return { path: String(response.path) };
  }

  private normalizeState(raw: BridgeState): any {
    return {
      systemPrompt: "",
      model: raw.model,
      thinkingLevel: raw.thinkingLevel || "off",
      messages: Array.isArray(raw.messages) ? raw.messages : [],
      tools: mergeTools(this.backendTools, this.uiTools),
      isStreaming: Boolean(raw.isStreaming),
      streamMessage: raw.streamMessage ?? null,
      pendingToolCalls: new Set(Array.isArray(raw.pendingToolCalls) ? raw.pendingToolCalls : []),
      error: raw.error ?? null
    };
  }

  private applyState(raw: BridgeState): void {
    this.backendTools = Array.isArray(raw.tools) ? raw.tools : [];
    this.state = this.normalizeState(raw);
    this.state.tools = mergeTools(this.backendTools, this.uiTools);
    this.sessionId = raw.sessionId ?? null;
    this.sessionFile = raw.sessionFile ?? null;
    this.sessionTitle = raw.sessionTitle ?? null;
    this.cwd = raw.cwd ?? null;
  }

  private normalizeEvent(event: any): any {
    if (event && typeof event === "object" && Array.isArray(event.pendingToolCalls)) {
      return { ...event, pendingToolCalls: new Set(event.pendingToolCalls) };
    }
    return event;
  }

  private applyEvent(event: any): void {
    const eventType = event?.type;
    if (eventType === "agent_start") {
      this.state.isStreaming = true;
      return;
    }
    if (eventType === "message_end") {
      this.state.messages = [...this.state.messages, event.message];
      this.state.streamMessage = null;
      return;
    }
    if (eventType === "message_start" || eventType === "message_update") {
      this.state.streamMessage = event.message;
      return;
    }
    if (eventType === "tool_execution_start") {
      const pending = new Set<string>(this.state.pendingToolCalls || new Set<string>());
      pending.add(String(event.toolCallId));
      this.state.pendingToolCalls = pending;
      return;
    }
    if (eventType === "tool_execution_end") {
      const pending = new Set<string>(this.state.pendingToolCalls || new Set<string>());
      pending.delete(String(event.toolCallId));
      this.state.pendingToolCalls = pending;
      return;
    }
    if (eventType === "turn_end" && event.message?.errorMessage) {
      this.state.error = event.message.errorMessage;
      return;
    }
    if (eventType === "agent_end") {
      this.state.isStreaming = false;
      this.state.streamMessage = null;
    }
  }

  private emit(event: any): void {
    for (const listener of Array.from(this.listeners)) {
      listener(event);
    }
  }

  private async request(path: string, options: RequestOptions = {}): Promise<any> {
    const response = await fetch(`${this.apiBaseUrl}${path}`, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json"
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(String(payload.error || `Request failed: ${response.status}`));
    }
    return payload;
  }
}
