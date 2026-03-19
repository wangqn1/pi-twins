# Browser And Screenshot Recipes

Load this file when the task needs concrete AppleScript for Safari, Chrome, screenshot capture, or screenshot-to-model workflows.

## Safari

```applescript
tell application "Safari"
  activate
  if (count of windows) = 0 then make new document
  set URL of front document to "https://example.com"
end tell
```

Open a new tab:

```applescript
tell application "Safari"
  activate
  tell window 1 to make new tab with properties {URL:"https://example.com"}
end tell
```

Reload front tab:

```applescript
tell application "Safari"
  activate
  do JavaScript "location.reload();" in front document
end tell
```

## Google Chrome

```applescript
tell application "Google Chrome"
  activate
  if (count of windows) = 0 then make new window
  set URL of active tab of front window to "https://example.com"
end tell
```

Open a new tab:

```applescript
tell application "Google Chrome"
  activate
  tell front window to make new tab with properties {URL:"https://example.com"}
end tell
```

Reload active tab:

```applescript
tell application "Google Chrome"
  activate
  reload active tab of front window
end tell
```

## Screenshot Commands

Full screen to file:

```bash
screencapture -x /tmp/browser-shot.png
```

Interactive selection:

```bash
screencapture -i /tmp/selection.png
```

Clipboard instead of file:

```bash
screencapture -c
```

Save to workspace for later model input:

```bash
screencapture -x /Users/wqn/project/python/pi-twin/tmp/browser-shot.png
```

Basic validation:

```bash
test -f /Users/wqn/project/python/pi-twin/tmp/browser-shot.png
```

## Browser keystrokes via System Events

Reload current tab:

```applescript
tell application "System Events"
  keystroke "r" using command down
end tell
```

Focus address bar:

```applescript
tell application "System Events"
  keystroke "l" using command down
end tell
```

Open a new tab:

```applescript
tell application "System Events"
  keystroke "t" using command down
end tell
```

## Targeting a browser process

```applescript
tell application "System Events"
  tell process "Safari"
    set frontmost to true
  end tell
end tell
```

## Common blockers

- Accessibility permission missing for `System Events`
- Screen Recording permission missing for `screencapture`
- Current runtime does not support sending local images to the active model
- App name mismatch, for example `Google Chrome` vs `Chrome`
- UI element names differ across macOS versions and languages
- Target window or tab does not exist yet
