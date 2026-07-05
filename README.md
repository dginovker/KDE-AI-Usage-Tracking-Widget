# AI Usage Rings

KDE Plasma 6 applet for showing Claude Code and Codex quota pressure in a panel.

The panel shows two weekly quota rings: Claude on the left, Codex on the right. The number inside each ring is whole days until that weekly window resets. Colors are pace-aware, so low remaining quota can still be green when the reset is soon.

## Install
```bash
./install-widget.sh
```

Applet id: `local.aiusage.rings`.

## Claude Usage

Claude Code exposes quota through its status-line payload:

```json
{
  "statusLine": {
    "type": "command",
    "command": "/home/wacket/.local/share/plasma/plasmoids/local.aiusage.rings/contents/code/widget_snapshot.py --capture-claude-statusline",
    "padding": 0,
    "refreshInterval": 600
  }
}
```

## Data Sources

- Codex: `~/.codex/state_5.sqlite` and `~/.codex/sessions/**/*.jsonl`
- Claude: `~/.cache/ai-usage/claude-statusline.json`

Refresh: every 10 minutes and once when opened.
