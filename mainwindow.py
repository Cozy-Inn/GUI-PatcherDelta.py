import sys
import os
import subprocess
import ctypes
import winreg
import threading
import re
import shutil
import glob
import json
os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QFileDialog
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QObject, QEvent, Signal, QTimer
from ui_form import Ui_PatchWizard

def copy_game_files(src_copy_dir, dest_dir, target_data_sel, target_data_3):
    import os
    import shutil
    import ctypes
    import sys
    import tempfile

    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def try_copy():
        try:
            # Создаем структуру папок если нужно
            os.makedirs(os.path.join(dest_dir, 'lang'), exist_ok=True)
            os.makedirs(os.path.join(dest_dir, 'vid'), exist_ok=True)

            # Копируем все файлы
            shutil.copytree(src_copy_dir, dest_dir, dirs_exist_ok=True)
            shutil.copy2(target_data_sel, os.path.join(os.path.dirname(dest_dir), 'data.win'))
            shutil.copy2(target_data_3, os.path.join(dest_dir, 'data.win'))
            return True
        except PermissionError:
            return False

    if try_copy():
        return True

    if not is_admin():
        # Создаем временный скрипт для копирования с правами админа
        script = f"""
import os
import shutil

src = r'{src_copy_dir}'
dest = r'{dest_dir}'
file1 = r'{target_data_sel}'
file2 = r'{target_data_3}'

try:
    os.makedirs(os.path.join(dest, 'lang'), exist_ok=True)
    os.makedirs(os.path.join(dest, 'vid'), exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    shutil.copy2(file1, os.path.join(os.path.dirname(dest), 'data.win'))
    shutil.copy2(file2, os.path.join(dest, 'data.win'))
except Exception as e:
    print(f"Ошибка копирования: {e}")
    input("Нажмите Enter для выхода...")
    raise
"""

        with tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w') as f:
            f.write(script)
            temp_script = f.name

        try:
            # Запускаем с правами администратора
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, temp_script, None, 1
            )
            return True
        finally:
            try:
                os.unlink(temp_script)
            except:
                pass
    else:
        # Если уже админ, но копирование не удалось
        raise RuntimeError("Не удалось скопировать файлы даже с правами администратора")

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
        self.goTo("intro")

        # variables
        self.select_folder(State.selected_folder)
        self.ui.chooseBtn.clicked.connect(self.select_folder_diag)
        self.ui.dropFrame.default_drop_label = """<div style="text-align: center; width: 100%;"><span style="color: rgba(98, 98, 98, 1);">Перетащите иконку игры, чтобы указать путь к папке</span></div>"""
        self.ui.dropFrame.default_classic_mode_label = """<div style="text-align: center; width: 100%;"><a href="#">Не работает? Классический режим</a></div>\n"""

        # navigations
        self.ui.nextBtn_intro.clicked.connect(lambda: self.goTo("drop_link"))
        self.ui.nextBtn_path.clicked.connect(lambda: self.goTo("installation"))
        self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_success"))
        self.ui.nextBtn_drop.clicked.connect(lambda: self.goTo("installation"))
        self.ui.classic_mode_label.linkActivated.connect(lambda: self.goTo("select_path"))

        self.ui.backBtn_drop.clicked.connect(lambda: self.goTo("intro"))
        self.ui.backBtn_path.clicked.connect(lambda: self.goTo("drop_link"))

        # programm exits
        self.ui.endBtn_intro.clicked.connect(QApplication.quit)
        self.ui.endBtn_path.clicked.connect(QApplication.quit)
        self.ui.endBtn_install.clicked.connect(QApplication.quit)
        self.ui.endBtn_success.clicked.connect(QApplication.quit)
        self.ui.endBtn_fail.clicked.connect(QApplication.quit)
        self.ui.endBtn_drop.clicked.connect(QApplication.quit)

        # dropFrame init
        self.drop_filter = DropFilter(self.ui.dropFrame, self.handle_dropped_files)
        self.ui.dropFrame.installEventFilter(self.drop_filter)

        self.data_root = get_data_root()
        self.bin_folder = os.path.join(self.data_root, 'bin')
        self.patch_folder = os.path.join(self.data_root, 'patch')

        self.progress_changed.connect(self.ui.patch_progress.setValue)
        self.progress_percent = int(0)
        self.ui.version.setText(self.parse("version"))

        self.current_progress = 0
        self.target_progress = 0
        self.status_text = ""
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(5)
        self.progressRequested.connect(self.smoothPercentage)

    def parse(self, key):
        filename=f"{self.data_root}/info.txt"
        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key} ="):
                        # Получаем всё после '=' и убираем пробелы
                        value = line.split("=", 1)[1].strip()
                        return value
        except FileNotFoundError:
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
        path = os.path.abspath(path)
        _, _, free = shutil.disk_usage(path)
        free_mb = int(free / (1024 * 1024))
        return f"{free_mb:,}".replace(",", " ")

    def handle_dropped_files(self, filepaths):
        file = filepaths[0]
        file_lower = file.lower()
        folder_path = ""
        if sys.platform.startswith("win"):
            if file_lower.endswith(".exe"):
                folder_path = os.path.dirname(file)
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
                        print("Папка с .exe из ярлыка:", folder_path)
                    else:
                        print("Целевой файл ярлыка не .exe:", target_path)
                except ImportError:
                    print("pywin32 не установлен — не могу обработать .lnk")
                except Exception as e:
                    print("Ошибка чтения .lnk:", e)
            elif file_lower.endswith(".url"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        content = f.read().lower()
                        if "steam" in content:
                            folder_path = self.search_deltarune_steam_installations()
                        else:
                            print("Это .url, но не steam")
                except Exception as e:
                    print("Ошибка чтения .url:", e)
        elif sys.platform.startswith("linux"):
            print("Linux")
        elif sys.platform == "darwin":
            print("macOS")
        else:
            print(f"Неизвестная платформа: {sys.platform}")
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
        else:
            if (folder_path == State.selected_folder):
                return
            pushlogo = QPixmap(":/img/resources/drop_icon_err.png")
            self.ui.space_available_drop.setText("*Не выбран диск*")
            self.ui.space_available_path.setText("*Не выбран диск*")
            self.ui.drop_icon.setPixmap(pushlogo)
            self.ui.drop_label.setText("""<div style="text-align: center; width: 100%;"><span style="text-align: center;"><font size="4">Не удалось найти игру, попробуйте ещё раз</font></span></div>""")
            self.ui.classic_mode_label.setText("""<div style="text-align: center; width: 100%;"><a href="#">Классический режим</a></div>\n""")

    def select_folder_diag(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder:
            self.select_folder(folder)

    def search_deltarune_steam_installations(self):
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
                        fixed_path = os.path.normpath(path_match.group(1))
                        lib_path = os.path.join(fixed_path, "steamapps", "common")
                        paths.append(lib_path)
            except Exception as e:
                print(f"[ERROR] Ошибка при чтении libraryfolders.vdf: {e}")

            return paths


        steam_path = get_steam_path_from_registry()
        if not steam_path:
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
                        print(f"[FOUND] Найдена Deltarune: {full_path}")
                        self.select_folder(full_path)
                        return full_path
        if found_count == 0:
            print("[ERROR] Deltarune не найдена ни в одной из библиотек.")

    def smoothPercentage(self, newPercent, title):
        self.target_progress = int(newPercent)
        self.status_text = title
        self.updateProgress()
        print(f"[smoothPercentage] target: {self.target_progress}, title: {self.status_text}")
        if not self.timer.isActive():
            print("[smoothPercentage] starting timer")
            self.timer.start()

    def _tick(self):
        print(f"[tick] current={self.current_progress}, target={self.target_progress}")
        if self.current_progress < self.target_progress:
            self.current_progress += 1
            self.updateProgress()
        else:
            self.timer.stop()
            print("[_tick] Timer stopped")

    def updateProgress(self):
        print(f"[updateProgress] progress: {self.current_progress}, title: {self.status_text}")
        self.progress_changed.emit(self.current_progress)
        self.ui.install_percentage.setText(f"{self.current_progress}%")
        self.ui.install_status.setText(self.status_text)

    # STARTING PATCHING FROM HERE
    def start_patching_async(self):
        def patching_task():
            patcher_exe = os.path.join(self.data_root, "bin", "GMS-UTML-Patcher.exe")
            if sys.platform.startswith("win"):
                try:
                    self.progressRequested.emit(15, "Патчим выбор главы...")
                    data_win_1 = os.path.join(State.selected_folder, "data.win")
                    patch_file_1 = os.path.join(self.patch_folder, "ch_sel", "data.json")
                    result_file_1 = os.path.join(self.patch_folder, "data_sel.win")
                    subprocess.run([patcher_exe, "--data-path", data_win_1, "--patcher-file", patch_file_1, "--skip-hashcheck", "--output", result_file_1], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.progressRequested.emit(50, "Выбор главы пропатчен.")

                    self.progressRequested.emit(55, "Патчим третью главу...")
                    data_win_2 = os.path.join(State.selected_folder, "chapter3_windows", "data.win")
                    patch_file_2 = os.path.join(self.patch_folder, "ch3", "data3.json")
                    result_file_2 = os.path.join(self.patch_folder, "data_3.win")
                    subprocess.run([patcher_exe, "--data-path", data_win_2, "--patcher-file", patch_file_2, "--skip-hashcheck", "--output", result_file_2], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.progressRequested.emit(80, "Третья глава пропатчена.")

                    self.progressRequested.emit(85, "Копируем файлы...")

                    src_copy_dir = os.path.join(self.patch_folder, "copy", "chapter3")
                    dest_copy_dir = os.path.join(State.selected_folder, "chapter3_windows")
                    target_data_sel = os.path.join(State.selected_folder, "data.win")
                    target_data_3 = os.path.join(State.selected_folder, "chapter3_windows", "data.win")

                    copy_game_files(src_copy_dir, dest_copy_dir, target_data_sel, target_data_3)

                    self.progressRequested.emit(100, "Патчинг завершён.")
                    self.ui.nextBtn_install.setEnabled(True)
                except Exception as e:
                    print(str(e))
                    self.progressRequested.emit(0, f"Ошибка: {e}")
                    self.ui.error.setText(str(e))
                    self.goTo("end_fail")
            else:
                self.progressRequested.emit(0, "Патчинг доступен только на Windows.")

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
    widget = MainWindow()
    widget.setFixedSize(530, 400)
    widget.show()
    sys.exit(app.exec())
