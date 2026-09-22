"""Authenticated case controls and optional reviewed layout clarification."""
import json
from pathlib import Path
import streamlit as st
import config
from governance import control, identity, ad
from governance.step_policy import PolicyDenied
from runtime.tool_gateway import dispatch
from ui.shared.context import connection


def _update_from_receipt(app, thread_id, receipt):
    success = receipt["status"] == "succeeded"
    archive = "archive_id" in receipt
    values = {"completed": receipt["status"] != "in_doubt",
              "outcome": ("archiviert" if archive else "verbucht") if success else
                         "wirkung_ungeklaert" if receipt["status"] == "in_doubt" else "abgelehnt",
              "command_id": receipt["command_id"], "error": receipt.get("reason")}
    if archive:
        values["archive_id"] = receipt["archive_id"]
    app.update_state({"configurable": {"thread_id": thread_id}}, values, as_node="elo" if archive else "buchung")


def render(app, thread_id, values):
    con = connection()
    try:
        try:
            person = identity.principal(con)
            c = control.case(con, thread_id)
        except (identity.AuthenticationError, PolicyDenied):
            return
        if not ad.check_approval_permission(con, person).allowed:
            return
        with st.expander("Vorgang steuern"):
            reason = st.text_input("Begründung", key=f"control_reason_{thread_id}")
            if st.button("Fortsetzen" if c["stopped"] else "Anhalten", key=f"stop_{thread_id}", disabled=not reason.strip()):
                try:
                    control.set_stopped(con, thread_id, not c["stopped"], reason)
                    if c["stopped"] and not values.get("completed"):
                        step = "buchung" if c["process"] == "A" else "elo"
                        old = control.get_candidate(con, thread_id, step)
                        control.validate_payload(con, step, old["payload"])
                        new = control.candidate(con, thread_id, step, old["payload"], True)
                        app.update_state({"configurable": {"thread_id": thread_id}},
                                         {"approval_id": new["approval_id"], "candidate_version": new["version"],
                                          "approval_decision": "", "command_id": None, "exception_case": True},
                                         as_node="abgleich" if c["process"] == "A" else "kostenstelle")
                    st.rerun()
                except PolicyDenied as error:
                    st.error(str(error))
            if values.get("command_id") and values.get("outcome") == "wirkung_ungeklaert":
                st.warning("Die Antwort fehlt. Vor einer Wiederholung wird derselbe Ausführungsauftrag geprüft.")
                if st.button("Ergebnis prüfen und fortsetzen", key=f"recover_{thread_id}"):
                    try:
                        control.recover_command(con, values["command_id"])
                        receipt = dispatch(con, values["command_id"])
                        _update_from_receipt(app, thread_id, receipt)
                        st.rerun()
                    except PolicyDenied as error:
                        st.error(str(error))
            if values.get("archive_id") and ad.check_configuration_permission(con, person).allowed:
                choices = [row[0] for row in con.execute("SELECT id FROM cost_centers ORDER BY id")]
                center = st.selectbox("Korrigierte Kostenstelle", ["Zuordnung zurücknehmen", *choices], key=f"correct_{thread_id}")
                confirmed = st.checkbox("Die Korrektur wurde fachlich geprüft.", key=f"correct_confirm_{thread_id}")
                if st.button("Ablagezuordnung korrigieren", disabled=not (confirmed and reason.strip()), key=f"correct_apply_{thread_id}"):
                    try:
                        control.correct_archive(con, values["archive_id"], None if center == "Zuordnung zurücknehmen" else center, reason)
                        st.success("Korrektur gespeichert. Original und bisherige Zuordnung bleiben nachweisbar.")
                    except PolicyDenied as error:
                        st.error(str(error))
        failures = con.execute("SELECT step FROM local_extraction_failures WHERE case_id=?", (thread_id,)).fetchall()
        if failures:
            _layout(app, con, thread_id, failures[0][0], values)
    finally:
        con.close()


def _layout(app, con, thread_id, step, values):
    from llm import layout
    with st.expander("Layout manuell klären"):
        st.caption("Nur nach fehlgeschlagener lokaler Extraktion. Namen, Konto-, Adress- und Kontaktdaten müssen im Ausschnitt vollständig verdeckt sein.")
        page = st.number_input("Seite", min_value=1, value=1, step=1, key=f"layout_page_{thread_id}")
        region = st.text_input("Seitenausschnitt [links, oben, rechts, unten] in PDF-Punkten", "[0, 0, 400, 300]", key=f"layout_region_{thread_id}")
        masks = st.text_input("Zu verdeckende Rechtecke", "[[0, 0, 400, 100]]", key=f"layout_masks_{thread_id}")
        if st.button("Maskierte Vorschau erstellen", key=f"layout_prepare_{thread_id}"):
            try:
                prepared = layout.prepare(con, case_id=thread_id, step=step, page=int(page)-1,
                                          region=json.loads(region), redactions=json.loads(masks))
                st.session_state[f"layout_request_{thread_id}"] = prepared["request_id"]
            except (PolicyDenied, ValueError, TypeError) as error:
                st.error(str(error))
        request_id = st.session_state.get(f"layout_request_{thread_id}")
        if not request_id:
            return
        row = con.execute("SELECT image,image_hash,status FROM layout_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            return
        st.image(row[0], caption="Ausschließlich diese Bilddaten sind für die externe Prüfung vorgesehen.")
        reviewed = st.checkbox("Der Ausschnitt ist erforderlich; alle Personen-, Konto-, Adress- und Kontaktdaten sind verdeckt.", key=f"mask_review_{request_id}")
        explanation = st.text_input("Grund der Layoutklärung", key=f"mask_reason_{request_id}")
        if row[2] == "prepared" and st.button("Maskierung bestätigen", disabled=not (reviewed and explanation.strip()), key=f"mask_confirm_{request_id}"):
            try:
                layout.review(con, request_id, row[1], explanation)
                st.rerun()
            except PolicyDenied as error:
                st.error(str(error))
        deployment_file = Path(config.DB_PATH).parent / "layout-deployment.json"
        deployment = None
        try:
            deployment = layout.DeploymentApproval(**json.loads(deployment_file.read_text(encoding="utf-8")))
            deployment.validate()
        except (OSError, ValueError, TypeError, PolicyDenied):
            st.info("Externe Layoutprüfung gesperrt: freigegebener Endpoint und Bereitstellungsnachweise fehlen.")
        if row[2] == "reviewed" and st.button("Maskierten Ausschnitt prüfen lassen", disabled=deployment is None, key=f"layout_send_{request_id}"):
            from agents.shared.schemas import PaymentExtraction, InvoiceExtraction
            schema = PaymentExtraction if step == "extraktion_zahlung" else InvoiceExtraction
            try:
                result = layout.send(con, request_id, deployment, schema)
                update = {**result.model_dump(mode="json"), "completed": False, "outcome": "", "error": None,
                          "escalation": None, "approval_decision": "", "approval_id": None, "command_id": None}
                app.update_state({"configurable": {"thread_id": thread_id}}, update, as_node=step)
                from ui.cases.run import _stream_run
                _stream_run(app, {"configurable": {"thread_id": thread_id}}, None, "Extraktion fachlich prüfen")
                st.rerun()
            except Exception as error:
                st.error(f"Layoutklärung angehalten: {type(error).__name__}")
