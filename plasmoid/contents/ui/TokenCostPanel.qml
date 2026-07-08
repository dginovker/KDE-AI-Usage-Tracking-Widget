import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property string providerName: ""
    property string windowKey: "30d"
    property var tokens: ({})
    readonly property var windows: tokens && tokens.windows ? tokens.windows : []
    readonly property var selected: selectedWindow()

    spacing: Kirigami.Units.smallSpacing / 2
    Layout.fillWidth: true

    PlasmaComponents3.Label {
        text: root.selected[root.providerName + "_tokens"] || "--"
        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.25
        Layout.fillWidth: true
    }

    PlasmaComponents3.Label {
        text: i18n("%1 API equivalent", root.selected[root.providerName + "_cost"] || "--")
        opacity: 0.74
        Layout.fillWidth: true
    }

    function selectedWindow() {
        for (let i = 0; i < root.windows.length; i++) {
            if (root.windows[i].key === root.windowKey) {
                return root.windows[i];
            }
        }
        return root.windows.length > 0 ? root.windows[0] : {};
    }
}
