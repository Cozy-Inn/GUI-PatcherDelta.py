from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def show_admin_warning():
    msg = QMessageBox()
    msg.setIconPixmap(QPixmap(":/img/resources/queen_sprite.png"))
    msg.setWindowTitle("Программа запущена от имени администратора")
    msg.setWindowIcon(QPixmap(":/icon/resources/cozy_inn.ico"))
    msg.setText('<span style="font-size:12pt; font-weight: 600">Обратите внимание!<br>Программа запущена с правами администратора.</span>')
    msg.setInformativeText(
        "Функция «Drag-and-drop» может работать некорректно. Гарантирована работа только Классического режима.\n"
        "Рекомендуется перезапустить программу без прав администратора."
    )
    msg.setStandardButtons(QMessageBox.Ok)
    msg.setWindowFlags(Qt.WindowStaysOnTopHint)
    msg.setStyleSheet("""
        QLabel {
            font-size: 10pt;
        }
    """)
    msg.exec()

def show_critical_error(title: str, subtitle: str = ""):
    msg = QMessageBox()
    msg.setIconPixmap(QPixmap(":/img/resources/queen_sprite_error.png"))
    msg.setWindowTitle("Критическая ошибка")
    msg.setText(f'<div style="font-size:12pt; font-weight: 600; height: 5px;">{title}</div><div style="height: 1px;"></div>')
    msg.setInformativeText(f"<div style='font-size: 10pt'>{subtitle}</div>")
    msg.setStandardButtons(QMessageBox.Ok)
    msg.setWindowFlags(Qt.WindowStaysOnTopHint)
    msg.exec()