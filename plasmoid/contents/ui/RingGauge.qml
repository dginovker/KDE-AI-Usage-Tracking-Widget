import QtQuick
import org.kde.kirigami as Kirigami
Item {
    id: root
    property real percent: -1; property real innerPercent: -1
    property string centerText: "--"; property string accentColor: ""; property string innerAccentColor: ""
    implicitWidth: Kirigami.Units.iconSizes.medium; implicitHeight: implicitWidth
    function ring(ctx, radius, stroke, value, color) {
        ctx.lineWidth = stroke; ctx.lineCap = "round"; ctx.beginPath();
        ctx.strokeStyle = Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.18);
        ctx.arc(width / 2, height / 2, radius, 0, 2 * Math.PI, false); ctx.stroke();
        if (value < 0) return;
        ctx.beginPath(); ctx.strokeStyle = color || Kirigami.Theme.highlightColor;
        ctx.arc(width / 2, height / 2, radius, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.min(100, Math.max(0, value)) / 100, false);
        ctx.stroke();
    }
    Canvas {
        id: canvas; anchors.fill: parent; antialiasing: true
        onPaint: {
            const ctx = getContext("2d"), size = Math.min(width, height);
            const outerStroke = Math.max(3, Math.round(size * 0.13)), outerRadius = size / 2 - outerStroke / 2 - 1;
            const innerStroke = Math.max(3, Math.round(size * 0.12));
            const innerRadius = outerRadius - outerStroke / 2 - Math.max(1, Math.round(size * 0.04)) - innerStroke / 2;
            ctx.clearRect(0, 0, width, height); root.ring(ctx, outerRadius, outerStroke, root.percent, root.accentColor);
            if (root.innerPercent >= 0 && innerRadius > innerStroke / 2) root.ring(ctx, innerRadius, innerStroke, root.innerPercent, root.innerAccentColor);
        }
    }
    Text {
        anchors.centerIn: parent; text: String(root.centerText); color: Kirigami.Theme.textColor; font.bold: true
        font.pixelSize: Math.max(8, Math.min(parent.width, parent.height) * (text.length > 2 ? 0.24 : 0.31))
    }
    onPercentChanged: canvas.requestPaint(); onInnerPercentChanged: canvas.requestPaint()
    onAccentColorChanged: canvas.requestPaint(); onInnerAccentColorChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint(); onHeightChanged: canvas.requestPaint()
}
