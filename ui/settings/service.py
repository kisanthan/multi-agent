"""Pure configuration operations used by the Streamlit settings page."""

from __future__ import annotations

from config import AuthMethod, Provider, SECRET_FIELDS, masked, save_settings, settings
from governance.audit import Decision, log_entry
from ui.shared import user
from ui.shared.context import connection, current_user


def actor():
    con = connection()
    try:
        return user.load(con, current_user())
    finally:
        con.close()


def public_snapshot() -> dict:
    """Configuration evidence with every secret deliberately excluded."""
    return {
        "profile": settings.profile_snapshot(),
        "ollama_base_url": settings.ollama_base_url,
        "reader_parser": settings.reader_parser.value,
        "amount_tolerance_eur": settings.amount_tolerance_eur,
        "anthropic_auth_method": settings.anthropic_auth_method.value,
        "google_auth_method": settings.google_auth_method.value,
        "anthropic_profile": settings.anthropic_profile,
        "google_cloud_project": settings.google_cloud_project,
    }


def save_configuration(updates: dict, actor_upn: str) -> None:
    before = public_snapshot()
    save_settings(updates)
    after = public_snapshot()
    con = connection()
    try:
        log_entry(
            con,
            actor=actor_upn,
            agent="policy",
            action="konfiguration_geaendert",
            decision=Decision.ALLOWED,
            reason=(f"Systemkonfiguration auf Revision "
                    f"{settings.configuration_revision} geaendert."),
            payload={
                "vorher": before,
                "nachher": after,
                "geaenderte_felder": sorted(set(updates) - SECRET_FIELDS),
            },
            outcome="gespeichert",
        )
        con.commit()
    finally:
        con.close()


def configured(provider: Provider) -> str:
    if provider is Provider.OLLAMA:
        return settings.ollama_base_url
    if provider is Provider.OPENAI:
        return masked(settings.openai_api_key)
    if provider is Provider.ANTHROPIC:
        return (f"Workspace: {settings.anthropic_profile}"
                if settings.anthropic_auth_method is AuthMethod.PROFILE
                else masked(settings.anthropic_api_key))
    return (f"OAuth project: {settings.google_cloud_project or '-'}"
            if settings.google_auth_method is AuthMethod.OAUTH
            else masked(settings.google_api_key))


def has_connection_parameters(provider: Provider) -> bool:
    if provider is Provider.OLLAMA:
        return bool(settings.ollama_base_url)
    if provider is Provider.OPENAI:
        return bool(settings.openai_api_key)
    if provider is Provider.ANTHROPIC:
        return (bool(settings.anthropic_profile)
                if settings.anthropic_auth_method is AuthMethod.PROFILE
                else bool(settings.anthropic_api_key))
    if settings.google_auth_method is AuthMethod.API_KEY:
        return bool(settings.google_api_key)
    return all((
        settings.google_cloud_project,
        settings.google_oauth_client_id,
        settings.google_oauth_client_secret,
        settings.google_oauth_refresh_token,
    ))
