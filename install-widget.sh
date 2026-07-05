#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

chmod +x plasmoid/contents/code/widget_snapshot.py

if kpackagetool6 --type Plasma/Applet --show local.aiusage.rings >/dev/null 2>&1; then
    kpackagetool6 --type Plasma/Applet --upgrade plasmoid
else
    kpackagetool6 --type Plasma/Applet --install plasmoid
fi

echo "Installed AI Usage Rings as local.aiusage.rings"
