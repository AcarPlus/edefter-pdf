"""Uygulama ikonunu (app.png + app.ico) Qt ile çizer: python assets/make_icon.py"""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

HERE = Path(__file__).resolve().parent


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256

    # zemin: yuvarlatılmış kare, koyu petrol → yeşil
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#1f5f7a"))
    g.setColorAt(1, QColor("#2e8b6a"))
    p.setBrush(QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)

    # belge, kıvrık köşe
    doc = QPainterPath()
    x0, y0, x1, y1, fold = 66 * s, 44 * s, 190 * s, 212 * s, 38 * s
    doc.moveTo(x0, y0)
    doc.lineTo(x1 - fold, y0)
    doc.lineTo(x1, y0 + fold)
    doc.lineTo(x1, y1)
    doc.lineTo(x0, y1)
    doc.closeSubpath()
    p.setBrush(QColor("#ffffff"))
    p.drawPath(doc)
    corner = QPainterPath()
    corner.moveTo(x1 - fold, y0)
    corner.lineTo(x1 - fold, y0 + fold)
    corner.lineTo(x1, y0 + fold)
    corner.closeSubpath()
    p.setBrush(QColor("#cfe3dc"))
    p.drawPath(corner)

    # defter satırları
    p.setPen(QPen(QColor("#9bb8c4"), 9 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i, w in enumerate((88, 70, 88, 56)):
        y = (100 + i * 22) * s
        p.drawLine(QPointF(86 * s, y), QPointF((86 + w) * s, y))

    # alt bant: onay işareti
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2e8b6a"))
    p.drawEllipse(QPointF(170 * s, 186 * s), 40 * s, 40 * s)
    p.setPen(QPen(QColor("#ffffff"), 12 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    tick = QPainterPath()
    tick.moveTo(152 * s, 187 * s)
    tick.lineTo(165 * s, 200 * s)
    tick.lineTo(189 * s, 172 * s)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(tick)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication([])
    draw(256).save(str(HERE / "app.png"))
    draw(256).save(str(HERE / "app.ico"))
    print("ok")
