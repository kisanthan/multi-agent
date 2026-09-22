"""Local DMS stores immutable originals and versioned business assignments."""
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict
import config
from data.bootstrap import ensure_configured_runtime
from data.migrations import connect
from governance import identity, ad
from runtime.targets import execute

app = FastAPI(title="ELO-Mock (controlled)", version="2.0")


class Filing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    payload_hash: str


@app.get("/health")
def health():
    return {"status": "ok", "system": "elo-mock"}


@app.post("/archive")
def archive(a: Filing, authorization: str = Header(default=""), x_service_key: str = Header(default="")):
    ensure_configured_runtime()
    with connect(config.DB_PATH) as con:
        return execute(con, command_id=a.command_id, digest=a.payload_hash,
                       token=authorization.removeprefix("Bearer "), supplied_key=x_service_key, audience="elo")


def _reader(con, token):
    try:
        person = identity.principal(con, token.removeprefix("Bearer "))
        if not ad.check_reader_access(con, person).allowed:
            raise identity.AuthenticationError("Kein Leserecht.")
        return person
    except identity.AuthenticationError as error:
        raise HTTPException(401, str(error)) from error


@app.get("/archive/{archive_id}")
def read_filing(archive_id: str, authorization: str = Header(default="")):
    with connect(config.DB_PATH) as con:
        _reader(con, authorization)
        row = con.execute("SELECT archive_id,filename,document_hash,filed_at FROM archive WHERE archive_id=?", (archive_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Archiv-ID nicht gefunden.")
        result = dict(zip(("archive_id", "filename", "document_hash", "filed_at"), row))
        result["assignments"] = [dict(zip(("cost_center_id", "version", "active"), x)) for x in con.execute(
            "SELECT cost_center_id,version,active FROM archive_assignments WHERE archive_id=? ORDER BY version", (archive_id,))]
        return result


@app.get("/archive/{archive_id}/content")
def read_content(archive_id: str, authorization: str = Header(default="")):
    with connect(config.DB_PATH) as con:
        person = _reader(con, authorization)
        row = con.execute("SELECT d.content,a.document_hash FROM document_objects d JOIN archive a ON "
                          "a.document_hash=d.document_hash WHERE a.archive_id=?", (archive_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Original fehlt.")
        from governance.audit import log_entry, CaseReference, Decision
        log_entry(con, actor=person, agent="elo", action="archiv_original_lesen", decision=Decision.ALLOWED,
                  reason="Authentifizierter Originalabruf.", reference=CaseReference(source=row[1]), outcome="read")
        con.commit()
        return Response(content=row[0], media_type="application/pdf")
