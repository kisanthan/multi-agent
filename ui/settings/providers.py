"""Provider connection controls for the agent configuration page."""

from __future__ import annotations

import shutil
import subprocess

import streamlit as st

from config import AuthMethod, Provider, settings
from llm.client import LLMUnreachable, list_models
from ui.settings.service import configured, has_connection_parameters, save_configuration
from ui.shared import i18n


def reset_connection_status(provider: Provider) -> None:
    st.session_state.pop(f"models_{provider.value}", None)
    st.session_state.pop(f"connection_status_{provider.value}", None)


def test_provider(provider: Provider) -> None:
    try:
        models = list_models(provider)
    except LLMUnreachable as exc:
        st.session_state[f"connection_status_{provider.value}"] = {
            "connected": False,
            "message": str(exc),
        }
        st.error(str(exc))
        return
    st.session_state[f"models_{provider.value}"] = models
    st.session_state[f"connection_status_{provider.value}"] = {
        "connected": True,
        "message": i18n.t("settings.models_found", count=len(models)),
    }
    st.success(i18n.t("settings.connected_count", count=len(models)))


def connection_status(provider: Provider, active_model: str) -> None:
    status = st.session_state.get(f"connection_status_{provider.value}")
    models = st.session_state.get(f"models_{provider.value}", [])
    if status and status["connected"]:
        normalized = {name.removesuffix(":latest") for name in models}
        if active_model and active_model not in models and active_model not in normalized:
            st.warning(i18n.t(
                "settings.connected_missing_model",
                count=len(models),
                model=active_model,
            ))
        else:
            st.success(i18n.t("settings.connected", message=status["message"]))
    elif status:
        st.error(i18n.t("settings.not_connected", message=status["message"]))
    elif has_connection_parameters(provider):
        st.info(i18n.t("settings.connection_unchecked"))
    else:
        st.warning(i18n.t("settings.connection_missing"))


def _auth_label(method: AuthMethod) -> str:
    return i18n.t(f"settings.auth.{method.value}", default=method.value)


