import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
Kirigami.FormLayout {
    property alias cfg_showClaude: claude.checked
    property alias cfg_showCodex: codex.checked
    property alias cfg_showKimi: kimi.checked
    property alias cfg_showGrok: grok.checked
    QQC2.CheckBox { id: claude; text: i18n("Claude"); Kirigami.FormData.label: i18n("Show:") }
    QQC2.CheckBox { id: codex; text: i18n("Codex") }
    QQC2.CheckBox { id: kimi; text: i18n("Kimi") }
    QQC2.CheckBox { id: grok; text: i18n("Grok") }
}
