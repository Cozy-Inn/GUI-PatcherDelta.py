@echo off
chcp 65001
REM Проверяем, что передан аргумент (путь к data.win)
if "%~1"=="" (
    echo Пожалуйста, перетащите файл data.win на этот скрипт или укажите путь как аргумент.
    pause
    exit /b 1
)

set "DATA_PATH=%~1"
set "DATA_DIR=%~dp1"

if "%DATA_DIR:~-1%"=="\" set "DATA_DIR=%DATA_DIR:~0,-1%"

set "OUTPUT_DIR=%DATA_DIR%"

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

set "PATCHER_FILE=%~dp0\..\ch_sel\data.json"

REM Запускаем патчер (используя путь к батнику)
"%~dp0GMS-UTML-Patcher.exe" --data-path "%DATA_PATH%" --patcher-file "%PATCHER_FILE%" --skip-timecheck

REM Ждём, чтобы патчер успел завершиться
REM (если патчер асинхронный — возможно нужна другая логика ожидания)

REM Переименовываем patched файл в оригинальный
set "PATCHED_FILE=%OUTPUT_DIR%\data.patched.win"
set "ORIGINAL_FILE=%OUTPUT_DIR%\data.win"

if exist "%PATCHED_FILE%" (
    echo Заменяем %ORIGINAL_FILE% на %PATCHED_FILE%...
    del /f /q "%ORIGINAL_FILE%" 2>nul
    move /y "%PATCHED_FILE%" "%ORIGINAL_FILE%"
    if errorlevel 1 (
        echo Ошибка при переименовании patched файла!
        pause
        exit /b 1
    ) else (
        echo Успешно заменён файл data.win
    )
) else (
    echo Файл %PATCHED_FILE% не найден!
    pause
    exit /b 1
)

pause