def render_provider_parameters(provider: Provider, actor: str, namespace: str) -> None:
    st.subheader(i18n.t("settings.connection_parameters"), divider=False)
    st.caption(i18n.t("settings.connection_shared"))

    if provider is Provider.OLLAMA:
        endpoint = st.text_input(
            i18n.t("settings.ollama_url"),
            settings.ollama_base_url,
            key=f"ollama_endpoint_{namespace}",
            help=i18n.t("settings.ollama_url.help"),
        )
        if st.button(
            i18n.t("settings.save_connection"),
            key=f"save_ollama_{namespace}",
            icon=":material/save:",
        ):
            save_configuration({"ollama_base_url": endpoint}, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.ollama_saved"))
        return

    if provider is Provider.ANTHROPIC:
        methods = [AuthMethod.API_KEY, AuthMethod.PROFILE]
        method = st.selectbox(
            i18n.t("settings.auth_method"),
            methods,
            index=methods.index(settings.anthropic_auth_method),
            format_func=_auth_label,
            key=f"anthropic_method_{namespace}",
        )
        key = st.text_input(
            i18n.t("settings.new_api_key"),
            type="password",
            key=f"anthropic_key_{namespace}",
            placeholder=i18n.t("settings.keep_secret"),
            disabled=method is not AuthMethod.API_KEY,
        )
        profile = st.text_input(
            i18n.t("settings.workspace_profile"),
            settings.anthropic_profile,
            key=f"anthropic_profile_{namespace}",
            disabled=method is not AuthMethod.PROFILE,
        )
        st.caption(configured(provider))
        with st.container(horizontal=True):
            save = st.button(
                i18n.t("settings.save_connection"),
                key=f"save_anthropic_{namespace}",
                icon=":material/save:",
            )
            connect = st.button(
                i18n.t("settings.connect_workspace"),
                key=f"connect_anthropic_{namespace}",
                disabled=method is not AuthMethod.PROFILE,
                icon=":material/link:",
            )
        if save:
            updates = {"anthropic_auth_method": method, "anthropic_profile": profile}
            if key:
                updates["anthropic_api_key"] = key
            save_configuration(updates, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.anthropic_saved"))
        if connect:
            if not shutil.which("ant"):
                st.error(i18n.t("settings.anthropic_cli_missing"))
            else:
                try:
                    subprocess.run(
                        ["ant", "auth", "login", "--profile", profile],
                        check=True,
                        timeout=300,
                    )
                    save_configuration({
                        "anthropic_auth_method": AuthMethod.PROFILE,
                        "anthropic_profile": profile,
                    }, actor)
                    reset_connection_status(provider)
                    st.success(i18n.t("settings.anthropic_connected"))
                except (subprocess.SubprocessError, OSError) as exc:
                    st.error(i18n.t("settings.workspace_failed", error=type(exc).__name__))
        if st.button(
            i18n.t("settings.disconnect"),
            key=f"clear_anthropic_{namespace}",
            icon=":material/link_off:",
        ):
            if settings.anthropic_auth_method is AuthMethod.PROFILE and shutil.which("ant"):
                try:
                    subprocess.run(
                        ["ant", "auth", "logout", "--profile", settings.anthropic_profile],
                        check=True,
                        timeout=60,
                    )
                except (subprocess.SubprocessError, OSError):
                    st.warning(i18n.t("settings.workspace_logout_failed"))
            save_configuration({
                "anthropic_api_key": "",
                "anthropic_auth_method": AuthMethod.API_KEY,
            }, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.anthropic_disconnected"))
        st.caption(i18n.t("settings.anthropic_billing"))
        return

    if provider is Provider.GOOGLE:
        methods = [AuthMethod.API_KEY, AuthMethod.OAUTH]
        method = st.selectbox(
            i18n.t("settings.auth_method"),
            methods,
            index=methods.index(settings.google_auth_method),
            format_func=_auth_label,
            key=f"google_method_{namespace}",
        )
        api_key = st.text_input(
            i18n.t("settings.new_api_key"),
            type="password",
            key=f"google_key_{namespace}",
            placeholder=i18n.t("settings.keep_secret"),
            disabled=method is not AuthMethod.API_KEY,
        )
        project = st.text_input(
            i18n.t("settings.google_project"),
            settings.google_cloud_project,
            key=f"google_project_{namespace}",
            disabled=method is not AuthMethod.OAUTH,
        )
        client_id = st.text_input(
            i18n.t("settings.oauth_client_id"),
            settings.google_oauth_client_id,
            key=f"google_client_id_{namespace}",
            disabled=method is not AuthMethod.OAUTH,
        )
        client_secret = st.text_input(
            i18n.t("settings.oauth_client_secret"),
            type="password",
            key=f"google_client_secret_{namespace}",
            placeholder=i18n.t("settings.keep_secret"),
            disabled=method is not AuthMethod.OAUTH,
        )
        st.caption(configured(provider))
        with st.container(horizontal=True):
            save = st.button(
                i18n.t("settings.save_connection"),
                key=f"save_google_{namespace}",
                icon=":material/save:",
            )
            connect = st.button(
                i18n.t("settings.connect_google"),
                key=f"connect_google_{namespace}",
                disabled=method is not AuthMethod.OAUTH,
                icon=":material/link:",
            )
        if save:
            updates = {
                "google_auth_method": method,
                "google_cloud_project": project,
                "google_oauth_client_id": client_id,
            }
            if api_key:
                updates["google_api_key"] = api_key
            if client_secret:
                updates["google_oauth_client_secret"] = client_secret
            save_configuration(updates, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.google_saved"))
        if connect:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow

                flow = InstalledAppFlow.from_client_config({"installed": {
                    "client_id": client_id,
                    "client_secret": client_secret or settings.google_oauth_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }}, scopes=["https://www.googleapis.com/auth/cloud-platform"])
                credentials = flow.run_local_server(port=0, open_browser=True)
                if not credentials.refresh_token:
                    raise RuntimeError("missing refresh token")
                save_configuration({
                    "google_auth_method": AuthMethod.OAUTH,
                    "google_cloud_project": project,
                    "google_oauth_client_id": client_id,
                    "google_oauth_client_secret": (
                        client_secret or settings.google_oauth_client_secret
                    ),
                    "google_oauth_refresh_token": credentials.refresh_token,
                }, actor)
                reset_connection_status(provider)
                st.success(i18n.t("settings.google_connected"))
            except Exception as exc:  # provider SDK exposes several error classes
                st.error(i18n.t("settings.google_failed", error=type(exc).__name__))
        if st.button(
            i18n.t("settings.disconnect"),
            key=f"clear_google_{namespace}",
            icon=":material/link_off:",
        ):
            save_configuration({
                "google_api_key": "",
                "google_oauth_refresh_token": "",
                "google_oauth_client_secret": "",
            }, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.google_disconnected"))
        return

    api_key = st.text_input(
        i18n.t("settings.new_api_key"),
        type="password",
        key=f"openai_key_{namespace}",
        placeholder=i18n.t("settings.keep_secret"),
    )
    st.caption(configured(provider))
    with st.container(horizontal=True):
        save = st.button(
            i18n.t("settings.save_connection"),
            key=f"save_openai_{namespace}",
            icon=":material/save:",
        )
        disconnect = st.button(
            i18n.t("settings.disconnect"),
            key=f"clear_openai_{namespace}",
            icon=":material/link_off:",
        )
    if save:
        if api_key:
            save_configuration({"openai_api_key": api_key}, actor)
            reset_connection_status(provider)
            st.success(i18n.t("settings.openai_saved"))
        else:
            st.info(i18n.t("settings.no_new_key"))
    if disconnect:
        save_configuration({"openai_api_key": ""}, actor)
        reset_connection_status(provider)
        st.success(i18n.t("settings.openai_disconnected"))
    st.caption(i18n.t("settings.openai_billing"))
