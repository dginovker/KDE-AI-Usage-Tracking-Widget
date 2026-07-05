import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    readonly property int refreshMs: 10 * 60 * 1000
    readonly property string helperPath: fileUrlToPath(Qt.resolvedUrl("../code/widget_snapshot.py"))
    property string activeSource: ""
    property var snapshot: ({})
    property bool loading: false
    property string lastError: ""

    Plasmoid.title: i18n("AI Usage Rings")
    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground

    toolTipMainText: i18n("AI Usage")
    toolTipSubText: tooltipText()

    compactRepresentation: Item {
        id: compact

        Layout.minimumWidth: Kirigami.Units.iconSizes.medium * 2 + Kirigami.Units.smallSpacing
        Layout.minimumHeight: Kirigami.Units.iconSizes.medium
        Layout.preferredWidth: Kirigami.Units.iconSizes.medium * 2 + Kirigami.Units.smallSpacing
        Layout.preferredHeight: Kirigami.Units.iconSizes.medium

        RowLayout {
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            RingGauge {
                Layout.preferredWidth: Math.max(16, compact.height - 2)
                Layout.preferredHeight: Layout.preferredWidth
                percent: root.percent(root.value(["claude", "weekly", "used_percent"]))
                centerText: root.resetDaysText("claude")
                accentColor: root.value(["claude", "weekly", "color"]) || ""
            }

            RingGauge {
                Layout.preferredWidth: Math.max(16, compact.height - 2)
                Layout.preferredHeight: Layout.preferredWidth
                percent: root.percent(root.value(["codex", "weekly", "used_percent"]))
                centerText: root.resetDaysText("codex")
                accentColor: root.value(["codex", "weekly", "color"]) || ""
            }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: {
                root.refreshData();
                root.expanded = !root.expanded;
            }
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 22
        Layout.minimumHeight: Kirigami.Units.gridUnit * 16
        collapseMarginsHint: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true

                PlasmaComponents3.Label {
                    text: i18n("AI Usage")
                    font.bold: true
                    Layout.fillWidth: true
                }
            }

            GridLayout {
                columns: 2
                columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: Kirigami.Units.largeSpacing
                Layout.fillWidth: true

                ProviderPanel {
                    title: i18n("Claude")
                    provider: root.value(["claude"]) || {}
                }

                ProviderPanel {
                    title: i18n("Codex")
                    provider: root.value(["codex"]) || {}
                }
            }

            PlasmaComponents3.Label {
                visible: root.lastError.length > 0
                text: root.lastError
                color: "#da4453"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                visible: root.value(["claude", "available"]) === false
                text: i18n("Claude usage will appear after the next Claude Code response.")
                opacity: 0.7
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Item {
                Layout.fillHeight: true
            }
        }
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"

        onNewData: function(sourceName, data) {
            if (sourceName !== root.activeSource) {
                return;
            }
            disconnectSource(sourceName);
            root.activeSource = "";
            root.loading = false;

            const stdout = data.stdout || data["stdout"] || "";
            if (stdout.length === 0) {
                root.lastError = i18n("Usage helper returned no data.");
                return;
            }

            try {
                root.snapshot = JSON.parse(stdout);
                root.lastError = "";
            } catch (error) {
                root.lastError = i18n("Could not parse usage helper output.");
            }
        }
    }

    Timer {
        interval: root.refreshMs
        running: true
        repeat: true
        onTriggered: root.refreshData()
    }

    onExpandedChanged: {
        if (root.expanded) {
            refreshData();
        }
    }

    Component.onCompleted: {
        var configureAction = Plasmoid.internalAction("configure");
        if (configureAction) {
            configureAction.visible = false;
            configureAction.enabled = false;
        }
        refreshData();
    }

    function fileUrlToPath(url) {
        var text = url.toString();
        if (text.indexOf("file://") === 0) {
            return decodeURIComponent(text.substring(7));
        }
        return text;
    }

    function shellQuote(text) {
        return "'" + text.replace(/'/g, "'\\''") + "'";
    }

    function refreshData() {
        if (loading) {
            return;
        }
        activeSource = "python3 " + shellQuote(helperPath) + " --stamp " + Date.now();
        loading = true;
        executable.connectSource(activeSource);
    }

    function percent(value) {
        if (typeof value !== "number") {
            return -1;
        }
        return value;
    }

    function percentLabel(value) {
        if (typeof value !== "number") {
            return "--";
        }
        return Math.round(value).toString() + "%";
    }

    function updatedLabel() {
        if (!snapshot || !snapshot.generated_at) {
            return i18n("not updated");
        }
        var date = new Date(snapshot.generated_at);
        if (isNaN(date.getTime())) {
            return snapshot.generated_at;
        }
        return date.toLocaleTimeString(Qt.locale(), "hh:mm");
    }

    function tooltipText() {
        var claudeWeek = percentLabel(value(["claude", "weekly", "used_percent"]));
        var codexWeek = percentLabel(value(["codex", "weekly", "used_percent"]));
        var updated = updatedLabel();
        return i18n("Claude week used: %1\nCodex week used: %2\nUpdated: %3", claudeWeek, codexWeek, updated);
    }

    function resetDaysText(providerName) {
        var label = value([providerName, "weekly", "reset_days_label"]);
        if (label === 0 || label === "0") {
            return "0";
        }
        if (label !== undefined && label !== null && label !== "") {
            return String(label);
        }
        return "?";
    }

    function value(path) {
        var current = snapshot;
        for (var i = 0; i < path.length; i++) {
            if (current === null || current === undefined || typeof current !== "object") {
                return undefined;
            }
            current = current[path[i]];
        }
        return current;
    }
}
