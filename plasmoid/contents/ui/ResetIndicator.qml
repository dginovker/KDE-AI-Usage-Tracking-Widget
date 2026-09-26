import QtQuick
import org.kde.plasma.components as PlasmaComponents3
Item {
    id: root
    property var resets: ({})
    property double currentTime: Date.now() / 1000
    readonly property bool unavailable: Boolean(resets.error) || (Boolean(resets.fresh_until) && currentTime >= resets.fresh_until)
    readonly property bool announced: !unavailable && Number(resets.alert_until) > currentTime
    readonly property string message: unavailable ? (resets.error || i18n("Reset information unavailable: last update is stale"))
        : resets.alert_until && !announced ? i18n("Earlier reset announcement — completion unverified") : (resets.next || "")
    HoverHandler { id: hover }
    PlasmaComponents3.ToolTip { visible: hover.hovered && root.message.length > 0; text: root.message }
    Accessible.name: message
    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.currentTime = Date.now() / 1000 }
    onResetsChanged: currentTime = Date.now() / 1000
}
