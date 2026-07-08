import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property var tokens: ({})
    readonly property var windows: tokens && tokens.windows ? tokens.windows : []

    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true

    PlasmaComponents3.Label {
        text: i18n("API cost estimate")
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
            text: i18n("Codex tokens")
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
        }

        PlasmaComponents3.Label {
            text: i18n("Codex $")
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
        }

        PlasmaComponents3.Label {
            text: i18n("Claude tokens")
            opacity: 0.7
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
        }

        PlasmaComponents3.Label {
            text: i18n("Claude $")
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
                text: modelData.codex_tokens || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 5
            }

            PlasmaComponents3.Label {
                text: modelData.codex_cost || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }

            PlasmaComponents3.Label {
                text: modelData.claude_tokens || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 5
            }

            PlasmaComponents3.Label {
                text: modelData.claude_cost || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }
        }
    }

    PlasmaComponents3.Label {
        visible: Boolean(root.tokens && root.tokens.note)
        text: root.tokens.note || ""
        opacity: 0.68
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
}
