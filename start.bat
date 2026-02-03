@echo off
chcp 65001 >nul
title RunPod Monitor Bot

echo ========================================
echo   RunPod Monitor Bot
echo ========================================
echo.

cd /d "%~dp0"

:: Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

:: .env 파일 확인
if not exist ".env" (
    echo [오류] .env 파일이 없습니다.
    echo .env.example을 복사하여 .env 파일을 만들고 설정해주세요.
    pause
    exit /b 1
)

:: 의존성 설치 확인
echo [1/2] 의존성 확인 중...
python -m pip show runpod >nul 2>&1
if errorlevel 1 (
    echo [1/2] 의존성 설치 중...
    python -m pip install -r requirements.txt
)

:: 실행
echo [2/2] Bot 시작...
echo.
echo 종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.
echo ========================================
echo.

python runpod_monitor.py

:: 오류 발생 시 창 유지
if errorlevel 1 (
    echo.
    echo [오류] 프로그램이 비정상 종료되었습니다.
    pause
)
