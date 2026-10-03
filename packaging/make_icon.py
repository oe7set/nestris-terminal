"""Draws packaging/icon.ico (a gold/cyan T tetromino); run once, the .ico is committed."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

app = QGuiApplication([])
size = 256
img = QImage(size, size, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setBrush(QColor("#07070d"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(0, 0, size, size, 44, 44)
cell = 64
blocks = [(0, 0, "#ffc740"), (1, 0, "#ffc740"), (2, 0, "#ffc740"), (1, 1, "#4fd6ff")]
ox, oy = (size - 3 * cell) // 2, 60
for x, y, color in blocks:
    p.setBrush(QColor(color))
    p.drawRoundedRect(ox + x * cell + 4, oy + y * cell + 4, cell - 8, cell - 8, 8, 8)
p.setBrush(QColor("#ece9f5"))
p.drawRoundedRect(ox + cell + 4, oy + 2 * cell + 4, cell - 8, cell - 8, 8, 8)
p.end()
out = Path(__file__).with_name("icon.ico")
assert img.save(str(out), "ICO"), "Qt ICO writer missing"
print(out)
