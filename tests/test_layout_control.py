"""Masked escalation transport tests with synthetic PDFs and no outbound calls."""
import hashlib
import json
import time
import pytest
import pymupdf
from pydantic import BaseModel
from governance import control, identity
from governance.step_policy import PolicyDenied
from llm import layout
from tests.test_control_contracts import tokens, SUBMITTER, APPROVER


class Result(BaseModel):
    number: str


@pytest.fixture
def layout_case(con, tokens):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((30, 40), "PERSON SECRET ACCOUNT")
    page.insert_text((30, 160), "Invoice R-1")
    raw = doc.tobytes()
    doc.close()
    with identity.session(tokens[SUBMITTER]):
        control.register_case(con, case_id="layout-case", actor=SUBMITTER,
                              document_hash=hashlib.sha256(raw).hexdigest(), filename="private.pdf", content=raw)
    control.select_process(con, "layout-case", "A")
    return "layout-case"


def prepare(con, tokens, case_id):
    with identity.session(tokens[APPROVER]):
        return layout.prepare(con, case_id=case_id, step="extraktion_zahlung", page=0,
                              region=[0, 0, 400, 200], redactions=[[0, 0, 400, 100]])


def test_no_escalation_without_local_failure(con, tokens, layout_case):
    with pytest.raises(PolicyDenied, match="lokaler"):
        prepare(con, tokens, layout_case)


def test_only_reviewed_masked_crop_crosses_transport(con, tokens, layout_case, tmp_path):
    con.execute("INSERT INTO local_extraction_failures VALUES(?,?,?,?)",
                (layout_case, "extraktion_zahlung", "local_schema_failure", time.time()))
    con.commit()
    item = prepare(con, tokens, layout_case)
    pixel = pymupdf.Pixmap(item["image"])
    assert pixel.width == 800 and pixel.height == 400
    assert pixel.pixel(70, 75) == (255, 255, 255)
    evidence = tmp_path / "synthetic-evidence.txt"
    evidence.write_text("Synthetic deployment approval for transport tests only.")
    approval = layout.DeploymentApproval("https://layout.invalid/extract", "EU-TEST",
                                         str(evidence), str(evidence), str(evidence),
                                         str(evidence), "Test owner")
    calls = []
    def transport(endpoint, body):
        calls.append(body)
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"number": "R-1"}
        return Response()
    with identity.session(tokens[APPROVER]):
        with pytest.raises(PolicyDenied):
            layout.send(con, item["request_id"], approval, Result, transport=transport)
        layout.review(con, item["request_id"], item["image_hash"], "Layout failure and all sensitive fields reviewed.")
        result = layout.send(con, item["request_id"], approval, Result, transport=transport)
        with pytest.raises(PolicyDenied):
            layout.send(con, item["request_id"], approval, Result, transport=transport)
    assert result.number == "R-1"
    assert len(calls) == 1
    assert set(calls[0]) == {"image_base64", "media_type", "schema", "instruction"}
    assert "PERSON SECRET" not in json.dumps(calls[0]) and "private.pdf" not in json.dumps(calls[0])


def test_full_page_or_missing_mask_is_denied(con, tokens, layout_case):
    con.execute("INSERT INTO local_extraction_failures VALUES(?,?,?,?)",
                (layout_case, "extraktion_zahlung", "failed", time.time()))
    con.commit()
    with identity.session(tokens[APPROVER]), pytest.raises(PolicyDenied):
        layout.prepare(con, case_id=layout_case, step="extraktion_zahlung", page=0,
                       region=[0, 0, 600, 800], redactions=[[0, 0, 100, 100]])


def test_missing_provider_evidence_denies_cloud():
    with pytest.raises(PolicyDenied):
        layout.DeploymentApproval("https://layout.invalid", "EU-DE", "", "", "", "", "owner").validate()
