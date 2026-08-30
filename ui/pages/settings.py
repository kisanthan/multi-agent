"""Central agent and provider settings with least-privilege editing."""

from __future__ import annotations

import shutil
import subprocess

import streamlit as st
from pydantic import BaseModel

from config import (AuthMethod, ProfileId, Provider, ReaderParser, SECRET_FIELDS,
                    masked, save_settings, settings)
from governance.audit import Decision, log_entry
from llm.client import LLMUnreachable, client_for, list_models
from ui.shared import style, user
from ui.shared.context import connection, current_user

PROFILE_LABELS = {
    ProfileId.ROUTER: "Gemeinsame Belegarterkennung",
    ProfileId.PAYMENT: "Extraktion Zahlungsbestätigung",
    ProfileId.INVOICE: "Extraktion Eingangsrechnung",
}
PROVIDER_LABELS = {
    Provider.OLLAMA: "Lokal · Ollama",
    Provider.GOOGLE: "Google · Gemini",
    Provider.ANTHROPIC: "Anthropic · Claude",
    Provider.OPENAI: "OpenAI",
}


class _ConnectionAnswer(BaseModel):
    status: str


def _actor():
    con = connection()
    try:
        return user.load(con, current_user())
    finally:
        con.close()


def _public_snapshot() -> dict:
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


def _save(updates: dict, actor: str) -> None:
    before = _public_snapshot()
    save_settings(updates)
    after = _public_snapshot()
    con = connection()
    try:
        log_entry(
            con, actor=actor, agent="policy", action="konfiguration_geaendert",
            decision=Decision.ALLOWED,
            reason=f"Systemkonfiguration auf Revision {settings.configuration_revision} geändert.",
            payload={"vorher": before, "nachher": after,
                     "geaenderte_felder": sorted(set(updates) - SECRET_FIELDS)},
            outcome="gespeichert",
        )
        con.commit()
    finally:
        con.close()


def _configured(provider: Provider) -> str:
    if provider is Provider.OLLAMA:
        return settings.ollama_base_url
    if provider is Provider.OPENAI:
        return masked(settings.openai_api_key)
    if provider is Provider.ANTHROPIC:
        return (f"Workspace-Profil: {settings.anthropic_profile}"
                if settings.anthropic_auth_method is AuthMethod.PROFILE
                else masked(settings.anthropic_api_key))
    return (f"OAuth-Projekt: {settings.google_cloud_project or 'nicht hinterlegt'}"
            if settings.google_auth_method is AuthMethod.OAUTH
            else masked(settings.google_api_key))


def _reset_connection_status(provider: Provider) -> None:
    st.session_state.pop(f"models_{provider.value}", None)
    st.session_state.pop(f"connection_status_{provider.value}", None)


def _test_provider(provider: Provider) -> None:
    try:
        models = list_models(provider)
    except LLMUnreachable as e:
        st.session_state[f"connection_status_{provider.value}"] = {
            "connected": False, "message": str(e),
        }
        st.error(str(e))
        return
    st.session_state[f"models_{provider.value}"] = models
    st.session_state[f"connection_status_{provider.value}"] = {
        "connected": True, "message": f"{len(models)} Modelle gefunden",
    }
    st.success(f"Verbunden · {len(models)} Modelle gefunden.")


def _has_connection_parameters(provider: Provider) -> bool:
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
    return all((settings.google_cloud_project, settings.google_oauth_client_id,
                settings.google_oauth_client_secret,
                settings.google_oauth_refresh_token))


def _connection_status(provider: Provider, active_model: str) -> None:
    status = st.session_state.get(f"connection_status_{provider.value}")
    models = st.session_state.get(f"models_{provider.value}", [])
    if status and status["connected"]:
        normalized = {name.removesuffix(":latest") for name in models}
        if active_model and active_model not in models and active_model not in normalized:
            st.warning(
                f"Verbunden · {len(models)} Modelle gefunden · das aktive Modell "
                f"{active_model!r} wurde nicht gefunden."
            )
        else:
            st.success(f"Verbunden · {status['message']}.")
    elif status:
        st.error(f"Nicht verbunden · {status['message']}")
    elif _has_connection_parameters(provider):
        st.info("Verbindungsparameter vorhanden · Verbindung noch nicht geprüft.")
    else:
        st.warning("Nicht verbunden · Verbindungsparameter fehlen.")


