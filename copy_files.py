import sys
import os
import shutil
import json
import time
from time import sleep

def load_args():
    if len(sys.argv) == 2 and sys.argv[1].endswith('.json'):
        with open(sys.argv[1], 'r') as f:
            return json.load(f)
    return None

def safe_copy(src, dst, max_retries=5, delay=1):
    """Копирование с повторными попытками при блокировке файла"""
    for attempt in range(max_retries):
        try:
            shutil.copy2(src, dst)
            return True
        except PermissionError as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
    return False

def copy_files(args):
    try:
        # Создаем директории
        os.makedirs(args['dest'], exist_ok=True)

        # Копируем исходные файлы с повторами
        if os.path.exists(args['src']):
            for root, dirs, files in os.walk(args['src']):
                rel_path = os.path.relpath(root, args['src'])
                target_dir = os.path.join(args['dest'], rel_path)
                os.makedirs(target_dir, exist_ok=True)
                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_dir, file)
                    safe_copy(src_file, dst_file)
        else:
            print(f"Source directory not found: {args['src']}")
            return 1

        # Копируем патч-файлы с повторами
        safe_copy(args['patch_file_1'], os.path.join(os.path.dirname(args['dest']), "data.win"))
        safe_copy(args['patch_file_2'], os.path.join(args['dest'], "data.win"))

        return 0
    except Exception as e:
        print(f"Error during copying: {e}")
        sleep(5)
        return 2

if __name__ == "__main__":
    args = load_args() or {
        'src': sys.argv[1],
        'dest': sys.argv[2],
        'patch_file_1': sys.argv[3],
        'patch_file_2': sys.argv[4]
    }
    sys.exit(copy_files(args))
