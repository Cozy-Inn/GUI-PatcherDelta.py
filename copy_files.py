import os
import shutil
import subprocess
import tempfile
import time

def copy_game_files(src_copy_dir: str, dest_dir: str, datas_temp_dir: str, data_sel: str, data_3: str):
    if os.name != 'nt':
        print("This function is intended for Windows only.")
        return

    done_flag_path = os.path.join(tempfile.gettempdir(), '__copy_done__')

    try:
        if os.path.exists(done_flag_path):
            os.remove(done_flag_path)

        def is_admin():
            try:
                return os.getuid() == 0
            except AttributeError:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin()

        if is_admin():
            print("Есть права администратора, копируем напрямую...")
            shutil.copytree(src_copy_dir, dest_dir, dirs_exist_ok=True)
            shutil.copy(data_sel, os.path.join(dest_dir, os.path.basename(data_sel)))
            shutil.copy(data_3, os.path.join(dest_dir, os.path.basename(data_3)))
            with open(done_flag_path, "w") as f:
                f.write("done")
            return

        print(src_copy_dir, dest_dir, data_sel, data_3)
        script_code = f"""
import shutil
import os
import time
import tempfile

src = r'''{src_copy_dir}'''
dest = r'''{dest_dir}'''
data_sel = r'''{data_sel}'''
data_3 = r'''{data_3}'''
datas_temp_dir = r'''{datas_temp_dir}'''
done_flag_path = os.path.join(tempfile.gettempdir(), '__copy_done__')

try:
    shutil.copytree(src, dest, dirs_exist_ok=True)
    shutil.copy(os.path.join(datas_temp_dir, "data_sel.win"), data_sel)
    shutil.copy(os.path.join(datas_temp_dir, "data_3.win"), data_3)
    with open(done_flag_path, "w") as f:
        f.write("done")
except Exception as e:
    with open(os.path.join(tempfile.gettempdir(), '__copy_done__'), "w") as f:
        f.write("error: " + str(e))
"""

        script_path = os.path.join(tempfile.gettempdir(), "__copy_admin__.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_code)

        subprocess.run([
            "powershell", "-Command",
            f'Start-Process python -ArgumentList \'"{script_path}"\' -Verb RunAs'
        ])

        for _ in range(120):
            if os.path.exists(done_flag_path):
                with open(done_flag_path, "r") as f:
                    content = f.read()
                if content.startswith("error:"):
                    raise RuntimeError(content)
                break
            time.sleep(1)
        else:
            raise TimeoutError("Операция копирования не завершилась за разумное время.")

    except Exception as e:
        print(f"Ошибка копирования: {e}")