def _provider_parameters(provider: Provider, actor: str, namespace: str) -> None:
    """Render only the connection fields relevant to the selected provider."""
    st.markdown("#### Verbindungsparameter")
    st.caption(
        "Die Verbindung wird zentral gespeichert und kann von allen drei "
        "Agentenprofilen wiederverwendet werden."
    )

    if provider is Provider.OLLAMA:
        endpoint = st.text_input(
            "Ollama-Adresse", settings.ollama_base_url,
            key=f"ollama_endpoint_{namespace}",
            help="Lokaler Rechner oder Ollama-Server im Netzwerk, z. B. http://localhost:11434.",
        )
        if st.button("Verbindungsparameter speichern", key=f"save_ollama_{namespace}"):
            _save({"ollama_base_url": endpoint}, actor)
            _reset_connection_status(provider)
            st.success("Ollama-Adresse gespeichert.")
        return

    if provider is Provider.ANTHROPIC:
        method = st.selectbox(
            "Anmeldung", [AuthMethod.API_KEY, AuthMethod.PROFILE],
            index=[AuthMethod.API_KEY, AuthMethod.PROFILE].index(settings.anthropic_auth_method),
            format_func=lambda x: "API-Key" if x is AuthMethod.API_KEY else "Developer-Workspace",
            key=f"anthropic_method_{namespace}",
        )
        key = st.text_input(
            "Neuer API-Key", type="password", key=f"anthropic_key_{namespace}",
            placeholder="Leer lassen, um den vorhandenen Schlüssel zu behalten",
            disabled=method is not AuthMethod.API_KEY,
        )
        profile = st.text_input(
            "Workspace-Profil", settings.anthropic_profile,
            key=f"anthropic_profile_{namespace}",
            disabled=method is not AuthMethod.PROFILE,
        )
        st.caption(_configured(Provider.ANTHROPIC))
        cols = st.columns(2)
        if cols[0].button("Verbindungsparameter speichern",
                          key=f"save_anthropic_{namespace}"):
            updates = {"anthropic_auth_method": method, "anthropic_profile": profile}
            if key:
                updates["anthropic_api_key"] = key
            _save(updates, actor)
            _reset_connection_status(provider)
            st.success("Anthropic-Verbindung gespeichert.")
        if cols[1].button("Workspace verbinden", key=f"connect_anthropic_{namespace}",
                          disabled=method is not AuthMethod.PROFILE):
            if not shutil.which("ant"):
                st.error("Die offizielle Anthropic-CLI `ant` ist nicht installiert.")
            else:
                try:
                    subprocess.run(["ant", "auth", "login", "--profile", profile],
                                   check=True, timeout=300)
                    _save({"anthropic_auth_method": AuthMethod.PROFILE,
                           "anthropic_profile": profile}, actor)
                    _reset_connection_status(provider)
                    st.success("Anthropic-Workspace verbunden.")
                except (subprocess.SubprocessError, OSError) as e:
                    st.error(f"Workspace-Anmeldung fehlgeschlagen ({type(e).__name__}).")
        if st.button("Verbindung trennen", key=f"clear_anthropic_{namespace}"):
            if settings.anthropic_auth_method is AuthMethod.PROFILE and shutil.which("ant"):
                try:
                    subprocess.run(["ant", "auth", "logout", "--profile",
                                    settings.anthropic_profile], check=True, timeout=60)
                except (subprocess.SubprocessError, OSError):
                    st.warning("Das Workspace-Profil konnte nicht automatisch abgemeldet werden.")
            _save({"anthropic_api_key": "", "anthropic_auth_method": AuthMethod.API_KEY}, actor)
            _reset_connection_status(provider)
            st.success("Anthropic-Verbindung getrennt.")
        st.caption("Ein Claude.ai-Abo enthält keine Nutzung der Anthropic API.")
        return

    if provider is Provider.GOOGLE:
        method = st.selectbox(
            "Anmeldung", [AuthMethod.API_KEY, AuthMethod.OAUTH],
            index=[AuthMethod.API_KEY, AuthMethod.OAUTH].index(settings.google_auth_method),
            format_func=lambda x: "API-Key" if x is AuthMethod.API_KEY else "Google-Cloud-Konto (OAuth)",
            key=f"google_method_{namespace}",
        )
        api_key = st.text_input(
            "Neuer API-Key", type="password", key=f"google_key_{namespace}",
            placeholder="Leer lassen, um den vorhandenen Schlüssel zu behalten",
            disabled=method is not AuthMethod.API_KEY,
        )
        project = st.text_input(
            "Google-Cloud-Projekt", settings.google_cloud_project,
            key=f"google_project_{namespace}", disabled=method is not AuthMethod.OAUTH,
        )
        client_id = st.text_input(
            "OAuth Client-ID", settings.google_oauth_client_id,
            key=f"google_client_id_{namespace}", disabled=method is not AuthMethod.OAUTH,
        )
        client_secret = st.text_input(
            "OAuth Client-Secret", type="password",
            key=f"google_client_secret_{namespace}",
            placeholder="Leer lassen, um den vorhandenen Wert zu behalten",
            disabled=method is not AuthMethod.OAUTH,
        )
        st.caption(_configured(Provider.GOOGLE))
        cols = st.columns(2)
        if cols[0].button("Verbindungsparameter speichern",
                          key=f"save_google_{namespace}"):
            updates = {"google_auth_method": method, "google_cloud_project": project,
                       "google_oauth_client_id": client_id}
            if api_key:
                updates["google_api_key"] = api_key
            if client_secret:
                updates["google_oauth_client_secret"] = client_secret
            _save(updates, actor)
            _reset_connection_status(provider)
            st.success("Google-Verbindung gespeichert.")
        if cols[1].button("Google-Konto verbinden", key=f"connect_google_{namespace}",
                          disabled=method is not AuthMethod.OAUTH):
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_config({"installed": {
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }}, scopes=["https://www.googleapis.com/auth/cloud-platform"])
                credentials = flow.run_local_server(port=0, open_browser=True)
                if not credentials.refresh_token:
                    raise RuntimeError("Kein Refresh-Token erhalten")
                _save({"google_auth_method": AuthMethod.OAUTH,
                       "google_oauth_refresh_token": credentials.refresh_token}, actor)
                _reset_connection_status(provider)
                st.success("Google-Cloud-Konto verbunden.")
            except Exception as e:
                st.error(f"Google-Anmeldung fehlgeschlagen ({type(e).__name__}).")
        if st.button("Verbindung trennen", key=f"clear_google_{namespace}"):
            _save({"google_api_key": "", "google_oauth_refresh_token": "",
                   "google_oauth_client_secret": ""}, actor)
            _reset_connection_status(provider)
            st.success("Google-Zugangsdaten entfernt.")
        return

    api_key = st.text_input(
        "Neuer API-Key", type="password", key=f"openai_key_{namespace}",
        placeholder="Leer lassen, um den vorhandenen Schlüssel zu behalten",
    )
    st.caption(_configured(Provider.OPENAI))
    cols = st.columns(2)
    if cols[0].button("Verbindungsparameter speichern", key=f"save_openai_{namespace}"):
        if api_key:
            _save({"openai_api_key": api_key}, actor)
            _reset_connection_status(provider)
            st.success("OpenAI-Verbindung gespeichert.")
        else:
            st.info("Kein neuer Schlüssel eingegeben; der vorhandene Schlüssel bleibt erhalten.")
    if cols[1].button("Verbindung trennen", key=f"clear_openai_{namespace}"):
        _save({"openai_api_key": ""}, actor)
        _reset_connection_status(provider)
        st.success("OpenAI-Schlüssel entfernt.")
    st.caption("ChatGPT Plus/Pro und die OpenAI API werden getrennt abgerechnet.")


