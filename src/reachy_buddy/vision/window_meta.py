"""Foreground window metadata: process name plus a scrubbed, truncated title."""

import re
import sys
import ctypes
import logging
from ctypes import wintypes
from pathlib import Path
from dataclasses import dataclass


logger = logging.getLogger(__name__)

_TITLE_MAX = 80
_APP_LABEL_MAX = 32
_TITLE_DENY_PHRASES = (
    "password",
    "passwd",
    "two-factor",
    "two factor",
    "authenticator",
    "one-time",
    "banking",
    "account login",
    "sign in",
    "signin",
    "user account control",
    "credential",
    "unlock",
    "secure desktop",
    "windows security",
)
_TITLE_DENY_TOKENS = re.compile(r"\b(2fa|otp|pin|uac|bank)\b")
_SECURE_PROCESSES = frozenset(
    {
        "logonui",
        "consent",
        "lockapp",
        "credentialuibroker",
        "windowshello",
        "lockappbroker",
    }
)


@dataclass(frozen=True)
class WindowMeta:
    """Active-window process name and a privacy-scrubbed title."""

    process_name: str = ""
    title: str = ""
    app_label: str = "screen"
    secure: bool = False
    denied: bool = False

    @property
    def skip(self) -> bool:
        """Whether this window must not be treated as a stuck desktop."""
        return self.secure or self.denied

    @property
    def identity(self) -> tuple[str, str]:
        """Stable key for optional same-app / same-title matching."""
        return (self.app_label, self.title)


def scrub_title(title: str, max_len: int = _TITLE_MAX) -> str:
    """Collapse whitespace and truncate a window title."""
    collapsed = " ".join(title.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


def title_is_denied(title: str) -> bool:
    """Return whether the title looks like a login, bank, password, or 2FA surface."""
    lowered = title.lower()
    if any(phrase in lowered for phrase in _TITLE_DENY_PHRASES):
        return True
    return _TITLE_DENY_TOKENS.search(lowered) is not None


def process_app_label(process_name: str) -> str:
    """Turn a process path or image name into a short observation label."""
    stem = Path(process_name).stem.strip()
    cleaned = "".join(char for char in stem if char.isalnum() or char in "-_")
    return (cleaned or "screen")[:_APP_LABEL_MAX]


def window_meta_from_parts(process_name: str, title: str, *, secure: bool = False) -> WindowMeta:
    """Build metadata from already-read process and title strings."""
    scrubbed = scrub_title(title)
    label = process_app_label(process_name)
    denied = title_is_denied(scrubbed)
    process_secure = label.lower() in _SECURE_PROCESSES
    return WindowMeta(
        process_name=Path(process_name).name,
        title="" if denied else scrubbed,
        app_label=label,
        secure=secure or process_secure,
        denied=denied,
    )


def read_foreground_window() -> WindowMeta:
    """Read the foreground window; empty metadata when the platform cannot."""
    if sys.platform == "win32":
        return _read_win32_foreground()
    return WindowMeta()


def desktop_is_secure() -> bool:
    """Best-effort locked / UAC / secure-desktop detection."""
    if sys.platform == "win32":
        return _win32_desktop_is_secure()
    return False


def seconds_since_input() -> float | None:
    """Seconds since the last OS input event, or None when unavailable."""
    if sys.platform == "win32":
        return _win32_seconds_since_input()
    return None


def _read_win32_foreground() -> WindowMeta:
    user32 = ctypes.windll.user32
    hwnd = int(user32.GetForegroundWindow())
    if not hwnd:
        return WindowMeta(secure=True, app_label="screen")
    title = _win32_window_title(hwnd)
    process_name = _win32_process_name(hwnd)
    return window_meta_from_parts(process_name, title, secure=_win32_desktop_is_secure())


def _win32_window_title(hwnd: int) -> str:
    length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _win32_process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return ""
    kernel32 = ctypes.windll.kernel32
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    if not process:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size))
        return buffer.value if ok else ""
    finally:
        kernel32.CloseHandle(process)


def _win32_desktop_is_secure() -> bool:
    user32 = ctypes.windll.user32
    desktop = user32.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return True
    try:
        size = wintypes.DWORD(0)
        user32.GetUserObjectInformationW(desktop, 2, None, 0, ctypes.byref(size))
        if size.value <= 0:
            return False
        buffer = ctypes.create_unicode_buffer(size.value // 2 or 1)
        if not user32.GetUserObjectInformationW(desktop, 2, buffer, size.value, ctypes.byref(size)):
            return False
        name = buffer.value.strip()
        return bool(name) and name.lower() not in {"default", "winsta0\\default"}
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Secure-desktop probe failed: %s", exc)
        return False
    finally:
        user32.CloseDesktop(desktop)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def _win32_seconds_since_input() -> float | None:
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    now = ctypes.windll.kernel32.GetTickCount()
    elapsed_ms = (now - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0
