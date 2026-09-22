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
        "portal_mode": settings.portal_mode.value,
        "portal_admin_email": settings.portal_admin_email,
        "demo_submitter_upn": settings.demo_submitter_upn,
        "demo_approver_upn": settings.demo_approver_upn,
        "anthropic_auth_method": settings.anthropic_auth_method.value,
        "google_auth_method": settings.google_auth_method.value,
        "anthropic_profile": settings.anthropic_profile,
        "google_cloud_project": settings.google_cloud_project,
    }


def save_configuration(updates: dict, actor_upn: str) -> None:
    from governance import identity, ad
    from governance.inference_policy import authorize_local

    for key, value in updates.items():
        if key.startswith("llm_") and key.endswith("_provider") and Provider(value) is not Provider.OLLAMA:
            raise PermissionError("Cloudprofile sind für die Standardverarbeitung gesperrt.")
        if key.startswith(("anthropic_", "google_", "openai_")) and value:
            raise PermissionError("Cloudzugangsdaten gehören nicht in die Standardverarbeitung.")
    if "ollama_base_url" in updates:
        authorize_local("klassifikation", Provider.OLLAMA.value, str(updates["ollama_base_url"]))

    con = connection()
    try:
        person = identity.principal(con)
        if person != actor_upn or not ad.check_configuration_permission(con, person).allowed:
            raise PermissionError("Keine Berechtigung zur Konfigurationsänderung.")
        before = public_snapshot()
        # A durable intent is required BEFORE activating any file-based setting.
        log_entry(con, actor=person, agent="policy", action="konfiguration_beantragt",
                  decision=Decision.ALLOWED, reason="Authentifizierte Konfigurationsänderung.",
                  payload={"before": before, "fields": sorted(set(updates) - SECRET_FIELDS)}, outcome="prepared")
        con.commit()
        save_settings(updates)
        log_entry(con, actor=person, agent="policy", action="konfiguration_geaendert",
                  decision=Decision.ALLOWED, reason=f"Revision {settings.configuration_revision} aktiviert.",
                  payload={"after": public_snapshot()}, outcome="saved")
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
