import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property var tokens: ({})
    readonly property var windows: tokens && tokens.windows ? tokens.windows : []
    readonly property var cacheRows: tokens && tokens.cache ? tokens.cache : []
    readonly property var modelRows: tokens && tokens.models ? tokens.models : []

    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true

    PlasmaComponents3.Label {
        text: i18n("API equivalent")
        font.bold: true
        Layout.fillWidth: true
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
                text: modelData.tokens || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }

            PlasmaComponents3.Label {
                text: modelData.cost || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }

            PlasmaComponents3.Label {
                text: modelData.codex || "--"
                opacity: 0.78
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                text: modelData.claude || "--"
                opacity: 0.78
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.18)
    }

    PlasmaComponents3.Label {
        text: i18n("Cache, 30d")
        font.bold: true
        Layout.fillWidth: true
    }

    Repeater {
        model: root.cacheRows

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                text: modelData.provider || "--"
                font.bold: true
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }

            PlasmaComponents3.Label {
                text: modelData.primary || "--"
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                text: modelData.detail || "--"
                opacity: 0.72
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    PlasmaComponents3.Label {
        text: i18n("Top models, 30d")
        font.bold: true
        Layout.fillWidth: true
    }

    Repeater {
        model: root.modelRows

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                text: modelData.provider || "--"
                opacity: 0.78
                Layout.preferredWidth: Kirigami.Units.gridUnit * 3
            }

            PlasmaComponents3.Label {
                text: modelData.model || "--"
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                text: modelData.cost || "--"
                horizontalAlignment: Text.AlignRight
                Layout.preferredWidth: Kirigami.Units.gridUnit * 4
            }

            PlasmaComponents3.Label {
                text: modelData.tokens || "--"
                opacity: 0.72
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
