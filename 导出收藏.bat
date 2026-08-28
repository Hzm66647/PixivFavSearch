@echo off
chcp 65001 >nul
title PixivFavSearch - 导出收藏
cd /d "%~dp0"

echo ==========================================
echo   导出 Pixiv 收藏 (CDP 方案, cookie 不落盘)
echo ==========================================
echo.
echo 需要 Edge/Chrome 以调试模式打开 (见 README)。
echo 本工具会在浏览器会话内抓取收藏, 不会保存你的登录 cookie。
echo.

REM 找 Python
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo 未找到 Python。请先双击 启动.bat 完成环境准备。
    pause & exit /b 1
)

REM 确保依赖
"%PY%" -m pip install --quiet --disable-pip-version-check websocket-client >nul 2>&1

REM 检测 CDP 端口
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9222/json' -TimeoutSec 2).StatusCode}catch{0}" >nul 2>&1
if errorlevel 1 (
    echo ⚠ 未检测到调试端口 9222。
    echo   请先关闭 Edge, 然后用以下方式打开:
    echo   运行(Win+R): msedge --remote-debugging-port=9222
    echo   登录 pixiv.net 后, 回到这里按任意键继续...
    pause
)

"%PY%" pixiv_export.py
echo.
pause