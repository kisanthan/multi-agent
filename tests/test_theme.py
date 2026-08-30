"""Theme preference and native Streamlit theme synchronization."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import tomllib

from streamlit.testing.v1 import AppTest

from ui.shared import theme


ROOT = Path(__file__).parent.parent


def test_light_theme_has_complete_accessible_surface_tokens():
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    ))

    shared = config["theme"]
    light = shared["light"]
    sidebar = light["sidebar"]

    assert shared["showWidgetBorder"] is True
    assert shared["baseRadius"] == "10px"
    assert light["backgroundColor"] == "#ffffff"
    assert light["secondaryBackgroundColor"] == "#f6f8fb"
    assert light["textColor"] == "#1f2937"
    assert light["codeTextColor"] == "#1f2937"
    assert sidebar["backgroundColor"] == "#f6f8fb"
    assert sidebar["textColor"] == "#1f2937"
    assert sidebar["primaryColor"] == "#0b5cad"


def test_theme_initializes_from_browser_cookie(monkeypatch):
    state = {}
    monkeypatch.setattr(theme.st, "session_state", state)
    monkeypatch.setattr(
        theme.st,
        "context",
        SimpleNamespace(cookies={theme.THEME_COOKIE: "dark"}),
    )

    assert theme.is_dark() is True
    assert state[theme.SESSION_DARK_MODE] is True


def test_native_theme_bridge_updates_streamlit_and_browser_preference():
    script = theme._NATIVE_THEME_JS

    assert "document.cookie" in script
    assert "stActiveTheme-" in script
    assert "window.location.pathname" in script
    assert "window.location.reload()" in script


def test_sync_native_theme_passes_the_selected_mode(monkeypatch):
    calls = []

    def mount(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(theme, "_NATIVE_THEME_BRIDGE", mount)
    monkeypatch.setattr(theme, "is_dark", lambda: True)

    theme.sync_native()

    assert calls == [{
        "key": "native-theme-sync",
        "data": {"theme": "Dark", "cookie_name": theme.THEME_COOKIE},
        "width": 1,
        "height": 1,
    }]


def test_app_recovers_from_a_stale_theme_module(monkeypatch):
    monkeypatch.delattr(theme, "sync_native")

    app = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=60)
    app.run()

    assert not any(
        "has no attribute 'sync_native'" in exception.message
        for exception in app.exception
    )
    assert hasattr(theme, "sync_native")
