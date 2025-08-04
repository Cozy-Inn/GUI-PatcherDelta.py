from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def show_admin_warning():
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle("Предупреждение")
    msg.setText('<span style="font-size:12pt; font-weight: 600">Обратите внимание!<br>Программа запущена с правами администратора.</span>')
    msg.setInformativeText(
        "Функция перетаскивания в приложение может работать некорректно.\n"
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