from PySide6.QtWidgets import QMessageBox

def show_admin_warning():
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle("Предупреждение")
    msg.setText("Программа запущена с правами администратора")
    msg.setInformativeText(
        "Функция перетаскивания в приложение может работать некорректно.\n\n"
        "Рекомендуется перезапустить программу без прав администратора."
    )
    msg.setStandardButtons(QMessageBox.Ok)
    msg.setWindowFlags(Qt.WindowStaysOnTopHint)
    msg.exec()