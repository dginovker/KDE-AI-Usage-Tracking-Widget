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
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("../code/widget_snapshot.py").toString().replace("file://", ""))
    readonly property var providers: providerList(Plasmoid.configuration.showClaude, Plasmoid.configuration.showCodex, Plasmoid.configuration.showKimi, Plasmoid.configuration.showGrok)
    readonly property var apiWindows: ["24h", "7d", "30d", "lifetime"]
    property string apiWindow: "30d"; property string activeSource: ""
    property var snapshot: ({}); property bool loading: false; property string lastError: ""; property string lastUpdated: ""
    Plasmoid.title: i18n("AI Usage Rings"); Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.status: PlasmaCore.Types.ActiveStatus; Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    toolTipMainText: i18n("AI Usage")
    compactRepresentation: Item {
        id: compact
        Layout.minimumWidth: Kirigami.Units.iconSizes.medium * root.providers.length + Kirigami.Units.smallSpacing * Math.max(0, root.providers.length - 1)
        Layout.minimumHeight: Kirigami.Units.iconSizes.medium
        Layout.preferredWidth: Layout.minimumWidth; Layout.preferredHeight: Layout.minimumHeight
        RowLayout {
            anchors.centerIn: parent; spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: root.providers
                RingGauge {
                    Layout.preferredWidth: Math.max(16, compact.height - 2); Layout.preferredHeight: Layout.preferredWidth
                    percent: root.used(modelData, "weekly"); innerPercent: root.used(modelData, "current")
                    centerText: root.quota(modelData, "weekly").days || "?"
                    accentColor: root.quota(modelData, "weekly").color || ""
                    innerAccentColor: root.quota(modelData, "current").color || ""
                }
            }
        }
        MouseArea { anchors.fill: parent; onClicked: { root.refreshData(); root.expanded = !root.expanded; } }
    }
    fullRepresentation: PlasmaExtras.Representation {
        Layout.minimumWidth: Kirigami.Units.gridUnit * Math.max(34, root.providers.length * 17)
        Layout.minimumHeight: Kirigami.Units.gridUnit * 21; collapseMarginsHint: true
        ColumnLayout {
            anchors.fill: parent; anchors.margins: Kirigami.Units.largeSpacing; spacing: Kirigami.Units.smallSpacing
            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label { text: i18n("AI Usage"); font.bold: true; Layout.fillWidth: true }
                Item {
                    Layout.preferredWidth: refreshButton.implicitWidth; Layout.preferredHeight: refreshButton.implicitHeight
                    PlasmaComponents3.ToolButton {
                        id: refreshButton
                        anchors.fill: parent; icon.name: "view-refresh"; enabled: !root.loading
                        Accessible.name: root.loading ? i18n("Refreshing usage") : i18n("Refresh usage")
                        onClicked: root.refreshData()
                    }
                    HoverHandler { id: refreshHover }
                    PlasmaComponents3.ToolTip {
                        visible: refreshHover.hovered; delay: Kirigami.Units.toolTipDelay
                        text: root.loading ? i18n("Refreshing usage...")
                            : root.lastError ? i18n("Refresh failed: %1. Click to retry.", root.lastError)
                            : root.lastUpdated ? i18n("Updated %1. Click to refresh.", root.lastUpdated)
                            : i18n("Click to refresh usage.")
                    }
                }
            }
            GridLayout {
                columns: root.providers.length; columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: Kirigami.Units.largeSpacing; Layout.fillWidth: true
                Repeater {
                    model: root.providers
                    ProviderPanel { title: root.providerLabel(modelData); provider: root.provider(modelData) }
                }
                RowLayout {
                    Layout.columnSpan: root.providers.length; Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.largeSpacing; spacing: Kirigami.Units.smallSpacing
                    PlasmaComponents3.Label { text: i18n("API cost"); font.bold: true }
                    Repeater {
                        model: root.apiWindows
                        Rectangle {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 2.4; Layout.preferredHeight: Kirigami.Units.gridUnit * 1.35
                            radius: Kirigami.Units.cornerRadius
                            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, root.apiWindow === modelData ? 0.16 : 0.08)
                            border.width: root.apiWindow === modelData ? 1 : 0; border.color: "#3daee9"
                            PlasmaComponents3.Label {
                                anchors.centerIn: parent; text: modelData === "lifetime" ? i18n("All") : modelData
                                font.bold: root.apiWindow === modelData
                            }
                            MouseArea { anchors.fill: parent; onClicked: root.apiWindow = modelData }
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
                Repeater {
                    model: root.providers
                    ColumnLayout {
                        id: costPanel
                        readonly property var totals: root.cost(modelData)
                        readonly property var models: totals.models || []
                        property bool expanded: false
                        visible: Boolean(totals.tokens || totals.cost)
                        spacing: Kirigami.Units.smallSpacing / 2; Layout.fillWidth: true
                        Layout.minimumWidth: 0; Layout.preferredWidth: 1
                        PlasmaComponents3.Label {
                            text: totals.tokens || "--"; font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.25; Layout.fillWidth: true
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: Kirigami.Units.smallSpacing
                            PlasmaComponents3.Label {
                                text: i18n("%1 API equivalent", totals.cost || "--"); opacity: 0.74
                                Layout.fillWidth: true; elide: Text.ElideRight
                            }
                            PlasmaComponents3.ToolButton {
                                visible: costPanel.models.length > 0
                                icon.name: costPanel.expanded ? "go-up" : "go-down"
                                Accessible.name: costPanel.expanded ? i18n("Hide model costs") : i18n("Show model costs")
                                onClicked: costPanel.expanded = !costPanel.expanded
                            }
                        }
                        Repeater {
                            model: costPanel.expanded ? costPanel.models : []
                            RowLayout {
                                Layout.fillWidth: true; spacing: Kirigami.Units.smallSpacing
                                PlasmaComponents3.Label {
                                    text: modelData.name; opacity: 0.68; elide: Text.ElideMiddle
                                    Layout.fillWidth: true; Layout.minimumWidth: 0
                                }
                                PlasmaComponents3.Label { text: modelData.cost; opacity: 0.8 }
                            }
                        }
                        PlasmaComponents3.Label {
                            visible: costPanel.expanded && Boolean(costPanel.totals.note)
                            text: costPanel.totals.note || ""; opacity: 0.68
                        }
                    }
                }
            }
            PlasmaComponents3.Label {
                visible: root.provider("claude").available === false
                text: i18n("Claude usage will appear after the next Claude Code response.")
                opacity: 0.7; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            PlasmaComponents3.Label {
                visible: Boolean((root.snapshot.tokens || {}).note); text: (root.snapshot.tokens || {}).note || ""
                opacity: 0.68; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
            Item { Layout.fillHeight: true }
            PlasmaComponents3.Label {
                visible: text.length > 0; text: root.errors(); color: "#fdbc4b"
                horizontalAlignment: Text.AlignRight; wrapMode: Text.WordWrap; Layout.fillWidth: true
            }
        }
    }
    P5Support.DataSource {
        id: executable; engine: "executable"
        onNewData: function(sourceName, data) {
            if (sourceName !== root.activeSource) return;
            disconnectSource(sourceName); root.activeSource = ""; root.loading = false;
            const output = data.stdout || data["stdout"] || "";
            if (!output) { root.lastError = i18n("Usage helper returned no data."); return; }
            try { root.snapshot = JSON.parse(output); root.lastError = ""; root.lastUpdated = Qt.formatTime(new Date(), "HH:mm:ss"); }
            catch (error) { root.lastError = i18n("Could not parse usage helper output."); }
        }
    }
    Timer { interval: root.refreshMs; running: true; repeat: true; onTriggered: root.refreshData() }
    Component.onCompleted: refreshData()
    function quote(value) { return "'" + value.replace(/'/g, "'\\''") + "'"; }
    function refreshData() {
        if (loading) return;
        activeSource = "python3 " + quote(helperPath) + " --providers=" + quote(providers.join(",")) + " --stamp " + Date.now();
        loading = true; executable.connectSource(activeSource);
    }
    function provider(name) { return snapshot && typeof snapshot === "object" ? snapshot[name] || {} : {}; }
    function quota(name, key) { return provider(name)[key] || {}; }
    function used(name, key) { return typeof quota(name, key).used === "number" ? quota(name, key).used : -1; }
    function providerLabel(name) { return name.charAt(0).toUpperCase() + name.slice(1); }
    function errors() {
        const values = (snapshot.errors || []).slice();
        if (lastError) values.unshift(Qt.formatTime(new Date(), "HH:mm") + " - Widget: " + lastError);
        return values.join("\n");
    }
    function providerList(claude, codex, kimi, grok) {
        const names = ["claude", "codex", "kimi", "grok"], enabled = [claude, codex, kimi, grok], selected = [];
        for (let index = 0; index < names.length; index++) if (enabled[index] !== false) selected.push(names[index]);
        return selected.length ? selected : names;
    }
    function cost(name) {
        const windows = (snapshot.tokens || {}).windows || [];
        for (let index = 0; index < windows.length; index++)
            if (windows[index].key === apiWindow) return (windows[index].providers || {})[name] || {};
        return {};
    }
}
