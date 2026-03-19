---
name: mac-app-control
description: Control macOS browsers, especially Safari and Google Chrome, capture screenshots, and pass screenshots to a multimodal model for visual understanding. Use when the user wants the agent to open URLs, switch tabs, reload pages, activate browser windows, take screenshots, or ask the model to analyze what is shown on screen on a Mac.
---

# Mac App Control

Use this skill when the user wants the agent to operate a browser on macOS, capture screenshots, and have a multimodal model interpret those screenshots.

## Rules

- Browser automation and screenshots require running commands outside the sandbox. Request escalation before using `open`, `osascript`, `screencapture`, or other GUI automation commands.
- Only use the screenshot-to-model path when the active runtime can send image inputs to the model. If image input is unavailable, say so clearly and fall back to saving the screenshot only.
- Prefer the least invasive action first:
  1. `open` or `open -a` to launch a browser or URL
  2. `osascript` targeting Safari or Google Chrome directly
  3. `screencapture` for screenshots
  4. send the screenshot as an image input to the multimodal model
  5. `osascript` with `System Events` only when UI scripting is necessary
- Before destructive or sensitive actions, get explicit confirmation:
  - submitting forms
  - clicking purchase, delete, send, publish, or confirm buttons
  - logging in, logging out, or modifying account settings
  - interacting with passwords, payments, security prompts, or account data
- If screenshots fail, tell the user that Screen Recording permission may be required.
- If UI scripting is blocked, tell the user that macOS Accessibility permission may be required for Terminal or the host app.

## Workflow

1. Restate the exact browser, screenshot, or visual analysis action to perform.
2. Choose the narrowest command path.
3. Request escalation for the command.
4. If visual understanding is requested, capture to a deterministic file path.
5. Send the image to the multimodal model when supported.
6. Report what succeeded, what the model inferred, and any next step.

## Command Patterns

### Launch or focus a browser

```bash
open -a "Safari"
```

```bash
open -a "Google Chrome"
```

```bash
osascript -e 'tell application "Safari" to activate'
```

### Open a URL

```bash
open "https://example.com"
```

### Tell the browser to do something directly

```bash
osascript -e 'tell application "Safari" to activate'
```

Read [references/applescript-recipes.md](references/applescript-recipes.md) for Safari and Chrome examples before writing longer AppleScript.

### Take a screenshot

Save to a file inside the workspace or `/tmp`.

```bash
screencapture -x /tmp/browser-shot.png
```

Capture a specific window interactively:

```bash
screencapture -i /tmp/browser-window.png
```

Use `-x` to suppress the shutter sound. Prefer explicit output paths.

### Send screenshot to the model

If the runtime supports multimodal prompts, use the saved screenshot as an image input in the next model turn. Prefer this sequence:

1. capture screenshot to a known file
2. verify the file exists
3. send the image with a short task prompt such as:
   - "Describe the current browser page"
   - "Extract the visible error message"
   - "Tell me which button is most likely the submit button"

If image input is not supported in the current runtime, stop after saving the screenshot and tell the user what is missing.

### UI scripting through System Events

Use only if direct app scripting is insufficient.

```bash
osascript -e 'tell application "System Events" to keystroke "l" using command down'
```

```bash
osascript -e 'tell application "System Events" to keystroke "r" using command down'
```

## Safety Limits

- Do not claim screen state you cannot verify from command results.
- When the model analyzes a screenshot, label conclusions as screen-based observations, not guaranteed facts about the underlying app state.
- Do not click through confirmations, purchases, or sends without a clear user instruction.
- Do not handle login flows, MFA codes, passwords, or security approvals autonomously.
- If the user asks for broad desktop control, break it into explicit sub-steps and confirm sensitive ones.

## Typical Requests

- “Open Safari and go to a URL.”
- “Open Chrome and switch to the tab with this site.”
- “Reload the current page.”
- “Take a screenshot of the browser window.”
- “Open this page and save a screenshot to `/tmp`.”
- “Open this page, screenshot it, and tell me what the model sees.”
- “Capture the browser and extract the visible error text.”

## Response Style

- Say what command path you are using.
- If escalation is needed, request it immediately instead of describing the command abstractly.
- After each step, report the visible outcome and any blocker.
- If you used image understanding, distinguish:
  - command result
  - screenshot path
  - model interpretation
