import subprocess
import ctypes
import tempfile
import os
from time import sleep
def generate_copy_bat(config: dict, output_path: str = "copy_script.bat", stop_flag = "temp.flag", log_func=print):
    lines = ["@echo off", "chcp 65001 >nul", ""]

    folders = config.get("folders", {})
    for src, dst in folders.items():
        lines.append(f'xcopy "{src}" "{dst}" /E /I /Y /Q')

    files = config.get("files", {})
    for src, dst in files.items():
        lines.append(f'copy /Y "{src}" "{dst}"')

    lines.append(f'echo DONE > "{stop_flag}"')

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log_func(f".bat script written to: {output_path}")


def elevate(bat_path, log_func=print):
    log_func("Повторный запуск с правами администратора...")
    
    params = f'"{bat_path}"'
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "cmd.exe", f'/c {params}', None, 1
    )
    
    if ret <= 32:
        log_func("Ошибка: не удалось запустить с правами администратора.")
    else:
        log_func("Скрипт был запущен с повышенными правами.")
        sleep(5)

def wait_for_done_flag(done_flag_path, log_func=print, timeout=60):
    import time
    start = time.time()
    while not os.path.exists(done_flag_path):
        if time.time() - start > timeout:
            log_func("Превышено время ожидания завершения скрипта.")
            raise RuntimeError(f"TimeoutError: Превышено максимальное время ожидания выполнения скрипта ({timeout} секунд)") 
        time.sleep(1)
    log_func("Скрипт успешно завершился.")
    os.remove(done_flag_path)
    return True


def run_bat_with_fallback(bat_path, log_func=print):
    try:
        # Пробуем обычный запуск
        log_func(f"Запуск {bat_path} без прав администратора...")
        result = subprocess.run(
            ["cmd.exe", "/c", bat_path], 
            check=True, shell=False, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            creationflags=subprocess.CREATE_NO_WINDOW
            )
        log_func("Скрипт выполнен успешно без повышения прав.")
    except subprocess.CalledProcessError as e:
        log_func(f"Ошибка выполнения: {e}. Возможно, не хватает прав.")
        elevate(bat_path, log_func)

def copy_game_files_win(config, log_func=print):
    if os.name != 'nt':
        log_func("This function is intended for Windows only.")
        return
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bat") as tmp:
        bat_path = tmp.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".flag") as tmp:
        stop_flag = tmp.name
    
    generate_copy_bat(config, bat_path, stop_flag, log_func)
    run_bat_with_fallback(bat_path, log_func)
    wait_for_done_flag(stop_flag, log_func)
    return bat_path
