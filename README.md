# KDE/Codex/Claude Usage Probe

This workspace contains a Plasma widget plus two local diagnostic tools:

- `ai_usage_report.py` prints the current KDE panel widgets plus local Codex and Claude Code usage.
- `claude_statusline_capture.py` is an optional Claude Code status-line command that stores the latest Claude rate-limit payload in `~/.cache/ai-usage/claude-statusline.json`.
- `plasmoid/` is the KDE Plasma 6 applet package for `local.aiusage.rings`.

Run:

```bash
./ai_usage_report.py
./ai_usage_report.py --json
```

Codex usage comes from `~/.codex/state_5.sqlite` and `~/.codex/sessions/**/*.jsonl`. The Codex rollout JSONL includes account rate-limit percentages when Codex has received them.

Claude token usage comes from `~/.claude/projects/**/*.jsonl`. If `CLAUDE_SESSION_ID` is not set and no status-line cache exists, the reporter uses the latest logged Claude session rather than claiming an active foreground session. Claude Code subscription remaining percentages are only available while Claude is running, through the status-line JSON. To capture them, add this to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/wacket/Projects/KDEWidgetClaudeCodexUsage/claude_statusline_capture.py",
    "padding": 0,
    "refreshInterval": 600
  }
}
```

After the next Claude Code response, rerun `./ai_usage_report.py`.

## Plasma widget

Install or upgrade the widget:

```bash
./install-widget.sh
```

The installed applet id is `local.aiusage.rings` and the package path is:

```text
~/.local/share/plasma/plasmoids/local.aiusage.rings/
```

The panel glyph is two side-by-side weekly-remaining rings:

- left ring: Claude weekly remaining
- right ring: Codex weekly remaining
- center text in each ring: whole days until that provider's weekly reset

It refreshes every 10 minutes and once when the popup opens. The popup shows one visual panel per provider, with the weekly reset ring plus current-window and weekly quota bars.
