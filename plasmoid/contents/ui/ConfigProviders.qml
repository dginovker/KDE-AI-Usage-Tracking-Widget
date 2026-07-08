import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    property alias cfg_showClaude: showClaude.checked
    property alias cfg_showCodex: showCodex.checked
    property alias cfg_showKimi: showKimi.checked

    QQC2.CheckBox {
        id: showClaude
        text: i18n("Claude")
        Kirigami.FormData.label: i18n("Show:")
    }

    QQC2.CheckBox {
        id: showCodex
        text: i18n("Codex")
    }

    QQC2.CheckBox {
        id: showKimi
        text: i18n("Kimi")
    }
}
