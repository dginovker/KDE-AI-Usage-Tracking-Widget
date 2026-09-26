## KDE AI Usage Rings

Taskbar widget visual to help maximize your AI subscription usage :)

<img width="893" height="697" alt="image" src="https://github.com/user-attachments/assets/cf362d17-ac09-420f-bcfc-4d21e4a9bf6c" />

Codex's center number turns light cyan while a fresh reset announcement is active.
Local weekly quota reset tracking starts after installation and records a reset when
usage drops and the weekly reset deadline advances by more than a minute. The widget
shows the interval between the two successful API readings, normally about ten minutes
apart. Sleep and failed requests widen that interval; resets with no observed usage
drop can be missed. “Early” means the change was observed before the previous deadline;
“scheduled window” means the observation interval includes that deadline, so the cause
is still uncertain. Neither identifies a global reset versus a banked reset redemption.
Account-separated observations and reset events are saved in
`$XDG_DATA_HOME/ai-usage/codex-resets.json` (normally
`~/.local/share/ai-usage/codex-resets.json`) for later timing analysis. Cached readings
are excluded; no historical landing times are inferred from announcements.
