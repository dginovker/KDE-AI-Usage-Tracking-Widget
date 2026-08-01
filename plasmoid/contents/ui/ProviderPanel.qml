import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
ColumnLayout {
    id: root
    property string title: ""
    property var provider: ({})
    readonly property var resets: provider.global_resets || ({})
    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1; Layout.alignment: Qt.AlignTop
    function quota(name) { return provider[name] || {}; }
    function used(name) { return typeof quota(name).used === "number" ? quota(name).used : -1; }
    PlasmaComponents3.Label {
        text: root.title; font.bold: true; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true
    }
    RingGauge {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: Kirigami.Units.iconSizes.huge; Layout.preferredHeight: Layout.preferredWidth
        percent: root.used("weekly"); innerPercent: root.used("current")
        centerText: root.quota("weekly").days || "?"
        accentColor: root.quota("weekly").color || ""; innerAccentColor: root.quota("current").color || ""
    }
    PlasmaComponents3.Label {
        text: root.quota("weekly").reset_label || "--"; opacity: 0.72
        horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true
    }
    Repeater {
        model: root.used("current") < 0 ? [{"key": "weekly", "title": i18n("Week")}] : [{"key": "current", "title": i18n("5h")}, {"key": "weekly", "title": i18n("Week")}]
        ColumnLayout {
            readonly property var quotaData: root.quota(modelData.key)
            readonly property real used: root.used(modelData.key)
            spacing: Kirigami.Units.smallSpacing / 2; Layout.fillWidth: true
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label { text: modelData.title; font.bold: true; Layout.fillWidth: true }
                PlasmaComponents3.Label {
                    text: used < 0 ? "--" : i18n("%1 used", Math.round(used) + "%"); opacity: used < 0 ? 0.55 : 1
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: Math.max(5, Kirigami.Units.smallSpacing)
                radius: height / 2
                color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.16)
                Rectangle {
                    anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                    width: parent.width * Math.max(0, Math.min(100, used)) / 100; radius: parent.radius
                    color: quotaData.color || Kirigami.Theme.disabledTextColor; visible: used >= 0
                }
            }
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label {
                    text: quotaData.pace || "--"; opacity: 0.78; elide: Text.ElideRight
                    font.pixelSize: Math.max(9, Kirigami.Theme.defaultFont.pixelSize * 0.86); Layout.fillWidth: true
                }
                PlasmaComponents3.Label {
                    text: quotaData.reset_label || "--"; opacity: 0.7
                    font.pixelSize: Math.max(9, Kirigami.Theme.defaultFont.pixelSize * 0.86)
                }
            }
        }
    }
    ColumnLayout {
        visible: Boolean(root.resets.past || root.resets.next || root.resets.banked)
        spacing: Kirigami.Units.smallSpacing; Layout.fillWidth: true; Layout.topMargin: Kirigami.Units.largeSpacing
        Repeater {
            model: ["past", "next", "banked"]
            PlasmaComponents3.Label {
                visible: Boolean(root.resets[modelData])
                text: modelData === "past" ? i18n("Past: %1", root.resets.past || "")
                    : modelData === "next" ? i18n("Next odds: %1", root.resets.next || "")
                    : i18n("Banked: %1", root.resets.banked || "")
                opacity: 0.72; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
        }
    }
}
