import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property string title: ""
    property var quota: ({})

    spacing: Kirigami.Units.smallSpacing / 2

    function used() {
        return quota && typeof quota.used === "number" ? quota.used : -1;
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            text: root.title
            font.bold: true
            Layout.fillWidth: true
        }

        PlasmaComponents3.Label {
            text: root.used() < 0 ? "--" : i18n("%1 used", Math.round(root.used()).toString() + "%")
            opacity: root.used() < 0 ? 0.55 : 1
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(5, Kirigami.Units.smallSpacing)
        radius: height / 2
        color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.16)

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: parent.width * Math.max(0, Math.min(100, root.used())) / 100
            radius: parent.radius
            color: root.quota.color || Kirigami.Theme.disabledTextColor
            visible: root.used() >= 0
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            text: root.quota.pace || "--"
            opacity: 0.78
            elide: Text.ElideRight
            font.pixelSize: Math.max(9, Kirigami.Theme.defaultFont.pixelSize * 0.86)
            Layout.fillWidth: true
        }

        PlasmaComponents3.Label {
            text: root.quota.reset_label || "--"
            opacity: 0.7
            font.pixelSize: Math.max(9, Kirigami.Theme.defaultFont.pixelSize * 0.86)
        }
    }
}
