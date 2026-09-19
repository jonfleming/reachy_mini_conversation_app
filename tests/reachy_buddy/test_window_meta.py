"""Tests for foreground-window scrubbing and stuck-screen denylists."""

from reachy_buddy.vision.window_meta import (
    WindowMeta,
    scrub_title,
    title_is_denied,
    process_app_label,
    window_meta_from_parts,
)


def test_scrub_title_collapses_and_truncates() -> None:
    """Titles are whitespace-collapsed and cut to a short, loggable length."""
    assert scrub_title("  hello   world  ") == "hello world"
    long = "x" * 200
    assert len(scrub_title(long)) <= 80
    assert scrub_title(long).endswith("…")


def test_title_denylist_covers_bank_password_and_2fa() -> None:
    """Login, bank, password, and 2FA titles are treated as forbidden."""
    assert title_is_denied("Acme Bank — Sign in")
    assert title_is_denied("Enter your password")
    assert title_is_denied("Authenticator 2FA")
    assert not title_is_denied("app.py — reachy_buddy")


def test_process_name_becomes_a_short_app_label() -> None:
    """Image paths collapse to a short observation label such as Code."""
    assert process_app_label(r"C:\Users\jon\AppData\Local\Programs\Microsoft VS Code\Code.exe") == "Code"
    assert process_app_label("") == "screen"


def test_window_meta_from_parts_marks_denied_and_secure() -> None:
    """Denied titles drop the raw title; lock-screen processes are secure."""
    denied = window_meta_from_parts("chrome.exe", "Please enter your password")
    assert denied.denied
    assert denied.skip
    assert denied.title == ""

    locked = window_meta_from_parts("LogonUI.exe", "Windows")
    assert locked.secure
    assert locked.skip


def test_window_identity_uses_app_and_title() -> None:
    """Same-app matching uses the scrubbed title plus the app label."""
    meta = WindowMeta(process_name="Code.exe", title="foo.py", app_label="Code")
    assert meta.identity == ("Code", "foo.py")
    assert not meta.skip
