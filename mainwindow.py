import sys
import os
import subprocess
import threading
import re
import glob
import shutil
from pathlib import Path
from time import sleep
from copy_files import copy_game_files_win
from copy_files import copy_game_files_mac
from messageboxes import show_admin_warning, is_admin, show_critical_error

if sys.platform.startswith("win"):
    os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"
else:
    os.environ["QT_QPA_PLATFORM"] = "cocoa:darkmode=0"

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QFileDialog, QMessageBox
from PySide6.QtGui import QPixmap, QMovie, QIcon
from PySide6.QtCore import QObject, QEvent, Signal, QTimer, Qt, QMetaObject

def get_data_root():
    if getattr(sys, 'frozen', False):
        exe_path = os.path.dirname(sys.executable)
        data_root = os.path.join(exe_path, 'data')
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_root = os.path.join(script_dir, 'data')
    return data_root

class State:
    selected_folder = ""
    if sys.platform == "darwin":
        # Путь по умолчанию для macOS
        selected_folder = os.path.expanduser("~/Library/Application Support/Steam/steamapps/common/DELTARUNE/DELTARUNE.app/Contents/Resources")
    else:
        # Путь по умолчанию для Windows
        selected_folder = os.path.join(
            "C:\\", "Program Files (x86)", "Steam", "steamapps", "common", "DELTARUNE"
        )
    is_patch_applied = False

