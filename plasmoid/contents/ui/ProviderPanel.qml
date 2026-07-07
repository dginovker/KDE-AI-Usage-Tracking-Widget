import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

ColumnLayout {
    id: root

    property string title: ""
    property var provider: ({})

    spacing: Kirigami.Units.smallSpacing
    Layout.fillWidth: true

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
}
