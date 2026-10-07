## KDE AI Usage Rings

Taskbar widget visual to help maximize your AI subscription usage :)

The title refreshes every five seconds with working/idle counts for main Pi,
Claude Code, and Codex CLI agents attached to Konsole. Linux process ancestry
excludes subagents, headless agents, orphaned processes, and non-Konsole sessions.
Waiting for user input or permission counts as idle. Failed or missing state
shows “agent counts unavailable” with the error, not zero or stale counts.

Pi counts use the existing local Pi Dashboard at `http://127.0.0.1:8040/api/sessions`,
not Intercom membership: a messaging disconnect must not erase a running agent.
Streaming and compaction count as working; user-question tools count as idle.
Dashboard failures or missing live state remain explicit errors. Claude Code uses
its native `sessions/<pid>.json` presence files (including busy, idle, and waiting
states). The installer adds
metadata-only lifecycle hooks to `~/.codex/hooks.json`, preserving existing hooks
and backing up the original before changes. **Approve the new AI Usage command
in Codex `/hooks` and restart existing Codex sessions.** The hook stores only
PID, process start time, session ID, event name, and working/idle state in
`$XDG_CACHE_HOME/ai-usage/agents/codex` (normally `~/.cache/ai-usage/agents/codex`);
it never stores prompts or tool arguments. Codex must run locally in Konsole:
remote/daemon-owned hooks cannot identify the local terminal agent and produce
an explicit missing-state error. No model or provider settings are changed.

<img width="893" height="697" alt="image" src="https://github.com/user-attachments/assets/cf362d17-ac09-420f-bcfc-4d21e4a9bf6c" />

Codex's center number turns light cyan while a fresh reset announcement is active.
Every usage lookup is logged per provider (with the full error text) to
`~/.cache/ai-usage/lookup-log.jsonl` for 7 days; ongoing errors show the 24h failure count.

API-equivalent costs include native client logs and Pi session usage, grouped by
provider. Pi's recorded costs include cache warming and compaction; response/entry
IDs prevent forks and imported Claude copies from being counted twice. Codex's
external-import registry excludes replayed conversations from Codex usage entirely:
importing a transcript is not a new API call. Missing pricing or billing counters
appear in the bottom-right error area rather than as a zero-dollar estimate.

Local weekly quota reset tracking starts after installation and records a reset when
usage drops and the weekly reset deadline advances by more than a minute. The widget
shows the interval between the two successful API readings, normally about ten minutes
apart, under “Last reset.” Sleep and failed requests widen that interval; resets with no observed usage
drop can be missed. In the saved history, “early” means the change was observed before the previous deadline;
“scheduled window” means the observation interval includes that deadline, so the cause
is still uncertain. Neither identifies a global reset versus a banked reset redemption.
Account-separated observations and reset events are saved in
`$XDG_DATA_HOME/ai-usage/codex-resets.json` (normally
`~/.local/share/ai-usage/codex-resets.json`) for later timing analysis. Cached readings
are excluded; no historical landing times are inferred from announcements.