class MainWindow(QMainWindow):
    confirmation_requested = Signal(int, object)
    progress_changed = Signal(int)
    progressRequested = Signal(int, str)
    def __init__(self, parent=None):
        super().__init__(parent)

        # импорты перенесены сюда дабы оптимизировать пространство и время загрузки
        if sys.platform.startswith("win"):
            from ui_form import Ui_PatchWizard as Ui_PatchWizardWin
            self.ui = Ui_PatchWizardWin()
        else:
            from ui_form_mac import Ui_PatchWizard as Ui_PatchWizardMac
            self.ui = Ui_PatchWizardMac()

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
        elif (sys.platform.startswith("darwin")): 
            self.search_deltarune_steam_installations_mac()
        
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
        if (sys.platform.startswith("darwin")): 
            self.patch_folder = os.path.join(self.data_root, '../../Resources/data/patch')
        
        if sys.platform == "darwin":
            patcher_path = os.path.join(self.bin_folder, "mac", "GMS-UTML-Patcher")
            if os.path.exists(patcher_path):
                try:
                    os.chmod(patcher_path, 0o755)  # Даем права на выполнение
                    self.sendVerbose(f"Установлены права на выполнение для {patcher_path}")
                except Exception as e:
                    self.sendVerbose(f"Ошибка при установке прав: {e}")
            lib_path = os.path.join(self.bin_folder, "mac", "Magick.Native-Q8-x64.dll.dylib")
            if os.path.exists(lib_path):
                try:
                    os.chmod(lib_path, 0o755)  # Даем права на выполнение
                    self.sendVerbose(f"Установлены права на выполнение для {lib_path}")
                except Exception as e:
                    self.sendVerbose(f"Ошибка при установке прав: {e}")

        if not os.path.isdir(self.bin_folder) or not os.path.isdir(self.patch_folder):
            show_critical_error("Отсутствуют необходимые для установщика папки.", "Отсутвует папка <code>data</code>, <code>data/bin</code> или <code>data/patch</code>")
            sys.exit(0)

        self.progress_changed.connect(self.ui.patch_progress.setValue)
        self.progress_percent = int(0)
        self.ui.version.setText(self.parseInfo("version"))

        self.current_progress = 0
        self.target_progress = 0
        self.status_text = ""
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(5)
        self.progressRequested.connect(self.smoothPercentage, Qt.QueuedConnection)

        self.ui.detailedlogs.setVisible(False)
        self.ui.showDetailsBtn.clicked.connect(lambda: self.ui.detailedlogs.setVisible(not self.ui.detailedlogs.isVisible()))
        self.sendVerbose("Программа прошла этап инициализации")

        ralsei = QMovie(":/img/resources/lytaya_animka_ralsei2009.gif")
        self.ui.dead_image.setMovie(ralsei)
        ralsei.start()

    def invoke_gui(self, fn, *args, **kwargs):
        QTimer.singleShot(0, lambda: fn(*args, **kwargs))

    def on_finish_clicked(self):
        if self.ui.startDELTA.isChecked():
            self.launch_deltarune()
        QApplication.quit()

    def launch_deltarune(self):
        try:
            if sys.platform.startswith("win"):
                game_exe = os.path.join(State.selected_folder, "DELTARUNE.exe")

                if os.path.exists(game_exe):
                    command = f'start "" "{game_exe}"'
                    subprocess.Popen(command, cwd=State.selected_folder, shell=True)
                else:
                    print("Файл DELTARUNE.exe не найден")
            elif sys.platform == "darwin":
                # Если путь заканчивается на "Contents/Resources", поднимаемся на 2 уровня вверх
                path = Path(State.selected_folder)
                if path.parts[-2:] == ("Contents", "Resources"):
                    app_path = str(path.parent.parent)  # Получаем путь к .app
                else:
                    app_path = os.path.join(State.selected_folder, "DELTARUNE.app")

                if os.path.exists(app_path):
                    command = ["open", app_path]
                    subprocess.Popen(command)
                    print(f"Запускаем игру из: {app_path}")
                else:
                    print(f"Файл DELTARUNE.app не найден по пути: {app_path}")
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

    def fix_mac_permissions(self, file_path):
        """Убирает quarantine атрибут и дает права на выполнение"""
        try:
            # Удаляем quarantine атрибут
            subprocess.run(["xattr", "-d", "com.apple.quarantine", file_path], 
                        check=True, stderr=subprocess.DEVNULL)
            
            # Даем права на выполнение
            subprocess.run(["chmod", "+x", file_path], 
                        check=True, stderr=subprocess.DEVNULL)
            
            return True
        except subprocess.CalledProcessError:
            return False


    def checkDELTARUNE(self, folder_path):
        # Проверяем, является ли это папкой Resources внутри .app
        path = Path(folder_path)
        if sys.platform == "darwin" and path.parts[-2:] == ("Contents", "Resources"):
            # Ищем родительский .app
            app_path = path.parent.parent
            if app_path.suffix == ".app" and app_path.is_dir():
                folder_path = str(app_path)
        
        for chapter in range(1, 5):
            if sys.platform == "darwin":
                chapter_dirs = glob.glob(os.path.join(folder_path, "Contents", "Resources", f"chapter{chapter}*"))
            else:
                chapter_dirs = glob.glob(os.path.join(folder_path, f"chapter{chapter}*"))
            
            if not chapter_dirs:
                return False
            
            found_data = False
            for ch_dir in chapter_dirs:
                if sys.platform == "darwin":
                    data_files = glob.glob(os.path.join(ch_dir, "game.*"))
                else:
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
            path = Path(file)
            # Если перетащили сам .app
            if path.suffix == ".app" and path.is_dir():
                resources_path = path / "Contents" / "Resources"
                if resources_path.exists():
                    icons_path = resources_path / "shortcut.icns"
                    if icons_path.exists():
                        resources_path = self.search_deltarune_steam_installations_mac()
                    folder_path = str(resources_path)
                    self.sendVerbose(f"Папка Resources найдена: {folder_path}")
                    print(f"Папка Resources найдена: {folder_path}")
                else:
                    folder_path = str(path)
                    self.sendVerbose(f"Папка Resources не найдена, используем .app: {folder_path}")
                    print(f"Папка Resources не найдена, используем .app: {folder_path}")
            # Если перетащили что-то внутри .app
            else:
                # Ищем .app в родительских папках
                app_path = None
                for parent in path.parents:
                    if parent.suffix == ".app" and parent.is_dir():
                        app_path = parent
                        break
                
                if app_path:
                    resources_path = app_path / "Contents" / "Resources"
                    if resources_path.exists():
                        folder_path = str(resources_path)
                        self.sendVerbose(f"Найден .app в родителях с Resources: {folder_path}")
                        print(f"Найден .app в родителях с Resources: {folder_path}")
                    else:
                        folder_path = str(app_path)
                        self.sendVerbose(f"Найден .app без Resources: {folder_path}")
                        print(f"Найден .app без Resources: {folder_path}")
                else:
                    # Проверяем, существует ли .app с таким же именем
                    app_candidate = path.with_suffix(".app")
                    if app_candidate.is_dir():
                        resources_path = app_candidate / "Contents" / "Resources"
                        if resources_path.exists():
                            folder_path = str(resources_path)
                            self.sendVerbose(f"Добавлен .app к пути с Resources: {folder_path}")
                            print(f"Добавлен .app к пути с Resources: {folder_path}")
                        else:
                            folder_path = str(app_candidate)
                            self.sendVerbose(f"Добавлен .app без Resources: {folder_path}")
                            print(f"Добавлен .app без Resources: {folder_path}")
                    else:
                        folder_path = str(path)
                        self.sendVerbose(f"Просто используем переданный путь: {folder_path}")
                        print(f"Просто используем переданный путь: {folder_path}")
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
        if text and text != State.selected_folder:
            self.ui.pathField.setText(text)
            self.select_folder(text)

    def search_deltarune_steam_installations_win(self):
        def get_steam_path_from_registry():
            try:
                import winreg
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
                full_path = str(Path(os.path.join(lib_path, folder)).resolve(strict=False))
                if os.path.isdir(full_path):
                    if self.checkDELTARUNE(full_path):
                        self.sendVerbose(f"[FOUND] Найдена Deltarune: {full_path}")
                        print(f"[FOUND] Найдена Deltarune: {full_path}")
                        self.select_folder(full_path)
                        return full_path
        if found_count == 0:
            self.sendVerbose("[ERROR] Deltarune не найдена ни в одной из библиотек.")
            print("[ERROR] Deltarune не найдена ни в одной из библиотек.")

    def search_deltarune_steam_installations_mac(self):
        """Поиск установленной через Steam игры DELTARUNE на macOS"""
        steam_paths = [
            os.path.expanduser("~/Library/Application Support/Steam"),  # Основная папка Steam
            "/Applications/Steam.app/Contents/MacOS/steamapps"  # Альтернативное расположение
        ]
        
        # Дополнительные возможные пути библиотек Steam
        library_folders = []
        for steam_path in steam_paths:
            if os.path.exists(steam_path):
                # Проверяем файл libraryfolders.vdf
                vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
                if os.path.exists(vdf_path):
                    try:
                        with open(vdf_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        # Ищем пути в libraryfolders.vdf
                        matches = re.findall(r'"path"\s+"([^"]+)"', content)
                        for match in matches:
                            lib_path = os.path.join(match, "steamapps", "common")
                            if os.path.exists(lib_path):
                                library_folders.append(lib_path)
                    except Exception as e:
                        self.sendVerbose(f"Ошибка чтения libraryfolders.vdf: {e}")
                        print(f"Ошибка чтения libraryfolders.vdf: {e}")
        
        # Проверяем все возможные пути
        for lib_path in library_folders + [os.path.join(p, "steamapps", "common") for p in steam_paths]:
            if not os.path.exists(lib_path):
                continue
                    
            # Проверяем .app версию
            deltarune_app = os.path.join(lib_path, "DELTARUNE", "DELTARUNE.app")
            if os.path.exists(deltarune_app):
                resources_path = os.path.join(deltarune_app, "Contents", "Resources")
                if os.path.exists(resources_path):
                    if self.checkDELTARUNE(resources_path):
                        self.sendVerbose(f"Найдена Deltarune.app: {deltarune_app}")
                        print(f"Найдена Deltarune.app: {deltarune_app}")
                        self.select_folder(resources_path)
                        return resources_path
        
        self.sendVerbose("Deltarune не найдена в Steam-библиотеках")
        print("Deltarune не найдена в Steam-библиотеках")
        return None

    # update percentage
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
        if threading.current_thread() is not threading.main_thread():
            return QMetaObject.invokeMethod(self, lambda: self.updateProgress(), Qt.QueuedConnection)
        self.progress_changed.emit(self.current_progress)
        self.ui.install_percentage.setText(f"{self.current_progress}%")
        self.ui.install_status.setText(self.status_text)

    # STARTING PATCHING FROM HERE
    def start_patching_async(self):
        warn_msg_shown = False

        def handle_confirmation(error_code, callback):
            nonlocal warn_msg_shown
            if warn_msg_shown: 
                return callback(True)
            warn_msg_shown = True

            msg = QMessageBox()
            msg.setWindowTitle("Внимание!")
            msg.setIconPixmap(QPixmap(":/img/resources/mnogo_voprosoff_warning.png"))

            yes_btn = msg.addButton("Продолжить", QMessageBox.AcceptRole)
            no_btn = msg.addButton("Отменить", QMessageBox.RejectRole)
            if error_code == 206:
                msg.setText('<span style="font-size:12pt; font-weight: 600">Ваша версия игры устарела!</span>')
                msg.setInformativeText("Если вы продолжите установку, то игра почти гарантированно не будет работать!\nВсё равно продолжить установку?")
            elif error_code == 205:
                msg.setText('<span style="font-size:12pt; font-weight: 600">Версия перевода неактуальна!</span>')
                msg.setInformativeText("Если вы продолжите установку, то игра почти гарантированно не будет работать!\nВсё равно продолжить установку?")
            elif error_code == 204:
                msg.setText('<span style="font-size:12pt; font-weight: 600">Обнаружена модификация!</span>')
                msg.setInformativeText("Возможно вы уже установили перевод. Всё равно продолжить?")
            
            msg.setStyleSheet("""
                QLabel {
                    font-size: 10pt;
                }
            """)
            msg.exec()

            result = msg.clickedButton() == yes_btn
            callback(result)

        self.confirmation_requested.connect(handle_confirmation, Qt.QueuedConnection)

        def patching_task():
            if sys.platform.startswith("win"):
                patcher_exe = os.path.join(self.data_root, "bin", "win", "GMS-UTML-Patcher.exe")
                try:
                    self.progressRequested.emit(0, "Патчим выбор главы...")
                    
                    original_data_sel = os.path.join(State.selected_folder, "data.win")
                    bak_data_sel = os.path.join(State.selected_folder, "data.orig.win")
                    patch_file_sel = os.path.join(self.patch_folder, "ch_sel", "data.win.json")
                    result_data_sel = os.path.join(self.patch_folder, "data_sel.win")
                    try:
                        subprocess.run([
                            patcher_exe,
                            "--data-path", original_data_sel,
                            "--patcher-file", patch_file_sel,
                            "--output", result_data_sel
                        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
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
                    self.progressRequested.emit(5, "Выбор главы пропатчен")

                    self.progressRequested.emit(5, "Патчим третью главу...")
                    original_ch3_data = os.path.join(State.selected_folder, "chapter3_windows", "data.win")
                    bak_ch3_data = os.path.join(State.selected_folder, "chapter3_windows", "data.orig.win")
                    ch3_patch = os.path.join(self.patch_folder, "ch3", "data.win.json")
                    result_data_3 = os.path.join(self.patch_folder, "data_3.win")
                    try:
                        subprocess.run([
                            patcher_exe,
                            "--data-path", original_ch3_data,
                            "--patcher-file", ch3_patch,
                            "--output", result_data_3
                        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
                            print(e.returncode)
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
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

                    self.progressRequested.emit(45, "Третья глава пропатчена")

                    self.progressRequested.emit(45, "Патчим четвёртую главу...")

                    original_ch4_data = os.path.join(State.selected_folder, "chapter4_windows", "data.win")
                    bak_ch4_data = os.path.join(State.selected_folder, "chapter4_windows", "data.orig.win")
                    ch4_patch = os.path.join(self.patch_folder, "ch4", "data.win.json")
                    result_data_4 = os.path.join(self.patch_folder, "data_4.win")
                    try:
                        subprocess.run([
                            patcher_exe,
                            "--data-path", original_ch4_data,
                            "--patcher-file", ch4_patch,
                            "--output", result_data_4
                        ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
                            print(e.returncode)
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
                                return
                            subprocess.run([
                                patcher_exe,
                                "--data-path", original_ch4_data,
                                "--patcher-file", ch4_patch,
                                "--skip-timecheck",
                                "--output", result_data_4
                            ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            raise

                    self.progressRequested.emit(75, "Четвёртая глава пропатчена.")
                    
                    self.progressRequested.emit(75, "Копируем файлы...")
                    ch3_src_dir = os.path.join(self.patch_folder, "copy", "chapter3")
                    ch3_dest_dir = os.path.join(State.selected_folder, "chapter3_windows")
                    ch4_src_dir = os.path.join(self.patch_folder, "copy", "chapter4")
                    ch4_dest_dir = os.path.join(State.selected_folder, "chapter4_windows")
                    ru_data_file = os.path.join(self.patch_folder, "copy", "ru_data.json")
                    ru_data_file_dest = os.path.join(State.selected_folder, "ru_data.json")

                    copy_config = { "folders": {}, "files": {}}

                    copy_config["folders"][ch3_src_dir] = ch3_dest_dir
                    copy_config["folders"][ch4_src_dir] = ch4_dest_dir

                    if not os.path.exists(bak_ch3_data):
                        copy_config["files"][original_ch3_data] = bak_ch3_data

                    if not os.path.exists(bak_ch4_data):
                        copy_config["files"][original_ch4_data] = bak_ch4_data

                    if not os.path.exists(bak_data_sel):
                        copy_config["files"][original_data_sel] = bak_data_sel

                    copy_config["files"][result_data_3] = original_ch3_data
                    copy_config["files"][result_data_4] = original_ch4_data
                    copy_config["files"][result_data_sel] = original_data_sel
                    copy_config["files"][ru_data_file] = ru_data_file_dest


                    bat_file = copy_game_files_win(
                        copy_config, lambda msg: self.invoke_gui(lambda: self.sendVerbose(msg))
                    )

                    self.progressRequested.emit(95, "Удаляем временные файлы...")

                    temp_files = [
                        result_data_sel,
                        result_data_3,
                        result_data_4,
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
                    self.ui.dead_image.setPixmap(QPixmap(":/img/resources/ralsei_down.png"))

                    self.ui.nextBtn_install.clicked.connect(lambda: self.goTo("end_fail"))
                    self.ui.nextBtn_install.setEnabled(True)
            elif sys.platform == "darwin":
                patcher_bin = os.path.join(self.data_root, "bin", "mac", "GMS-UTML-Patcher")
                try:
                    if not os.path.exists(patcher_bin):
                        raise FileNotFoundError(f"Файл патчера не найден: {patcher_bin}")

                    try:
                        subprocess.run(["xattr", "-d", "com.apple.quarantine", patcher_bin], check=True)
                        subprocess.run(["chmod", "755", patcher_bin], check=True)
                    except subprocess.CalledProcessError as e:
                        self.sendVerbose(f"Не удалось исправить права: {e}")

                    self.progressRequested.emit(0, "Патчим выбор главы...")
                    
                    original_data_sel = os.path.join(State.selected_folder, "game.ios")
                    bak_data_sel = os.path.join(State.selected_folder, "game.orig.ios")
                    patch_file_sel = os.path.join(self.patch_folder, "ch_sel", "data.mac.json")
                    result_data_sel = os.path.join(self.patch_folder, "game_sel.ios")
                    try:
                        subprocess.run([
                            patcher_bin,
                            "--data-path", original_data_sel,
                            "--patcher-file", patch_file_sel,
                            "--output", result_data_sel
                        ], check=True)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
                                return
                            subprocess.run([
                                patcher_bin,
                                "--data-path", original_data_sel,
                                "--patcher-file", patch_file_sel,
                                "--skip-timecheck",
                                "--output", result_data_sel
                            ], check=True)
                        else:
                            raise
                    self.progressRequested.emit(5, "Выбор главы пропатчен")

                    self.progressRequested.emit(5, "Патчим третью главу...")
                    original_ch3_data = os.path.join(State.selected_folder, "chapter3_mac", "game.ios")
                    bak_ch3_data = os.path.join(State.selected_folder, "chapter3_mac", "game.orig.ios")
                    ch3_patch = os.path.join(self.patch_folder, "ch3", "data.mac.json")
                    result_data_3 = os.path.join(self.patch_folder, "game_3.ios")
                    try:
                        subprocess.run([
                            patcher_bin,
                            "--data-path", original_ch3_data,
                            "--patcher-file", ch3_patch,
                            "--output", result_data_3
                        ], check=True)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
                                return
                            subprocess.run([
                                patcher_bin,
                                "--data-path", original_ch3_data,
                                "--patcher-file", ch3_patch,
                                "--skip-timecheck",
                                "--output", result_data_3
                            ], check=True)
                        else:
                            raise

                    self.progressRequested.emit(45, "Третья глава пропатчена")

                    self.progressRequested.emit(45, "Патчим четвёртую главу...")
                    original_ch4_data = os.path.join(State.selected_folder, "chapter4_mac", "game.ios")
                    bak_ch4_data = os.path.join(State.selected_folder, "chapter4_mac", "game.orig.ios")
                    ch4_patch = os.path.join(self.patch_folder, "ch4", "data.mac.json")
                    result_data_4 = os.path.join(self.patch_folder, "game_4.ios")
                    try:
                        subprocess.run([
                            patcher_bin,
                            "--data-path", original_ch4_data,
                            "--patcher-file", ch4_patch,
                            "--output", result_data_4
                        ], check=True)
                    except subprocess.CalledProcessError as e:
                        if e.returncode in (204, 205, 206):
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
                                self.invoke_gui(self.ui.nextBtn_install.clicked.connect, lambda: self.goTo("end_fail"))
                                self.invoke_gui(self.ui.error.setText, "Отмена пользователем")
                                self.invoke_gui(self.ui.nextBtn_install.setEnabled, True)
                                return
                            subprocess.run([
                                patcher_bin,
                                "--data-path", original_ch4_data,
                                "--patcher-file", ch4_patch,
                                "--skip-timecheck",
                                "--output", result_data_4
                            ], check=True)
                        else:
                            raise
                    self.progressRequested.emit(75, "Четвёртая глава пропатчена")

                    self.progressRequested.emit(75, "Копируем файлы...")
                    ch3_src_dir = os.path.join(self.patch_folder, "copy", "chapter3")
                    ch3_dest_dir = os.path.join(State.selected_folder, "chapter3_mac")
                    ch4_src_dir = os.path.join(self.patch_folder, "copy", "chapter4")
                    ch4_dest_dir = os.path.join(State.selected_folder, "chapter4_mac")
                    ru_data_file = os.path.join(self.patch_folder, "copy", "ru_data.json")
                    ru_data_file_dest = os.path.join(State.selected_folder, "ru_data.json")

                    copy_config = { "folders": {}, "files": {}}

                    copy_config["folders"][ch3_src_dir] = ch3_dest_dir
                    copy_config["folders"][ch4_src_dir] = ch4_dest_dir

                    if not os.path.exists(bak_ch3_data):
                        copy_config["files"][original_ch3_data] = bak_ch3_data

                    if not os.path.exists(bak_ch4_data):
                        copy_config["files"][original_ch4_data] = bak_ch4_data
                    
                    if not os.path.exists(bak_data_sel):
                        copy_config["files"][original_data_sel] = bak_data_sel
                    
                    copy_config["files"][result_data_3] = original_ch3_data
                    copy_config["files"][result_data_4] = original_ch4_data
                    copy_config["files"][result_data_sel] = original_data_sel
                    copy_config["files"][ru_data_file] = ru_data_file_dest

                    copy_game_files_mac(
                        copy_config, 
                        lambda msg: self.invoke_gui(lambda: self.sendVerbose(msg))
                    )

                    self.progressRequested.emit(95, "Удаляем временные файлы...")

                    temp_files = [
                        result_data_sel,
                        result_data_3,
                        result_data_4
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
                return

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
    app.setWindowIcon(QIcon(":/icons/resources/cozyinn.ico"))
    if is_admin():
        show_admin_warning()

    widget = MainWindow()
    widget.setFixedSize(530, 400)
    widget.setWindowIcon(QIcon(":/icons/resources/cozyinn.ico"))
    widget.show()
    sys.exit(app.exec())
