"""Only authorized immutable commands cross the target-system boundary."""
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
import httpx
import config
from governance import control
from governance.step_policy import PolicyDenied


def service_key() -> str:
    directory = Path(config.DB_PATH).parent / ".runtime_secrets"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "gateway.key"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_text(encoding="ascii").strip()
    with os.fdopen(fd, "w", encoding="ascii") as out:
        value = secrets.token_urlsafe(48)
        out.write(value)
        out.flush()
        os.fsync(out.fileno())
    return value


def local_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password:
        raise PolicyDenied("Der Prototyp erlaubt ausschließlich lokale Zielsystemendpunkte.")
    return url.rstrip("/")


def dispatch(con, command_id: str) -> dict:
    cmd = control.authorize_command(con, command_id)
    if cmd["status"] in {"succeeded", "rejected"}:
        return cmd["receipt"]
    endpoint = local_endpoint(config.settings.navision_url if cmd["step"] == "buchung" else config.settings.elo_url)
    endpoint += "/booking" if cmd["step"] == "buchung" else "/archive"
    token = control.grant(con, command_id)
    with control.atomic(con):
        control._log(con, cmd["case_id"], cmd["step"], "werkzeug_angefordert", "dispatched",
                     approval=control.approval_event(con, cmd["approval_id"]), command_id=command_id)
    try:
        response = httpx.post(endpoint, json={"command_id": command_id, "payload_hash": cmd["payload_hash"]},
                              headers={"Authorization": "Bearer " + token, "X-Service-Key": service_key()},
                              timeout=30.0)
        if response.status_code != 200:
            raise PolicyDenied(f"Zielsystem hat den Aufruf abgelehnt (HTTP {response.status_code}).")
        receipt = response.json()
        durable = control.command(con, command_id)
        if durable["status"] not in {"succeeded", "rejected"} or durable["receipt"] != receipt:
            raise PolicyDenied("Kein übereinstimmender dauerhafter Zielsystembeleg vorhanden.")
        return receipt
    except (httpx.HTTPError, ValueError):
        with control.atomic(con):
            con.execute("UPDATE execution_commands SET status='in_doubt' WHERE command_id=? "
                        "AND status NOT IN ('succeeded','rejected')", (command_id,))
            control._log(con, cmd["case_id"], cmd["step"], "wirkung_ungeklaert", "in_doubt",
                         approval=control.approval_event(con, cmd["approval_id"]), command_id=command_id)
        return {"command_id": command_id, "status": "in_doubt",
                "reason": "Antwort fehlt; Wirkung ungeklärt. Ergebnisbeleg vor Wiederholung prüfen."}
