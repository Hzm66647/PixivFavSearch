@echo off
chcp 65001 >nul
title PixivFavSearch 启动器
cd /d "%~dp0"

echo ==========================================
echo   PixivFavSearch - 本地书签搜索工具
echo ==========================================
echo.

REM ---- 1. 跨平台找 Python (优先本项目内置, 其次系统) ----
set "PY="
if exist "%PYTHONHOME%\python.exe" set "PY=%PYTHONHOME%\python.exe"
if not defined PY if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [1/4] 未找到 Python, 尝试自动下载便携版 ^(约 8-15MB, 首次 ^)...
    echo    从 python.org 下载 embed 版...
    powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile '%~dp0python.zip'" >nul 2>&1
    if errorlevel 1 goto :dlfail
    mkdir python >nul 2>&1
    powershell -NoProfile -Command "Expand-Archive -Force '%~dp0python.zip' '%~dp0python\'" >nul 2>&1
    del /q python.zip 2>nul
    set "PY=%~dp0python\python.exe"
    echo    便携 Python 就绪。
) else (
    echo [1/4] 检测到 Python: %PY%
)

REM ---- embed版无pip, 判断并引导 (改写 _pth 让 site-packages 可用) ----
"%PY%" -c "import pip" >nul 2>&1
if errorlevel 1 (
    echo    正在为便携版添加 pip...
    echo python312.zip> "%~dp0python\python312._pth"
    echo .>> "%~dp0python\python312._pth"
    echo Lib>> "%~dp0python\python312._pth"
    echo Lib\site-packages>> "%~dp0python\python312._pth"
    echo import site>> "%~dp0python\python312._pth"
    powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%~dp0get-pip.py'" >nul 2>&1
    "%PY%" "%~dp0get-pip.py" >nul 2>&1
    del /q get-pip.py 2>nul
)

echo [2/4] 安装/检查依赖 (PySocks, pykakasi, jieba)...
"%PY%" -m pip install --quiet --disable-pip-version-check PySocks pykakasi jieba
if errorlevel 1 (
    echo    依赖安装失败。请检查网络后重试。
    pause & exit /b 1
)
echo    依赖就绪。

echo [3/4] 启动 PixivFavSearch...
del /q pix_server_stdout.log 2>nul
start "" "%~dp0python\pythonw.exe" pix_search_server.py

echo [4/4] 等待就绪并打开浏览器...
set "READY="
for /l %%i in (1,1,40) do (
    ping -n 2 127.0.0.1 >nul
    curl -s -o nul http://127.0.0.1:8897/ >nul 2>&1 && set "READY=1" && goto :done
)
:done
if defined READY (
    echo    就绪! 打开浏览器 http://127.0.0.1:8897/
    start http://127.0.0.1:8897/
) else (
    echo    启动超时, 请查看 pix_server_stdout.log
)
timeout /t 5 /nobreak >nul
exit /b 0

:dlfail
echo    下载失败, 请手动安装 Python 3.11 加 PATH 后重试。
pause & exit /b 1