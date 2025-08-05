import os
import re
import winreg
from pathlib import Path

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
