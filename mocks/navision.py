"""Authenticated local ERP demonstrator; effects require a scoped command."""
from fastapi import FastAPI, Header
from pydantic import BaseModel, ConfigDict
import config
from data.bootstrap import ensure_configured_runtime
from data.migrations import connect
from runtime.targets import execute

app = FastAPI(title="Navision-Mock (controlled)", version="2.0")


class Booking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    payload_hash: str


@app.get("/health")
def health():
    return {"status": "ok", "system": "navision-mock"}


@app.post("/booking")
def book_payment(b: Booking, authorization: str = Header(default=""), x_service_key: str = Header(default="")):
    ensure_configured_runtime()
    with connect(config.DB_PATH) as con:
        return execute(con, command_id=b.command_id, digest=b.payload_hash,
                       token=authorization.removeprefix("Bearer "), supplied_key=x_service_key, audience="navision")
