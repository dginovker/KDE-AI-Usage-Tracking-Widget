import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property string title: ""
    property var provider: ({})
    readonly property var globalResets: provider && provider.global_resets ? provider.global_resets : ({})

    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    Layout.preferredWidth: 1

    function quota(name) {
        return provider && typeof provider === "object" ? provider[name] || {} : {};
    }

    function used(name) {
        var value = quota(name).used;
        return typeof value === "number" ? value : -1;
    }

    PlasmaComponents3.Label {
        text: root.title
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
        Layout.fillWidth: true
    }

    RingGauge {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: Kirigami.Units.iconSizes.huge
        Layout.preferredHeight: Kirigami.Units.iconSizes.huge
        percent: root.used("weekly")
        innerPercent: root.used("current")
        centerText: root.quota("weekly").days || "?"
        accentColor: root.quota("weekly").color || ""
        innerAccentColor: root.quota("current").color || ""
    }

    PlasmaComponents3.Label {
        text: root.quota("weekly").reset_label || "--"
        opacity: 0.72
        horizontalAlignment: Text.AlignHCenter
        Layout.fillWidth: true
    }

    Repeater {
        model: ["current", "weekly"]

        QuotaBar {
            title: modelData === "current" ? i18n("5h") : i18n("Week")
            quota: root.quota(modelData)
            Layout.fillWidth: true
        }
    }

    PlasmaComponents3.Label {
        visible: Boolean(root.globalResets.last)
        text: i18n("Last reset: %1", root.globalResets.last || "")
        opacity: 0.72
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
    }

    PlasmaComponents3.Label {
        visible: Boolean(root.globalResets.next)
        text: i18n("Next odds: %1", root.globalResets.next || "")
        opacity: 0.72
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        Layout.topMargin: root.globalResets.last ? 0 : Kirigami.Units.largeSpacing
    }

    PlasmaComponents3.Label {
        visible: Boolean(root.globalResets.banked)
        text: i18n("Banked: %1", root.globalResets.banked || "")
        opacity: 0.72
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        Layout.topMargin: root.globalResets.last || root.globalResets.next ? 0 : Kirigami.Units.largeSpacing
    }
}
