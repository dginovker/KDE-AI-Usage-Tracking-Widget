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
        if (!quota || typeof quota.used_percent !== "number") {
            return -1;
        }
        return quota.used_percent;
    }

    function colorFor(value) {
        if (value < 0) {
            return Kirigami.Theme.disabledTextColor;
        }
        if (quota && quota.color) {
            return quota.color;
        }
        if (value < 64) {
            return "#9b59b6";
        }
        if (value < 80) {
            return "#fdbc4b";
        }
        return "#27ae60";
    }

    function percentText(value) {
        if (value < 0) {
            return "--";
        }
        return Math.round(value).toString() + "%";
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
            text: root.percentText(root.used())
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
            color: root.colorFor(root.used())
            visible: root.used() >= 0
        }
    }

    PlasmaComponents3.Label {
        text: quota && quota.reset_short ? quota.reset_short : "--"
        opacity: 0.7
        font.pixelSize: Math.max(9, Kirigami.Theme.defaultFont.pixelSize * 0.86)
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignRight
    }
}
