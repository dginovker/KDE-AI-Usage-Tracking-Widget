import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: root

    property real percent: -1
    property string centerText: "--"
    property string accentColor: ""

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: Kirigami.Units.iconSizes.medium

    function hasValue(value) {
        return typeof value === "number" && value >= 0;
    }

    function ringColor(value) {
        if (!hasValue(value)) {
            return Kirigami.Theme.disabledTextColor;
        }
        if (accentColor.length > 0) {
            return accentColor;
        }
        if (value < 15) {
            return "#da4453";
        }
        if (value < 40) {
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
            var stroke = Math.max(2, Math.round(size * 0.12));
            var cx = width / 2;
            var cy = height / 2;
            var radius = size / 2 - stroke / 2 - 1;

            drawRing(ctx, cx, cy, radius, stroke, root.percent, ringColor(root.percent));
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
    onAccentColorChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
