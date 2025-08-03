import sys
import os
import tempfile
import subprocess
import ctypes
import winreg
import threading
import re
import glob
import shutil

from copy_files import copy_game_files_win
from messageboxes import show_admin_warning

os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QFileDialog, QMessageBox
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QObject, QEvent, Signal, QTimer
from ui_form import Ui_PatchWizard

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_data_root():
    if getattr(sys, 'frozen', False):
        exe_path = os.path.dirname(sys.executable)
        data_root = os.path.join(exe_path, 'data')
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_root = os.path.join(script_dir, 'data')
    return data_root

class State:
    selected_folder = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\DELTARUNE"
    is_patch_applied = False

class MainWindow(QMainWindow):
    confirmation_requested = Signal(int, object)
    progress_changed = Signal(int)
    progressRequested = Signal(int, str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_PatchWizard()
        self.ui.setupUi(self)

        self.pages = {
            "intro": self.ui.intro,
            "drop_link": self.ui.drop_link,
            "select_path": self.ui.select_path,
            "installation": self.ui.installation,
            "end_success": self.ui.end_success,
            "end_fail": self.ui.end_fail
        }

        if (sys.platform.startswith("win")): 
            self.search_deltarune_steam_installations_win()
        
        self.goTo("intro")

        # variables
        self.select_folder(State.selected_folder)
        self.ui.chooseBtn.clicked.connect(self.select_folder_diag)
        self.ui.pathField.textChanged.connect(self.path_input_update)
        self.ui.dropFrame.default_drop_label = """<div style="text-align: center; width: 100%;"><span style="color: rgba(98, 98, 98, 1);">Перетащите иконку игры, чтобы указать путь к папке</span></div>"""
        self.ui.dropFrame.default_classic_mode_label = """<div style="text-align: center; width: 100%;"><a href="#">Не работает? Классический режим</a></div>\n"""

        # navigations
        self.ui.nextBtn_intro.clicked.connect(lambda: self.goTo("drop_link"))
        self.ui.nextBtn_path.clicked.connect(lambda: self.goTo("installation"))
        self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_success"))
        self.ui.nextBtn_drop.clicked.connect(lambda: self.goTo("installation"))
        self.ui.classic_mode_label.linkActivated.connect(lambda: self.goTo("select_path"))

        self.ui.backBtn_drop.clicked.connect(lambda: self.goTo("intro"))
        self.ui.backBtn_path.clicked.connect(lambda: self.goTo("intro"))

        # programm exits
        self.ui.endBtn_intro.clicked.connect(QApplication.quit)
        self.ui.endBtn_path.clicked.connect(QApplication.quit)
        self.ui.endBtn_install.clicked.connect(QApplication.quit)
        self.ui.endBtn_success.clicked.connect(self.on_finish_clicked)
        self.ui.endBtn_fail.clicked.connect(QApplication.quit)
        self.ui.endBtn_drop.clicked.connect(QApplication.quit)

        # dropFrame init
        self.drop_filter = DropFilter(self.ui.dropFrame, self.handle_dropped_files)
        self.ui.dropFrame.installEventFilter(self.drop_filter)

        # other stuff
        self.data_root = get_data_root()
        self.bin_folder = os.path.join(self.data_root, 'bin')
        self.patch_folder = os.path.join(self.data_root, 'patch')

        self.progress_changed.connect(self.ui.patch_progress.setValue)
        self.progress_percent = int(0)
        self.ui.version.setText(self.parseInfo("version"))

        self.current_progress = 0
        self.target_progress = 0
        self.status_text = ""
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(5)
        self.progressRequested.connect(self.smoothPercentage)

        self.ui.detailedlogs.setVisible(False)
        self.ui.dead_image.setVisible(False)
        self.ui.showDetailsBtn.clicked.connect(lambda: self.ui.detailedlogs.setVisible(not self.ui.detailedlogs.isVisible()))
        self.sendVerbose("Программа прошла этап инициализации")

    def on_finish_clicked(self):
        if self.ui.startDELTA.isChecked():
            self.launch_deltarune()
        QApplication.quit()

    def launch_deltarune(self):
        try:
            game_exe = os.path.join(State.selected_folder, "DELTARUNE.exe")

            if os.path.exists(game_exe):
                command = f'start "" "{game_exe}"'
                subprocess.Popen(command, cwd=State.selected_folder, shell=True)
            else:
                print("Файл DELTARUNE.exe не найден")
        except Exception as e:
            print(f"Ошибка при запуске игры: {e}")

    def sendVerbose(self, text: str):
        self.ui.detailedlogs.appendPlainText(text)
        scrollbar = self.ui.detailedlogs.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def parseInfo(self, key):
        filename=f"{self.data_root}/info.txt"
        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key} ="):
                        value = line.split("=", 1)[1].strip()
                        return value
        except FileNotFoundError:
            self.sendVerbose(f"Файл {filename} не найден.")
            print(f"Файл {filename} не найден.")
        return None


    def checkDELTARUNE(self, folder_path):
        for chapter in range(1, 5):
            chapter_dirs = glob.glob(os.path.join(folder_path, f"chapter{chapter}*"))
            if not chapter_dirs:
                return False
            found_data = False
            for ch_dir in chapter_dirs:
                data_files = glob.glob(os.path.join(ch_dir, "data.*"))
                if any(os.path.isfile(path) for path in data_files):
                    found_data = True
                    break
            if not found_data:
                return False
        return True

    def get_free_space_mb(self, path):
        try:
            path = os.path.abspath(path)
            drive, _ = os.path.splitdrive(path)

            if not drive:
                drive = os.sep

            _, _, free = shutil.disk_usage(drive)
            free_mb = int(free / (1024 * 1024))
            return f"{free_mb:,}".replace(",", " ")
        except Exception as e:
            print(e)
            return "???"

    def handle_dropped_files(self, filepaths):
        file = filepaths[0]
        file_lower = file.lower()
        folder_path = ""
        if sys.platform.startswith("win"):
            if file_lower.endswith(".exe"):
                folder_path = os.path.dirname(file)
                self.sendVerbose(f"Папка с .exe: {folder_path}")
                print("Папка с .exe:", folder_path)
            elif file_lower.endswith(".lnk"):
                try:
                    import pythoncom
                    from win32com.shell import shell
                    shortcut = pythoncom.CoCreateInstance(
                        shell.CLSID_ShellLink, None,
                        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink
                    )
                    persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
                    persist_file.Load(file)

                    target_path, _ = shortcut.GetPath(shell.SLGP_RAWPATH)

                    if target_path.endswith(".exe"):
                        folder_path = os.path.dirname(target_path)
                        self.sendVerbose(f"Папка с .exe из ярлыка: {folder_path}")
                        print("Папка с .exe из ярлыка:", folder_path)
                    else:
                        self.sendVerbose(f"Целевой файл ярлыка не .exe: {target_path}")
                        print("Целевой файл ярлыка не .exe:", target_path)
                except ImportError:
                    self.sendVerbose("pywin32 не установлен — не удалось обработать .lnk")
                    print("pywin32 не установлен — не удалось обработать .lnk")
                except Exception as e:
                    self.sendVerbose(f"Ошибка чтения .lnk: {e}")
                    print("Ошибка чтения .lnk:", e)
            elif file_lower.endswith(".url"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        content = f.read().lower()
                        if "steam" in content:
                            folder_path = self.search_deltarune_steam_installations_win()
                        else:
                            self.sendVerbose("Получен .url, но не steam")
                            print("Получен .url, но не steam")
                except Exception as e:
                    self.sendVerbose(f"Ошибка чтения .url: {e}")
                    print("Ошибка чтения .url:", e)
            else:
                # предположим что это папка
                folder_path = file
        elif sys.platform == "darwin":
            print("macOS")
        else:
            print(f"Неподдерживаемая платформа: {sys.platform}")
        self.select_folder(folder_path)
    def goTo(self, page_name: str):
            match (page_name):
                case "installation":
                    self.progress_changed.emit(int(0))
                    self.start_patching_async()
                    return self.ui.stackedWidget.setCurrentWidget(self.ui.installation)
                case "select_path":
                    if (self.checkDELTARUNE(State.selected_folder)):
                        self.ui.nextBtn_path.setEnabled(True)
                    self.ui.stackedWidget.setCurrentWidget(self.ui.select_path)
                    return

            page = self.pages.get(page_name)
            if page:
                self.ui.stackedWidget.setCurrentWidget(page)
            else:
                self.sendVerbose(f"Страница {page_name} не найдена!")
                print(f"Страница {page_name} не найдена!")

    def select_folder(self, folder_path):
        if (self.checkDELTARUNE(folder_path)):
            deltalogo = QPixmap(":/img/resources/drop_icon_game.png")
            self.ui.space_available_drop.setText(f"{self.get_free_space_mb(folder_path)} Мбайт")
            self.ui.space_available_path.setText(f"{self.get_free_space_mb(folder_path)} Мбайт")
            self.ui.drop_icon.setPixmap(deltalogo)
            self.ui.drop_label.setText(f"""<div style="text-align: center; width: 100%;"><span style="text-align: center;"><font size="4">{folder_path}</font></span></div>""")
            self.ui.classic_mode_label.setText("""<div style="text-align: center; width: 100%;"><a href="#">Неправильно? Классический режим</a></div>\n""")
            self.ui.pathField.setText(folder_path)
            State.selected_folder = folder_path
            self.ui.nextBtn_drop.setEnabled(True)
            self.ui.nextBtn_path.setEnabled(True)
        else:
            if (folder_path == State.selected_folder):
                return
            pushlogo = QPixmap(":/img/resources/drop_icon_err.png")
            self.ui.space_available_drop.setText("*Не выбран диск*")
            self.ui.space_available_path.setText(f"{self.get_free_space_mb(folder_path)} Мбайт")
            self.ui.drop_icon.setPixmap(pushlogo)
            self.ui.drop_label.setText("""<div style="text-align: center; width: 100%;"><span style="text-align: center;"><font size="4">Не удалось найти игру, попробуйте ещё раз</font></span></div>""")
            self.ui.classic_mode_label.setText("""<div style="text-align: center; width: 100%;"><a href="#">Классический режим</a></div>\n""")
            self.ui.nextBtn_drop.setEnabled(False)
            self.ui.nextBtn_path.setEnabled(False)

    def select_folder_diag(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder:
            self.ui.pathField.setText(folder)
            self.select_folder(folder)

    def path_input_update(self, text):
        if text:
            self.ui.pathField.setText(text)
            self.select_folder(text)

    def search_deltarune_steam_installations_win(self):
        def get_steam_path_from_registry():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                    return steam_path
            except FileNotFoundError:
                return None

        def get_steam_library_paths(steam_path):
            paths = [os.path.join(steam_path, "steamapps", "common")]
            vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")

            if not os.path.exists(vdf_path):
                return paths

            try:
                with open(vdf_path, "r", encoding="utf-8") as f:
                    content = f.read()
                matches = re.findall(r'"\d+"\s*\{([^}]+)\}', content, re.MULTILINE | re.DOTALL)

                for block in matches:
                    path_match = re.search(r'"path"\s+"([^"]+)"', block)
                    if path_match:
                        raw_path = path_match.group(1)
                        try:
                            fixed_path = os.path.abspath(os.path.normpath(raw_path))
                            if os.path.exists(fixed_path):
                                lib_path = os.path.join(fixed_path, "steamapps", "common")
                                if os.path.exists(lib_path):
                                    paths.append(os.path.realpath(lib_path))
                                else:
                                    print(f"[WARN] Папка steamapps/common не найдена в: {fixed_path}")
                            else:
                                print(f"[WARN] Путь не существует: {raw_path} → {fixed_path}")
                        except Exception as e:
                            print(f"[ERROR] Ошибка обработки пути '{raw_path}': {str(e)}")
            except Exception as e:
                self.sendVerbose(f"[ERROR] Ошибка при чтении libraryfolders.vdf: {e}")
                print(f"[ERROR] Ошибка при чтении libraryfolders.vdf: {e}")

            return paths


        steam_path = get_steam_path_from_registry()
        if not steam_path:
            self.sendVerbose("[ERROR] Steam не найден в реестре.")
            print("[ERROR] Steam не найден в реестре.")
            return []

        library_paths = get_steam_library_paths(steam_path)

        found_count = 0
        for lib_path in library_paths:
            if not os.path.exists(lib_path):
                continue

            for folder in os.listdir(lib_path):
                full_path = os.path.join(lib_path, folder)
                if os.path.isdir(full_path):
                    if self.checkDELTARUNE(full_path):
                        self.sendVerbose(f"[FOUND] Найдена Deltarune: {full_path}")
                        print(f"[FOUND] Найдена Deltarune: {full_path}")
                        self.select_folder(full_path)
                        return full_path
        if found_count == 0:
            self.sendVerbose("[ERROR] Deltarune не найдена ни в одной из библиотек.")
            print("[ERROR] Deltarune не найдена ни в одной из библиотек.")

    def smoothPercentage(self, newPercent, title):
        self.sendVerbose(title)
        self.target_progress = int(newPercent)
        self.status_text = title
        self.updateProgress()
        if not self.timer.isActive():
            self.timer.start()

    def _tick(self):
        if self.current_progress < self.target_progress:
            self.current_progress += 1
            self.updateProgress()
        else:
            self.timer.stop()

    def updateProgress(self):
        self.progress_changed.emit(self.current_progress)
        self.ui.install_percentage.setText(f"{self.current_progress}%")
        self.ui.install_status.setText(self.status_text)

    # STARTING PATCHING FROM HERE
    def start_patching_async(self):


        def handle_confirmation(error_code, callback):
            msg = QMessageBox()
            msg.setWindowTitle("Внимание!")
            msg.setIcon(QMessageBox.Warning)

            if error_code == 203:
                msg.setText("Версия перевода неактуальна!")
                msg.setInformativeText("Хотите продолжить установку?")
            elif error_code == 204:
                msg.setText("Обнаружена модификация!")
                msg.setInformativeText("Возможно вы уже установили перевод. Всё равно продолжить?")

            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            result = msg.exec() == QMessageBox.Yes
            callback(result)

        self.confirmation_requested.connect(handle_confirmation)

        def patching_task():
            patcher_exe = os.path.join(self.data_root, "bin", "GMS-UTML-Patcher.exe")
            if not sys.platform.startswith("win"):
                self.progressRequested.emit(0, "Патчинг доступен только на Windows")
                return

            try:
                self.progressRequested.emit(15, "Патчим выбор главы...")
                
                original_data_sel = os.path.join(State.selected_folder, "data.win")
                patch_file_sel = os.path.join(self.patch_folder, "ch_sel", "data.json")
                result_data_sel = os.path.join(self.patch_folder, "data_sel.win")
                try:
                    subprocess.run([
                        patcher_exe,
                        "--data-path", original_data_sel,
                        "--patcher-file", patch_file_sel,
                        "--output", result_data_sel
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                except subprocess.CalledProcessError as e:
                    if e.returncode in (203, 204):
                        from threading import Event
                        event = Event()
                        user_choice = [None]

                        def callback(result):
                            user_choice[0] = result
                            event.set()
                        self.confirmation_requested.emit(e.returncode, callback)

                        event.wait(180)

                        if not user_choice[0]:
                            self.progressRequested.emit(0, "Установка отменена")
                            self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_fail"))
                            self.ui.error.setText("Отмена пользователем")
                            self.ui.nextBtn_install.setEnabled(True)
                            return
                        subprocess.run([
                            patcher_exe,
                            "--data-path", original_data_sel,
                            "--patcher-file", patch_file_sel,
                            "--skip-timecheck",
                            "--output", result_data_sel
                        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)

                    else:
                        raise

                self.progressRequested.emit(30, "Выбор главы пропатчен")

                self.progressRequested.emit(30, "Патчим третью главу...")
                original_ch3_data = os.path.join(State.selected_folder, "chapter3_windows", "data.win")
                ch3_patch = os.path.join(self.patch_folder, "ch3", "data3.json")
                result_data_3 = os.path.join(self.patch_folder, "data_3.win")
                try:
                    subprocess.run([
                        patcher_exe,
                        "--data-path", original_ch3_data,
                        "--patcher-file", ch3_patch,
                        "--output", result_data_3
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                except subprocess.CalledProcessError as e:
                    if e.returncode in (203, 204):
                        event = Event()
                        user_choice = [None]

                        def callback(result):
                            user_choice[0] = result
                            event.set()
                        self.confirmation_requested.emit(e.returncode, callback)

                        event.wait(180)

                        if not user_choice[0]:
                            self.progressRequested.emit(0, "Установка отменена")
                            self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_fail"))
                            self.ui.error.setText("Отмена пользователем")
                            self.ui.nextBtn_install.setEnabled(True)
                            return
                        subprocess.run([
                            patcher_exe,
                            "--data-path", original_ch3_data,
                            "--patcher-file", ch3_patch,
                            "--skip-timecheck",
                            "--output", result_data_3
                        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        raise

                self.progressRequested.emit(70, "Третья глава пропатчена")

                self.progressRequested.emit(70, "Копируем файлы...")
                src_dir = os.path.join(self.patch_folder, "copy", "chapter3")
                dest_dir = os.path.join(State.selected_folder, "chapter3_windows")

                copy_config = { "folders": {}, "files": {}}

                copy_config["folders"][src_dir] = dest_dir
                copy_config["files"][result_data_3] = original_ch3_data
                copy_config["files"][result_data_sel] = original_data_sel

                bat_file = copy_game_files_win(
                    copy_config, self.sendVerbose
                )

                self.progressRequested.emit(95, "Удаляем временные файлы...")

                temp_files = [
                    result_data_sel,
                    result_data_3,
                    bat_file
                ]
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except Exception as e:
                        print(f"Не удалось удалить временный файл {temp_file}: {e}")

                self.progressRequested.emit(100, "Патчинг завершён!")
                self.ui.nextBtn_install.setEnabled(True)
            except Exception as e:
                error_msg = str(e)
                print(f"Ошибка установки: {error_msg}")
                self.progressRequested.emit(0, f"Ошибка: {error_msg}")
                self.ui.error.setText(error_msg)
                self.ui.detailedlogs.setVisible(True)
                self.ui.dead_image.setVisible(True)
                self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_fail"))
                self.ui.nextBtn_install.setEnabled(True)


        threading.Thread(target=patching_task, daemon=True).start()





class DropFilter(QObject):
    def __init__(self, parent, on_drop_callback):
        super().__init__(parent)
        self.on_drop_callback = on_drop_callback

    def eventFilter(self, obj, event):
        pushlogo = QPixmap(":/img/resources/drop_icon.png")
        drop_icon = obj.findChild(QLabel, "drop_icon")
        drop_label = obj.findChild(QLabel, "drop_label")
        classic_label = obj.findChild(QLabel, "classic_mode_label")
        match event.type():
            case QEvent.DragEnter:
                obj.setStyleSheet("#dropFrame { background-color: rgba(230, 230, 230, 1); }")
                drop_icon.setPixmap(pushlogo)
                drop_label.setText("""<div style="text-align: center; width: 100%;"><span></span></div>""")
                classic_label.setText("")
                if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True

            case QEvent.DragLeave:
                obj.setStyleSheet("")
                drop_label.setText(obj.default_drop_label)
                classic_label.setText(obj.default_classic_mode_label)
                return True

            case QEvent.Drop:
                obj.setStyleSheet("")
                drop_label.setText(obj.default_drop_label)
                classic_label.setText(obj.default_classic_mode_label)
                if event.mimeData().hasUrls():
                    files = [url.toLocalFile() for url in event.mimeData().urls()]
                    self.on_drop_callback(files)
                    event.acceptProposedAction()
                return True

            case _:
                return False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if is_admin():
        show_admin_warning()

    widget = MainWindow()
    widget.setFixedSize(530, 400)
    widget.show()
    sys.exit(app.exec())
