import "@mariozechner/mini-lit/dist/ThemeToggle.js";
import { html, render } from "lit";
import { ChatPanel } from "@upstream-web-ui/ChatPanel";
import { AppStorage, setAppStorage } from "@upstream-web-ui/storage/app-storage";
import { IndexedDBStorageBackend } from "@upstream-web-ui/storage/backends/indexeddb-storage-backend";
import { CustomProvidersStore } from "@upstream-web-ui/storage/stores/custom-providers-store";
import { ProviderKeysStore } from "@upstream-web-ui/storage/stores/provider-keys-store";
import { SessionsStore } from "@upstream-web-ui/storage/stores/sessions-store";
import { SettingsStore } from "@upstream-web-ui/storage/stores/settings-store";
import "./app.css";
import { PythonAgent } from "./python-agent";

const MANAGED_PROVIDER_KEY = "managed-by-python";
const apiBaseUrl = `${window.location.origin}/api`;

const settings = new SettingsStore();
const providerKeys = new ProviderKeysStore();
const sessions = new SessionsStore();
const customProviders = new CustomProvidersStore();

const backend = new IndexedDBStorageBackend({
  dbName: "py-twins-web-ui",
  version: 1,
  stores: [
    settings.getConfig(),
    SessionsStore.getMetadataConfig(),
    providerKeys.getConfig(),
    customProviders.getConfig(),
    sessions.getConfig()
  ]
});

settings.setBackend(backend);
providerKeys.setBackend(backend);
customProviders.setBackend(backend);
sessions.setBackend(backend);
setAppStorage(new AppStorage(settings, providerKeys, sessions, customProviders, backend));

let connectionState: "connecting" | "connected" | "error" = "connecting";
let connectionError = "";
let exportPath = "";
let busy = false;
let agent: PythonAgent | null = null;
let chatPanel: ChatPanel | null = null;
let shellRendered = false;

function shortId(value: string | null | undefined): string {
  if (!value) return "n/a";
  return value.length <= 10 ? value : value.slice(0, 8);
}

async function ensureProviderKey(provider?: string | null): Promise<void> {
  if (!provider) return;
  if (!(await providerKeys.has(provider))) {
    await providerKeys.set(provider, MANAGED_PROVIDER_KEY);
  }
}

async function clearStoredSessions(): Promise<void> {
  const metadata = await sessions.getAllMetadata();
  await Promise.all(metadata.map((entry: { id: string }) => sessions.deleteSession(entry.id)));
}

async function rebuildChatPanel(): Promise<void> {
  if (!agent) return;
  chatPanel = new ChatPanel();
  await chatPanel.setAgent(agent as any, {
    onApiKeyRequired: async (provider: string) => {
      await ensureProviderKey(provider);
      return true;
    }
  });
}

function renderApp(): void {
  const root = document.getElementById("app");
  if (!root) return;

  const modelLabel = agent?.state.model?.id || "n/a";
  const sessionLabel = shortId(agent?.sessionId);

  render(
    html`
      <div class="app-shell">
        <header class="app-header">
          <div class="app-title">
            <h1>py-twins web-ui</h1>
            <p>upstream <code>tools/pi-mono/packages/web-ui</code> connected to the local Python engine</p>
            <div class="status-row">
              <span class="status-pill ${connectionState}">${connectionState}</span>
              <span class="status-pill">session ${sessionLabel}</span>
              <span class="status-pill">model ${modelLabel}</span>
              ${agent?.sessionTitle ? html`<span class="status-pill">${agent.sessionTitle}</span>` : ""}
              ${connectionError ? html`<span class="status-pill error">${connectionError}</span>` : ""}
              ${exportPath ? html`<span class="status-pill">exported ${exportPath}</span>` : ""}
            </div>
          </div>
          <div class="header-actions">
            <button class="action-button" ?disabled=${busy || !agent} @click=${() => void reloadSession()}>Reload</button>
            <button class="action-button" ?disabled=${busy || !agent} @click=${() => void newSession()}>New Session</button>
            <button class="action-button" ?disabled=${busy || !agent} @click=${() => void exportSession()}>Export HTML</button>
          </div>
        </header>
        <main class="panel-wrap">
          <div class="panel-card">
            <div id="panel-host" class="panel-host"></div>
            ${!chatPanel ? html`<div class="panel-fallback">Connecting…</div>` : ""}
          </div>
        </main>
        <div class="footer-note">
          client-side API keys are bypassed; model access is handled by the Python backend configured for this project.
        </div>
      </div>
    `,
    root
  );
  shellRendered = true;
  mountChatPanel();
}

function mountChatPanel(): void {
  if (!shellRendered || !chatPanel) return;
  const host = document.getElementById("panel-host");
  if (!host) return;
  if (chatPanel.parentElement !== host) {
    host.replaceChildren(chatPanel);
    chatPanel.style.display = "flex";
    chatPanel.style.width = "100%";
    chatPanel.style.height = "100%";
  }
}

function focusComposer(): void {
  requestAnimationFrame(() => {
    const textarea = document.querySelector("message-editor textarea") as HTMLTextAreaElement | null;
    textarea?.focus();
  });
}

async function withBusy<T>(fn: () => Promise<T>): Promise<T | undefined> {
  busy = true;
  renderApp();
  try {
    return await fn();
  } finally {
    busy = false;
    renderApp();
  }
}

async function reloadSession(): Promise<void> {
  if (!agent) return;
  exportPath = "";
  await withBusy(async () => {
    await agent!.reloadSession();
    await ensureProviderKey(agent!.state.model?.provider);
    await clearStoredSessions();
    await rebuildChatPanel();
  });
}

async function newSession(): Promise<void> {
  if (!agent) return;
  exportPath = "";
  await withBusy(async () => {
    await agent!.newSession();
    await ensureProviderKey(agent!.state.model?.provider);
    await clearStoredSessions();
    await rebuildChatPanel();
  });
}

async function exportSession(): Promise<void> {
  if (!agent) return;
  await withBusy(async () => {
    const result = await agent!.exportHtml();
    exportPath = result.path;
  });
}

async function bootstrap(): Promise<void> {
  renderApp();
  try {
    agent = new PythonAgent(apiBaseUrl);
    await agent.refreshState();
    await ensureProviderKey(agent.state.model?.provider);
    agent.subscribe(() => {
      renderApp();
    });
    await clearStoredSessions();
    await rebuildChatPanel();

    connectionState = "connected";
    renderApp();
    focusComposer();
  } catch (error) {
    connectionState = "error";
    connectionError = error instanceof Error ? error.message : String(error);
    renderApp();
  }
}

void bootstrap();
