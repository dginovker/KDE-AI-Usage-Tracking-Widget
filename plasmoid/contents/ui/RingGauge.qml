import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: root

    property real percent: -1
    property real innerPercent: -1
    property string centerText: "--"
    property string accentColor: ""
    property string innerAccentColor: ""
    property bool innerVisible: false

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: Kirigami.Units.iconSizes.medium

    function hasValue(value) {
        return typeof value === "number" && value >= 0;
    }

    function ringColor(value, color) {
        if (!hasValue(value)) {
            return Kirigami.Theme.disabledTextColor;
        }
        if (color.length > 0) {
            return color;
        }
        if (value < 64) {
            return "#3daee9";
        }
        if (value < 80) {
            return "#fdbc4b";
        }
        return "#27ae60";
    }

    function drawRing(ctx, cx, cy, radius, stroke, value, color) {
        ctx.lineWidth = stroke;
        ctx.lineCap = "round";

        ctx.beginPath();
        ctx.strokeStyle = Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g, Kirigami.Theme.textColor.b, 0.18);
        ctx.arc(cx, cy, radius, 0, Math.PI * 2, false);
        ctx.stroke();

        if (!hasValue(value)) {
            return;
        }

        var start = -Math.PI / 2;
        var end = start + Math.PI * 2 * Math.max(0, Math.min(100, value)) / 100;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.arc(cx, cy, radius, start, end, false);
        ctx.stroke();
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d");
            ctx.clearRect(0, 0, width, height);

            var size = Math.min(width, height);
            var stroke = Math.max(3, Math.round(size * 0.13));
            var cx = width / 2;
            var cy = height / 2;
            var radius = size / 2 - stroke / 2 - 1;

            drawRing(ctx, cx, cy, radius, stroke, root.percent, ringColor(root.percent, root.accentColor));
            if (root.innerVisible) {
                var innerStroke = Math.max(3, Math.round(size * 0.12));
                var gap = Math.max(1, Math.round(size * 0.04));
                var innerRadius = radius - stroke / 2 - gap - innerStroke / 2;
                if (innerRadius > innerStroke / 2) {
                    drawRing(ctx, cx, cy, innerRadius, innerStroke, root.innerPercent, ringColor(root.innerPercent, root.innerAccentColor));
                }
            }
        }
    }

    Text {
        anchors.centerIn: parent
        text: String(root.centerText)
        color: Kirigami.Theme.textColor
        font.bold: true
        font.pixelSize: Math.max(8, Math.min(parent.width, parent.height) * (text.length > 2 ? 0.24 : 0.31))
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    onPercentChanged: canvas.requestPaint()
    onInnerPercentChanged: canvas.requestPaint()
    onAccentColorChanged: canvas.requestPaint()
    onInnerAccentColorChanged: canvas.requestPaint()
    onInnerVisibleChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
