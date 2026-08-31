"""Agent profiles and provider readiness with least-privilege editing."""

from __future__ import annotations

import streamlit as st
from pydantic import BaseModel

from config import ProfileId, Provider, ReaderParser, settings
from llm.client import client_for
from ui.settings import providers
from ui.settings.service import actor, public_snapshot, save_configuration
from ui.shared import i18n, style

# Compatibility names for focused tests and extensions that used the former
# monolithic page. The implementation itself lives in the service module.
_actor = actor
_public_snapshot = public_snapshot
_save = save_configuration


class _ConnectionAnswer(BaseModel):
    status: str


def _profile_label(profile_id: ProfileId) -> str:
    return i18n.t(f"settings.profile.{profile_id.value}")


def _provider_label(provider: Provider) -> str:
    return i18n.t(f"settings.provider.{provider.value}")


def _profile_editor(profile_id: ProfileId, actor_upn: str) -> None:
    profile = settings.profile(profile_id)
    provider_options = list(Provider)
    provider = st.selectbox(
        i18n.t("settings.provider"),
        provider_options,
        index=provider_options.index(profile.provider),
        format_func=_provider_label,
        key=f"provider_{profile_id.value}",
    )
    providers.render_provider_parameters(provider, actor_upn, profile_id.value)
    providers.connection_status(
        provider,
        profile.model_id if provider is profile.provider else "",
    )
    st.caption(i18n.t("settings.connection_test.no_charge"))
    if st.button(
        i18n.t("settings.connection_test"),
        key=f"test_provider_{profile_id.value}",
        icon=":material/network_check:",
    ):
        providers.test_provider(provider)

    st.subheader(i18n.t("settings.model"), divider=False)
    discovered = st.session_state.get(f"models_{provider.value}", [])
    custom_option = i18n.t("settings.custom_model_option")
    if discovered:
        current = profile.model_id if provider is profile.provider else ""
        options = list(dict.fromkeys([
            *([current] if current else []),
            *discovered,
            custom_option,
        ]))
        picked = st.selectbox(
            i18n.t("settings.model"),
            options,
            key=f"model_list_{profile_id.value}",
        )
        custom = st.text_input(
            i18n.t("settings.custom_model"),
            key=f"custom_{profile_id.value}",
            disabled=picked != custom_option,
        )
        model = custom.strip() if picked == custom_option else picked
    else:
        initial = profile.model_id if provider is profile.provider else ""
        model = st.text_input(
            i18n.t("settings.model_id"),
            initial,
            key=f"model_{profile_id.value}",
        ).strip()
        st.caption(i18n.t("settings.models_after_test"))

    if st.button(
        i18n.t("settings.save_profile"),
        key=f"save_profile_{profile_id.value}",
        disabled=not model,
        icon=":material/save:",
    ):
        _save({
            f"llm_{profile_id.value}_provider": provider,
            f"llm_{profile_id.value}_model": model,
        }, actor_upn)
        st.success(i18n.t("settings.profile_saved", profile=_profile_label(profile_id)))

    profile_is_saved = provider is profile.provider and model == profile.model_id
    if st.button(
        i18n.t("settings.paid_test"),
        key=f"paid_test_{profile_id.value}",
        disabled=not profile_is_saved,
        help=(i18n.t("settings.save_first") if not profile_is_saved else None),
        icon=":material/science:",
    ):
        try:
            client, choice = client_for("klassifikation", profile_id=profile_id)
            raw = client.ask_json(
                system="Return exactly the requested JSON schema.",
                prompt="Set status to ok.",
                schema=_ConnectionAnswer,
            )
            _ConnectionAnswer.model_validate_json(raw)
            st.success(i18n.t("settings.structured_output_ok", model=choice.model_id))
        except Exception as exc:  # provider SDK exposes several error classes
            st.error(i18n.t("settings.paid_test_failed", error=type(exc).__name__))


def _readonly_summary() -> None:
    for profile_id in ProfileId:
        profile = settings.profile(profile_id)
        discovered = st.session_state.get(f"models_{profile.provider.value}")
        if discovered is None:
            readiness = i18n.t("settings.readiness.unchecked")
        elif profile.model_id in discovered:
            readiness = i18n.t("settings.readiness.ready")
        else:
            readiness = i18n.t("settings.readiness.missing")
        with st.container(border=True):
            st.markdown(f"**{_profile_label(profile_id)}**")
            st.caption(f"{_provider_label(profile.provider)} · {profile.model_id}")
            st.write(readiness)
    st.caption(i18n.t(
        "settings.configuration_revision",
        revision=settings.configuration_revision,
    ))


def _render_router(actor_upn: str) -> None:
    st.info(i18n.t("settings.router.info"))
    st.subheader(i18n.t("settings.router.title"))
    _profile_editor(ProfileId.ROUTER, actor_upn)
    st.divider()
    st.subheader(i18n.t("settings.document_processing"))
    parser = st.selectbox(
        i18n.t("settings.parser"),
        list(ReaderParser),
        index=list(ReaderParser).index(settings.reader_parser),
        format_func=lambda value: value.value,
    )
    if st.button(
        i18n.t("settings.save_parser"),
        icon=":material/save:",
    ):
        _save({"reader_parser": parser}, actor_upn)
        st.success(i18n.t("settings.parser_saved"))


def _render_payment(actor_upn: str) -> None:
    st.info(i18n.t("settings.payment.info"))
    st.subheader(i18n.t("settings.payment.title"))
    _profile_editor(ProfileId.PAYMENT, actor_upn)
    st.divider()
    st.subheader(i18n.t("settings.process_parameters"))
    tolerance = st.number_input(
        i18n.t("settings.amount_tolerance"),
        min_value=0.0,
        value=float(settings.amount_tolerance_eur),
        step=0.01,
    )
    if st.button(
        i18n.t("settings.save_tolerance"),
        icon=":material/save:",
    ):
        _save({"amount_tolerance_eur": tolerance}, actor_upn)
        st.success(i18n.t("settings.tolerance_saved"))
    st.subheader(i18n.t("settings.other_agents"))
    st.caption(i18n.t("settings.payment.deterministic"))


def _render_invoice(actor_upn: str) -> None:
    st.info(i18n.t("settings.invoice.info"))
    st.subheader(i18n.t("settings.invoice.title"))
    _profile_editor(ProfileId.INVOICE, actor_upn)
    st.subheader(i18n.t("settings.other_agents"))
    st.caption(i18n.t("settings.invoice.deterministic"))


def render() -> None:
    style.css()
    st.title(i18n.t("settings.title"))
    st.caption(i18n.t("settings.caption"))
    person = _actor()

    if not person.can_configure:
        st.info(i18n.t("settings.read_only"))
        _readonly_summary()
        return

    choices = {_profile_label(profile_id): profile_id for profile_id in ProfileId}
    selected_label = st.segmented_control(
        i18n.t("settings.profile_picker"),
        list(choices),
        default=next(iter(choices)),
        label_visibility="collapsed",
    )
    selected = choices[selected_label]
    {
        ProfileId.ROUTER: _render_router,
        ProfileId.PAYMENT: _render_payment,
        ProfileId.INVOICE: _render_invoice,
    }[selected](person.upn)
