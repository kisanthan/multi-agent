"""Portal modes change authentication UX, never the process controls."""
import hashlib
import pytest
from streamlit.testing.v1 import AppTest

import config
from config import PortalMode
from governance import ad, control, identity
from governance.step_policy import PolicyDenied
from ui.cases import approval_dialog, live_ai_panel


def test_admin_mode_seeds_documented_account_once(con, monkeypatch):
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.ADMIN)
    monkeypatch.setattr(config.settings, "portal_admin_email", "admin@prototype.local")
    monkeypatch.setattr(config.settings, "portal_admin_password", "Admin-Prototype-2026!")

    identity.ensure_portal_identities(con)
    token = identity.login(con, "admin@prototype.local", "Admin-Prototype-2026!")
    assert identity.principal(con, token) == "admin@prototype.local"
    account = ad.load_user(con, "admin@prototype.local")
    assert {ad.READER_GROUP, ad.APPROVAL_GROUP, ad.CONFIGURATION_GROUP} <= account.groups

    identity.set_password(con, "admin@prototype.local", "Changed-Admin-Password!")
    identity.ensure_portal_identities(con)
    assert identity.login(con, "admin@prototype.local", "Changed-Admin-Password!")


def test_demo_mode_issues_only_seeded_simulated_sessions(con, monkeypatch):
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.DEMO)
    monkeypatch.setattr(config.settings, "demo_submitter_upn", "einspeiser@chg-meridian.com")
    monkeypatch.setattr(config.settings, "demo_approver_upn", "pruefer@chg-meridian.com")
    identity.ensure_portal_identities(con)

    submitter = identity.issue_demo_session(con, "einspeiser@chg-meridian.com")
    approver = identity.issue_demo_session(con, "pruefer@chg-meridian.com")
    denied_actor = identity.issue_demo_session(con, "extern@partner.de")
    assert identity.principal(con, submitter) == "einspeiser@chg-meridian.com"
    assert identity.principal(con, approver) == "pruefer@chg-meridian.com"
    assert identity.principal(con, denied_actor) == "extern@partner.de"
    with pytest.raises(identity.AuthenticationError):
        identity.issue_demo_session(con, "unknown@example.invalid")


def test_extended_demo_people_have_the_requested_permissions(con, monkeypatch):
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.DEMO)
    monkeypatch.setattr(config.settings, "demo_submitter_upn", "einspeiser@chg-meridian.com")
    monkeypatch.setattr(config.settings, "demo_approver_upn", "pruefer@chg-meridian.com")
    identity.ensure_portal_identities(con)

    both = ad.load_user(con, "l.schneider@chg-meridian.com")
    upload_only = ad.load_user(con, "j.becker@chg-meridian.com")

    assert {ad.READER_GROUP, ad.APPROVAL_GROUP} <= both.groups
    assert upload_only.groups == {ad.READER_GROUP}
    assert identity.issue_demo_session(con, both.upn)
    assert identity.issue_demo_session(con, upload_only.upn)
    assert both.upn in identity.demo_portal_upns()
    assert upload_only.upn in identity.demo_portal_upns()


def test_demo_mode_keeps_four_eyes_and_payload_binding(con, monkeypatch):
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.DEMO)
    monkeypatch.setattr(config.settings, "demo_submitter_upn", "einspeiser@chg-meridian.com")
    monkeypatch.setattr(config.settings, "demo_approver_upn", "pruefer@chg-meridian.com")
    con.execute("INSERT INTO ad_memberships VALUES('einspeiser@chg-meridian.com','SG-CHG-Freigabe')")
    con.commit()
    identity.ensure_portal_identities(con)
    submitter = identity.issue_demo_session(con, "einspeiser@chg-meridian.com")
    approver = identity.issue_demo_session(con, "pruefer@chg-meridian.com")
    raw = b"synthetic demo document"
    digest = hashlib.sha256(raw).hexdigest()
    with identity.session(submitter):
        control.register_case(con, case_id="demo-case", actor="einspeiser@chg-meridian.com",
                              document_hash=digest, filename="demo.pdf", content=raw)
    control.select_process(con, "demo-case", "B")
    con.execute("INSERT INTO cost_centers VALUES('KST-DEMO','Demo','REF-DEMO','demo')")
    con.commit()
    center = con.execute("SELECT id FROM cost_centers ORDER BY id LIMIT 1").fetchone()[0]
    proposal = control.candidate(con, "demo-case", "elo",
                                 control.archive_payload(con, "demo-case", center), True)
    with identity.session(submitter), pytest.raises(PolicyDenied, match="verschiedene Personen"):
        control.decide(con, proposal, approved=True)
    with identity.session(approver):
        assert control.decide(con, proposal, approved=True) == "pruefer@chg-meridian.com"


def test_demo_mode_opens_portal_without_login(monkeypatch):
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.DEMO)
    at = AppTest.from_file("ui/app.py", default_timeout=30)
    at.run()
    assert not at.exception
    assert not any(field.label == "Passwort" for field in at.text_input)
    selector = next(selector for selector in at.selectbox if selector.label == "Demo-Rolle")
    assert at.session_state["signed_in_user"] == config.settings.demo_submitter_upn
    selector.set_value(config.settings.demo_approver_upn).run()
    assert not at.exception
    assert at.session_state["signed_in_user"] == config.settings.demo_approver_upn


def test_demo_identity_switch_starts_with_clean_ui_state(monkeypatch):
    """No drawer, dialog, widget, or case state may cross user boundaries."""
    monkeypatch.setattr(config.settings, "portal_mode", PortalMode.DEMO)
    at = AppTest.from_file("ui/app.py", default_timeout=30)
    at.run()
    assert not at.exception

    at.session_state[live_ai_panel.SESSION_SNAPSHOT] = live_ai_panel.PanelSnapshot(
        case_id="case-of-previous-user",
        filename="previous-user.pdf",
        profiles={},
    )
    at.session_state[approval_dialog.DISMISSED] = "case-of-previous-user"
    at.session_state["reject_confirmed_case-of-previous-user"] = True

    selector = next(selector for selector in at.selectbox
                    if selector.label == "Demo-Rolle")
    selector.set_value(config.settings.demo_approver_upn).run()

    assert not at.exception
    assert at.session_state["signed_in_user"] == config.settings.demo_approver_upn
    assert live_ai_panel.SESSION_SNAPSHOT not in at.session_state
    assert approval_dialog.DISMISSED not in at.session_state
    assert "reject_confirmed_case-of-previous-user" not in at.session_state
