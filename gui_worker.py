#!/usr/bin/env python3
"""GUI 子进程独立入口 — 必须独立模块, 不能放 __main__
PyInstaller + multiprocessing spawn 下, 子进程按模块路径恢复目标函数,
若 target 定义在 __main__ 里会报 "Can't get attribute" 而崩溃。
"""
import webview

_WIN_W, _WIN_H = 1180, 800


def start(url):
    """子进程入口: 创建并运行 webview 窗口(阻塞)"""
    webview.create_window(
        "PixivFavSearch",
        url,
        width=_WIN_W, height=_WIN_H,
        min_size=(820, 560),
        background_color="#15151a",
    )
    webview.start()
