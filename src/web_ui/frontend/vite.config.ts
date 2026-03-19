import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "../../../tools/pi-mono/node_modules/vite/dist/node/index.js";
import tailwindcss from "../../../tools/pi-mono/node_modules/@tailwindcss/vite/dist/index.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "../../..");
const monoRoot = path.resolve(projectRoot, "tools/pi-mono");
const monoNodeModules = path.resolve(monoRoot, "node_modules");

const alias = [
  { find: "@upstream-web-ui", replacement: path.resolve(monoRoot, "packages/web-ui/src") },
  { find: "@mariozechner/pi-ai", replacement: path.resolve(monoRoot, "packages/ai/src/index.ts") },
  { find: "@mariozechner/pi-agent-core", replacement: path.resolve(monoRoot, "packages/agent/src/index.ts") },
  { find: "@mariozechner/pi-tui", replacement: path.resolve(monoRoot, "packages/tui/src/index.ts") },
  { find: "@mariozechner/mini-lit", replacement: path.resolve(monoNodeModules, "@mariozechner/mini-lit") },
  { find: "ollama/browser", replacement: path.resolve(monoNodeModules, "ollama/dist/browser.mjs") },
  { find: "docx-preview", replacement: path.resolve(monoNodeModules, "docx-preview") },
  { find: "pdfjs-dist", replacement: path.resolve(monoNodeModules, "pdfjs-dist") },
  { find: "@lmstudio/sdk", replacement: path.resolve(monoNodeModules, "@lmstudio/sdk") },
  { find: "jszip", replacement: path.resolve(monoNodeModules, "jszip") },
  { find: "xlsx", replacement: path.resolve(monoNodeModules, "xlsx") },
  { find: "lucide", replacement: path.resolve(monoNodeModules, "lucide") },
  { find: "lit", replacement: path.resolve(monoNodeModules, "lit") },
  { find: "ollama", replacement: path.resolve(monoNodeModules, "ollama") }
];

export default defineConfig({
  root: __dirname,
  plugins: [tailwindcss()],
  resolve: { alias },
  server: {
    fs: {
      allow: [projectRoot, monoRoot, monoNodeModules]
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true
  }
});