def _profile_editor(profile_id: ProfileId, actor: str) -> None:
    profile = settings.profile(profile_id)
    providers = list(Provider)
    provider = st.selectbox(
        "Anbieter", providers, index=providers.index(profile.provider),
        format_func=lambda p: PROVIDER_LABELS[p], key=f"provider_{profile_id.value}",
    )
    _provider_parameters(provider, actor, profile_id.value)
    _connection_status(provider, profile.model_id if provider is profile.provider else "")
    st.caption(
        "Der Verbindungstest ruft nur die Modellliste ab und erzeugt keine "
        "kostenpflichtige Modellantwort."
    )
    if st.button("Verbindung prüfen & Modelle laden",
                 key=f"test_provider_{profile_id.value}"):
        _test_provider(provider)

    st.markdown("#### Modell")
    discovered = st.session_state.get(f"models_{provider.value}", [])
    if discovered:
        current = profile.model_id if provider is profile.provider else ""
        options = list(dict.fromkeys([*([current] if current else []),
                                      *discovered, "Andere Modell-ID …"]))
        picked = st.selectbox("Modell", options, key=f"model_list_{profile_id.value}")
        custom = st.text_input("Eigene Modell-ID", key=f"custom_{profile_id.value}",
                               disabled=picked != "Andere Modell-ID …")
        model = custom.strip() if picked == "Andere Modell-ID …" else picked
    else:
        initial = profile.model_id if provider is profile.provider else ""
        model = st.text_input("Modell-ID", initial,
                              key=f"model_{profile_id.value}").strip()
        st.caption("Nach erfolgreicher Verbindung stehen gefundene Modelle hier zur Auswahl.")
    if st.button("Agentenkonfiguration speichern", key=f"save_profile_{profile_id.value}",
                 disabled=not model):
        _save({f"llm_{profile_id.value}_provider": provider,
               f"llm_{profile_id.value}_model": model}, actor)
        st.success(f"{PROFILE_LABELS[profile_id]} gespeichert.")
    profile_is_saved = provider is profile.provider and model == profile.model_id
    if st.button("Strukturierte Testanfrage · kann Kosten verursachen",
                 key=f"paid_test_{profile_id.value}", disabled=not profile_is_saved,
                 help="Speichern Sie Anbieter und Modell zuerst." if not profile_is_saved else None):
        try:
            client, choice = client_for("klassifikation", profile_id=profile_id)
            raw = client.ask_json(
                system="Antworte exakt nach dem vorgegebenen JSON-Schema.",
                prompt="Setze status auf ok.", schema=_ConnectionAnswer,
            )
            _ConnectionAnswer.model_validate_json(raw)
            st.success(f"Strukturierte Ausgabe funktioniert mit {choice.model_id}.")
        except Exception as e:
            st.error(f"Testanfrage fehlgeschlagen ({type(e).__name__}).")


