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
    readonly property var providers: ["claude", "codex"]
    readonly property var apiWindows: [{"key": "24h", "label": "24h"}, {"key": "7d", "label": "7d"}, {"key": "30d", "label": "30d"}, {"key": "lifetime", "label": "All"}]
    property string apiWindow: "30d"
    property string activeSource: ""
    property var snapshot: ({})
    property bool loading: false
    property string lastError: ""

    Plasmoid.title: i18n("AI Usage Rings")
    Plasmoid.icon: "utilities-system-monitor"
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground

    toolTipMainText: i18n("AI Usage")

    compactRepresentation: Item {
        id: compact

        Layout.minimumWidth: Kirigami.Units.iconSizes.medium * 2 + Kirigami.Units.smallSpacing
        Layout.minimumHeight: Kirigami.Units.iconSizes.medium
        Layout.preferredWidth: Kirigami.Units.iconSizes.medium * 2 + Kirigami.Units.smallSpacing
        Layout.preferredHeight: Kirigami.Units.iconSizes.medium

        RowLayout {
            anchors.centerIn: parent
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: root.providers

                RingGauge {
                    Layout.preferredWidth: Math.max(16, compact.height - 2)
                    Layout.preferredHeight: Layout.preferredWidth
                    percent: root.used(modelData, "weekly")
                    innerPercent: root.used(modelData, "current")
                    centerText: root.quota(modelData, "weekly").days || "?"
                    accentColor: root.quota(modelData, "weekly").color || ""
                    innerAccentColor: root.quota(modelData, "current").color || ""
                }
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
        Layout.minimumWidth: Kirigami.Units.gridUnit * 34
        Layout.minimumHeight: Kirigami.Units.gridUnit * 21
        collapseMarginsHint: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                text: i18n("AI Usage")
                font.bold: true
                Layout.fillWidth: true
            }

            GridLayout {
                columns: 2
                columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: Kirigami.Units.largeSpacing
                Layout.fillWidth: true

                Repeater {
                    model: root.providers

                    ProviderPanel {
                        title: modelData === "claude" ? i18n("Claude") : i18n("Codex")
                        provider: root.provider(modelData)
                    }
                }

                RowLayout {
                    Layout.columnSpan: 2
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    PlasmaComponents3.Label {
                        text: i18n("API estimate")
                        font.bold: true
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Repeater {
                        model: root.apiWindows

                        Rectangle {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 2.4
                            Layout.preferredHeight: Kirigami.Units.gridUnit * 1.35
                            radius: Kirigami.Units.cornerRadius
                            color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, root.apiWindow === modelData.key ? 0.16 : 0.08)
                            border.width: root.apiWindow === modelData.key ? 1 : 0
                            border.color: "#3daee9"

                            PlasmaComponents3.Label {
                                anchors.centerIn: parent
                                text: modelData.label
                                color: Kirigami.Theme.textColor
                                font.bold: root.apiWindow === modelData.key
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.apiWindow = modelData.key
                            }
                        }
                    }
                }

                Repeater {
                    model: root.providers

                    TokenCostPanel {
                        providerName: modelData
                        windowKey: root.apiWindow
                        tokens: root.snapshot.tokens || {}
                    }
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
                visible: root.provider("claude").available === false
                text: i18n("Claude usage will appear after the next Claude Code response.")
                opacity: 0.7
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            PlasmaComponents3.Label {
                visible: Boolean(root.snapshot.tokens && root.snapshot.tokens.note)
                text: (root.snapshot.tokens || {}).note || ""
                opacity: 0.68
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

    Component.onCompleted: refreshData()

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

    function provider(providerName) {
        return snapshot && typeof snapshot === "object" ? snapshot[providerName] || {} : {};
    }

    function quota(providerName, quotaName) {
        return provider(providerName)[quotaName] || {};
    }

    function used(providerName, quotaName) {
        var current = quota(providerName, quotaName);
        return typeof current.used === "number" ? current.used : -1;
    }

}
