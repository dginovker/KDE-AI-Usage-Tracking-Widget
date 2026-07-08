import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property string providerName: ""
    property string title: ""
    property var tokens: ({})
    readonly property var windows: tokens && tokens.windows ? tokens.windows : []

    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true

    PlasmaComponents3.Label {
        text: root.title
        font.bold: true
        Layout.fillWidth: true
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            text: i18n("Window")
            opacity: 0.7
            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
        }

        PlasmaComponents3.Label {
            text: i18n("Tokens")
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
            Layout.fillWidth: true
        }

        PlasmaComponents3.Label {
            text: i18n("Est. $")
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
        }
    }

    Repeater {
        model: root.windows

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                text: modelData.label || "--"
                font.bold: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 3
            }

            PlasmaComponents3.Label {
                text: modelData[root.providerName + "_tokens"] || "--"
                horizontalAlignment: Text.AlignRight
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                text: modelData[root.providerName + "_cost"] || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }
        }
    }
}
