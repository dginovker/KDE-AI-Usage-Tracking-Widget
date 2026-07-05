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

    function quota(path) {
        if (!provider || typeof provider !== "object") {
            return {};
        }
        return provider[path] || {};
    }

    function weeklyPercent() {
        var weekly = quota("weekly");
        if (typeof weekly.used_percent !== "number") {
            return -1;
        }
        return weekly.used_percent;
    }

    function weeklyDays() {
        var weekly = quota("weekly");
        if (weekly.reset_days_label === 0 || weekly.reset_days_label === "0") {
            return "0";
        }
        if (weekly.reset_days_label !== undefined && weekly.reset_days_label !== null && weekly.reset_days_label !== "") {
            return String(weekly.reset_days_label);
        }
        return "?";
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
        percent: root.weeklyPercent()
        centerText: root.weeklyDays()
        accentColor: root.quota("weekly").color || ""
    }

    PlasmaComponents3.Label {
        text: root.quota("weekly").reset_short || "--"
        opacity: 0.72
        horizontalAlignment: Text.AlignHCenter
        Layout.fillWidth: true
    }

    QuotaBar {
        title: i18n("5h")
        quota: root.quota("current")
        Layout.fillWidth: true
    }

    QuotaBar {
        title: i18n("Week")
        quota: root.quota("weekly")
        Layout.fillWidth: true
    }
}
