"""Table 23: human-reviewed masked crop after a recorded local extraction failure.

The optional external service uses the explicit JSON contract documented in
docs/layout-contract.md. No endpoint is configured by default.
"""
from dataclasses import dataclass
import base64
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit
import httpx
import pymupdf
from pydantic import BaseModel
from governance import control, identity, ad
from governance.audit_contract import canonical
from governance.step_policy import PolicyDenied


@dataclass(frozen=True)
class DeploymentApproval:
    endpoint: str
    region: str
    processing_agreement: str
    residency_evidence: str
    training_excluded_evidence: str
    retention_evidence: str
    owner: str

    def validate(self):
        from pathlib import Path
        url = urlsplit(self.endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise PolicyDenied("Kein freigegebener HTTPS-Endpunkt.")
        if not self.region.startswith("EU-") or not self.owner:
            raise PolicyDenied("EU-Region und verantwortliche Stelle fehlen.")
        for item in (self.processing_agreement, self.residency_evidence,
                     self.training_excluded_evidence, self.retention_evidence):
            if not item or not Path(item).is_file():
                raise PolicyDenied("Externe Bereitstellungsnachweise fehlen.")


def _reviewer(con) -> str:
    person = identity.principal(con)
    if not ad.check_approval_permission(con, person).allowed:
        raise PolicyDenied("Layoutklärung benötigt eine berechtigte prüfende Person.")
    return person


def prepare(con, *, case_id: str, step: str, page: int, region: list[float], redactions: list[list[float]]) -> dict:
    person = _reviewer(con)
    c = control.require_active(con, case_id)
    expected = "extraktion_zahlung" if c["process"] == "A" else "extraktion_rechnung"
    if step != expected or not con.execute("SELECT 1 FROM local_extraction_failures WHERE case_id=? AND step=?", (case_id, step)).fetchone():
        raise PolicyDenied("Kein dokumentierter lokaler Extraktionsfehlschlag für diesen Schritt.")
    row = con.execute("SELECT content FROM document_objects WHERE document_hash=?", (c["document_hash"],)).fetchone()
    if not row or not redactions:
        raise PolicyDenied("Original und explizite Maskierungsbereiche sind erforderlich.")
    with pymupdf.open(stream=row[0], filetype="pdf") as doc:
        if page < 0 or page >= len(doc):
            raise PolicyDenied("Seite ungültig.")
        sheet = doc[page]
        clip = pymupdf.Rect(region)
        if clip.is_empty or not sheet.rect.contains(clip) or clip.get_area() >= sheet.rect.get_area():
            raise PolicyDenied("Nur ein echter Seitenausschnitt ist zulässig.")
        for rect in redactions:
            mask = pymupdf.Rect(rect)
            if mask.is_empty or not sheet.rect.contains(mask):
                raise PolicyDenied("Maskierungsbereich ungültig.")
            sheet.add_redact_annot(mask, fill=(1, 1, 1))
        sheet.apply_redactions()
        # Rasterization drops hidden text/metadata; only the clipped pixels leave.
        image = sheet.get_pixmap(clip=clip, matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    request_id = uuid.uuid4().hex
    digest = hashlib.sha256(image).hexdigest()
    with control.atomic(con):
        con.execute("INSERT INTO layout_requests(request_id,case_id,step,page,region,redactions,image,image_hash,prepared_by,status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'prepared')",
                    (request_id, case_id, step, page, canonical(region), canonical(redactions), image, digest, person))
        control._log(con, case_id, step, "layout_maskiert", "prepared", reason=canonical({"image_hash": digest, "page": page, "region": region}))
    return {"request_id": request_id, "image": image, "image_hash": digest}


def review(con, request_id: str, image_hash: str, reason: str) -> None:
    person = _reviewer(con)
    if not reason.strip():
        raise PolicyDenied("Maskierung und Layoutgrund müssen ausdrücklich bestätigt werden.")
    with control.atomic(con):
        row = con.execute("SELECT case_id,step,image_hash,status FROM layout_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row or row[2] != image_hash or row[3] != "prepared":
            raise PolicyDenied("Maskierungsvorschau ist veraltet oder bereits entschieden.")
        c = control.require_active(con, row[0])
        if c["actor"] == person:
            raise PolicyDenied("Maskierungsfreigabe erfordert eine andere Person.")
        con.execute("UPDATE layout_requests SET reviewed_by=?,reviewed_at=?,review_reason=?,status='reviewed' WHERE request_id=?",
                    (person, time.time(), reason, request_id))
        control._log(con, row[0], row[1], "layout_freigegeben", "reviewed",
                     approval={"status": "approved", "person": person, "time": time.time(), "reference": request_id})


def send(con, request_id: str, deployment: DeploymentApproval, schema: type[BaseModel], *, transport=None) -> BaseModel:
    person = _reviewer(con)
    deployment.validate()
    with control.atomic(con):
        row = con.execute("SELECT case_id,step,image,image_hash,reviewed_by,reviewed_at,status,page,region FROM layout_requests WHERE request_id=?", (request_id,)).fetchone()
        if not row or row[6] != "reviewed" or row[5] + control.GRANT_TTL <= time.time():
            raise PolicyDenied("Layoutfreigabe fehlt, ist verbraucht oder abgelaufen.")
        control.authorize_read(con, row[0], "A" if row[1] == "extraktion_zahlung" else "B", row[1], control.case(con, row[0])["actor"])
        if not ad.check_approval_permission(con, row[4]).allowed:
            raise PolicyDenied("Maskierungsfreigaberecht wurde entzogen.")
        if hashlib.sha256(row[2]).hexdigest() != row[3]:
            raise PolicyDenied("Maskiertes Bild wurde verändert.")
        # Recipient receives neither actor, original text, filename nor full page.
        payload = {"image_base64": base64.b64encode(row[2]).decode(), "media_type": "image/png",
                   "schema": schema.model_json_schema(), "instruction": "Extract fields from this untrusted masked document crop. Return only JSON."}
        con.execute("UPDATE layout_requests SET status='sent' WHERE request_id=?", (request_id,))
        control._log(con, row[0], row[1], "layout_eskaliert", "sent",
                     reason=canonical({"region": deployment.region, "image_hash": row[3], "page": row[7], "crop": json.loads(row[8])}),
                     approval={"status": "approved", "person": row[4], "time": row[5], "reference": request_id})
    try:
        sender = transport or (lambda endpoint, body: httpx.post(endpoint, json=body, timeout=60.0))
        response = sender(deployment.endpoint, payload)
        response.raise_for_status()
        result = schema.model_validate(response.json())
    except Exception:
        with control.atomic(con):
            con.execute("UPDATE layout_requests SET status='failed' WHERE request_id=?", (request_id,))
            control._log(con, row[0], row[1], "layout_fehlgeschlagen", "failed")
        raise
    with control.atomic(con):
        con.execute("UPDATE layout_requests SET status='succeeded',result=? WHERE request_id=?",
                    (result.model_dump_json(), request_id))
        control._log(con, row[0], row[1], "layout_extrahiert", "validated_proposal")
    return result