def _readonly_summary() -> None:
    for profile_id in ProfileId:
        profile = settings.profile(profile_id)
        discovered = st.session_state.get(f"models_{profile.provider.value}")
        if discovered is None:
            readiness = "Bereitschaft: noch nicht per Verbindungstest geprüft"
        elif profile.model_id in discovered:
            readiness = "Bereit"
        else:
            readiness = "Nicht bereit: aktives Modell wurde nicht gefunden"
        st.markdown(f"**{PROFILE_LABELS[profile_id]}**  \n"
                    f"{PROVIDER_LABELS[profile.provider]} · `{profile.model_id}`  \n"
                    f"{readiness}")
    st.caption(f"Konfigurationsrevision {settings.configuration_revision}")


def render() -> None:
    style.css()
    st.title("Agentenkonfiguration")
    st.caption(
        "Anbieter, Verbindung und Modell für jeden KI-Agenten separat festlegen."
    )
    person = _actor()

    if not person.can_configure:
        st.info("Sie können den Bereitschaftsstatus sehen, aber die Konfiguration nicht ändern.")
        _readonly_summary()
        return

    router, payment, invoice = st.tabs(
        ["Belegarterkennung", "Zahlungsbestätigung", "Eingangsrechnung"])
    with router:
        st.info(
            "Der KI-Router liest den Beleg und bestimmt ausschließlich die "
            "Belegart. Der Orchestrator übernimmt dieses Ergebnis und verzweigt "
            "regelbasiert in den passenden Prozess; er benötigt deshalb kein "
            "eigenes KI-Modell."
        )
        st.markdown("### Router-Agent")
        _profile_editor(ProfileId.ROUTER, person.upn)
        st.divider()
        st.markdown("### Dokumentverarbeitung")
        parser = st.selectbox(
            "Dokument-Parser", list(ReaderParser),
            index=list(ReaderParser).index(settings.reader_parser),
            format_func=lambda p: p.value,
        )
        if st.button("Parser speichern"):
            _save({"reader_parser": parser}, person.upn)
            st.success("Dokument-Parser gespeichert.")

    with payment:
        st.info(
            "Dieses Profil verarbeitet nur Zahlungsbestätigungen. Das Modell "
            "extrahiert Rechnungs- oder Bestellnummer und Betrag aus dem Beleg."
        )
        st.markdown("### Zahlungsbestätigungs-Agent")
        _profile_editor(ProfileId.PAYMENT, person.upn)
        st.divider()
        st.markdown("### Prozessparameter")
        tolerance = st.number_input(
            "Erlaubte Betragsabweichung in Euro", min_value=0.0,
            value=float(settings.amount_tolerance_eur), step=0.01,
        )
        if st.button("Betragstoleranz speichern"):
            _save({"amount_tolerance_eur": tolerance}, person.upn)
            st.success("Betragstoleranz gespeichert.")
        st.markdown("### Weitere Agenten")
        st.caption(
            "Abgleich prüft Nummer und Betrag gegen die Stammdaten; Buchung "
            "übernimmt einen freigegebenen Treffer. Beide arbeiten deterministisch "
            "und benötigen keine KI."
        )

    with invoice:
        st.info(
            "Dieses Profil verarbeitet nur Eingangsrechnungen. Das Modell "
            "extrahiert Nummer, Betrag, Lieferant, Rechnungspositionen und eine "
            "vorhandene Kostenstellenreferenz."
        )
        st.markdown("### Eingangsrechnungs-Agent")
        _profile_editor(ProfileId.INVOICE, person.upn)
        st.markdown("### Weitere Agenten")
        st.caption(
            "Kostenstellenzuordnung gleicht die Referenz exakt mit den Stammdaten "
            "ab; Archivierung übergibt den abgeschlossenen Vorgang an ELO. Beide "
            "arbeiten deterministisch und benötigen keine KI."
        )
