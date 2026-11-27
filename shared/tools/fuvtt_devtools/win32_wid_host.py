"""Hidden Win32 parent window (`HWND`) host for non-intrusive Godot `--wid` UI verification.

Why a background message-pump thread is required:
- On Windows, passing `--wid <HWND>` makes Godot create/reparent its child window under `HWND`.
- Win32 `CreateWindowExW` / `SetParent` sends synchronous cross-thread messages (`WM_PARENTNOTIFY`,
  `WM_NCCREATE`, etc.) to the thread that owns `HWND`.
- If the owning thread blocks inside `subprocess.run()` without pumping `GetMessageW`, Godot
  deadlocks at startup. Running a dedicated daemon thread with an invisible (`!WS_VISIBLE`),
  non-activating (`WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`) offscreen window (`-32000, -32000`)
  gives Godot a real `Windows` `DisplayServer` and OpenGL `gl_compatibility` viewport with zero
  desktop popup, zero taskbar icon, and zero focus stealing.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import sys
import threading
from typing import Sequence


WS_POPUP = 0x80000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WM_CLOSE = 0x0010


class Win32WidError(RuntimeError):
    """Raised when `--wid` hidden window hosting is unsupported or fails to initialize."""


@dataclass(frozen=True)
class WidHostTelemetry:
    """Focus and visibility diagnostics recorded across a `--wid` child run."""

    hwnd: int
    width: int
    height: int
    foreground_before: int
    foreground_after: int
    parent_visible: bool

    @property
    def focus_unchanged(self) -> bool:
        if self.foreground_before == 0:
            return True
        return self.foreground_before == self.foreground_after


def is_win32_wid_supported() -> bool:
    """Return True when running on native Windows where `user32.dll` `--wid` hosting is available."""
    return sys.platform == "win32"


def build_wid_godot_args(
    hwnd: int,
    *,
    width: int = 1440,
    height: int = 820,
    quit_after: int = 1200,
    rendering_method: str = "gl_compatibility",
) -> list[str]:
    """Build standard non-intrusive Godot CLI flags for `--wid` UI rendering on Windows."""
    if hwnd <= 0:
        raise Win32WidError(f"非法 HWND 句柄：{hwnd}")
    return [
        "--wid",
        str(int(hwnd)),
        "--resolution",
        f"{int(width)}x{int(height)}",
        "--single-window",
        "--rendering-method",
        rendering_method,
        "--audio-driver",
        "Dummy",
        "--quit-after",
        str(int(quit_after)),
    ]


class HiddenWin32WindowHost:
    """Context manager managing an invisible, message-pumped Win32 parent `HWND` for Godot `--wid`."""

    def __init__(self, *, width: int = 1440, height: int = 820, title: str = "FuVttHiddenWidHost") -> None:
        if not is_win32_wid_supported():
            raise Win32WidError(f"当前平台 ({sys.platform}) 不支持 Win32 `--wid` 隐藏窗口宿主；请使用默认 `--headless` 模式。")
        self.width = max(320, int(width))
        self.height = max(240, int(height))
        self.title = title
        self._hwnd: int = 0
        self._fg_before: int = 0
        self._fg_after: int = 0
        self._parent_visible: bool = False
        self._error: Exception | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def snapshot_telemetry(self) -> WidHostTelemetry:
        user32 = ctypes.windll.user32
        fg_now = int(user32.GetForegroundWindow())
        vis_now = bool(user32.IsWindowVisible(ctypes.wintypes.HWND(self._hwnd))) if self._hwnd else False
        self._fg_after = fg_now
        self._parent_visible = vis_now
        return WidHostTelemetry(
            hwnd=self._hwnd,
            width=self.width,
            height=self.height,
            foreground_before=self._fg_before,
            foreground_after=fg_now,
            parent_visible=vis_now,
        )

    def _pump_thread_main(self) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        hinst = kernel32.GetModuleHandleW(None)
        hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "STATIC",
            self.title,
            WS_POPUP | WS_CLIPCHILDREN,
            -32000,
            -32000,
            self.width,
            self.height,
            None,
            None,
            hinst,
            None,
        )
        if not hwnd:
            err_code = ctypes.get_last_error()
            self._error = Win32WidError(f"CreateWindowExW 创建隐藏宿主窗口失败 (WinError={err_code})")
            self._ready.set()
            return

        self._hwnd = int(hwnd)
        self._ready.set()

        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_CLOSE and int(msg.hWnd or 0) == self._hwnd:
                user32.DestroyWindow(wintypes.HWND(self._hwnd))
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def __enter__(self) -> HiddenWin32WindowHost:
        user32 = ctypes.windll.user32
        self._fg_before = int(user32.GetForegroundWindow())
        self._thread = threading.Thread(target=self._pump_thread_main, name="FuVttWidHostPump", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise Win32WidError("等待隐藏 Win32 宿主窗口线程就绪超时。")
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if self._hwnd:
            self._fg_after = int(user32.GetForegroundWindow())
            self._parent_visible = bool(user32.IsWindowVisible(wintypes.HWND(self._hwnd)))
            user32.PostMessageW(wintypes.HWND(self._hwnd), WM_CLOSE, 0, 0)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._hwnd = 0

    def build_godot_args(self, *, quit_after: int = 1200, rendering_method: str = "gl_compatibility") -> Sequence[str]:
        return build_wid_godot_args(
            self._hwnd,
            width=self.width,
            height=self.height,
            quit_after=quit_after,
            rendering_method=rendering_method,
        )
