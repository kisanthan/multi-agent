"""Session-local interface theme selection."""

from __future__ import annotations

import streamlit as st

SESSION_DARK_MODE = "ui_dark_mode"
THEME_COOKIE = "multi_agent_ui_theme"

_NATIVE_THEME_JS = """
export default function (component) {
  const requested = component.data?.theme === "Dark" ? "Dark" : "Light"
  const cookieName = component.data?.cookie_name || "multi_agent_ui_theme"
  const path = window.location.pathname || "/"
  const storagePrefix = `stActiveTheme-${path}-v`
  const existingKeys = Object.keys(window.localStorage)
    .filter((key) => key.startsWith(storagePrefix))
    .sort((left, right) => {
      const leftVersion = Number(left.slice(storagePrefix.length)) || 0
      const rightVersion = Number(right.slice(storagePrefix.length)) || 0
      return rightVersion - leftVersion
    })
  // Streamlit 1.59 uses version 2. Reusing a discovered newer key keeps the
  // bridge compatible when Streamlit increments its cache format.
  const activeThemeKey = existingKeys[0] || `${storagePrefix}2`
  const storedTheme = window.localStorage.getItem(activeThemeKey)
  const cookieTheme = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${encodeURIComponent(cookieName)}=`))
    ?.split("=")[1]
  const requestedCookie = requested.toLowerCase()

  if (storedTheme === JSON.stringify(requested) && cookieTheme === requestedCookie) {
    return
  }

  document.cookie = `${encodeURIComponent(cookieName)}=${requestedCookie}; Path=/; Max-Age=31536000; SameSite=Lax`
  window.localStorage.setItem(activeThemeKey, JSON.stringify(requested))
  window.location.reload()
}
"""

_NATIVE_THEME_BRIDGE = st.components.v2.component(
    "native_theme_bridge",
    js=_NATIVE_THEME_JS,
)


def is_dark() -> bool:
    """Whether the current browser session uses the dark appearance."""
    if SESSION_DARK_MODE not in st.session_state:
        try:
            cookie_value = st.context.cookies.get(THEME_COOKIE, "light")
        except Exception:
            cookie_value = "light"
        st.session_state[SESSION_DARK_MODE] = cookie_value == "dark"
    return bool(st.session_state[SESSION_DARK_MODE])


def sync_native() -> None:
    """Keep Streamlit's native component theme aligned with the app switch."""
    # AppTest executes Python without a browser-side component registry. The
    # visual bridge has no work to do there; its behavior is covered by the
    # focused unit tests below the UI smoke layer.
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    context = get_script_run_ctx(suppress_warning=True)
    if context is not None and context.session_id == "test session id":
        return

    _NATIVE_THEME_BRIDGE(
        key="native-theme-sync",
        data={
            "theme": "Dark" if is_dark() else "Light",
            "cookie_name": THEME_COOKIE,
        },
        width=1,
        height=1,
    )
