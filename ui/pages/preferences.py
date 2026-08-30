"""Personal interface settings available to every signed-in user."""

from __future__ import annotations

import streamlit as st

from ui.shared import i18n, style, theme


def render() -> None:
    style.css()
    st.title(i18n.t("page.preferences"))
    st.caption(i18n.t("preferences.caption"))

    st.subheader(i18n.t("preferences.language.title"))
    i18n.picker()
    st.caption(i18n.t("preferences.language.caption"))

    st.divider()
    st.subheader(i18n.t("preferences.theme.title"))
    st.session_state.setdefault(theme.SESSION_DARK_MODE, False)
    dark_mode = st.toggle(
        i18n.t("preferences.theme.dark_mode"),
        key=theme.SESSION_DARK_MODE,
        help=i18n.t("preferences.theme.help"),
    )
    active_key = ("preferences.theme.active_dark" if dark_mode
                  else "preferences.theme.active_light")
    st.caption(i18n.t(active_key))
