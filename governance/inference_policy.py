"""Data-flow policy independent of provider SDKs and model output."""
from urllib.parse import urlsplit
from agent_registry import get_config, ModelClass
from governance.step_policy import PolicyDenied

AGENT_PROFILES = {"klassifikation": "router", "extraktion_zahlung": "payment", "extraktion_rechnung": "invoice"}


def authorize_local(agent_id: str, provider: str, endpoint: str) -> None:
    cfg = get_config(agent_id)
    if agent_id not in AGENT_PROFILES or cfg.model_class is ModelClass.NO_MODEL or not cfg.active:
        raise PolicyDenied("Diese Komponente darf kein Modell aufrufen.")
    if "model.local" not in cfg.allowed_tools:
        raise PolicyDenied("Inferenzwerkzeug nicht freigegeben.")
    url = urlsplit(endpoint)
    if provider != "ollama" or url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password:
        raise PolicyDenied("Klassifikation und Standardextraktion dürfen nur am registrierten lokalen Endpoint laufen.")


def deny_unscoped_cloud() -> None:
    raise PolicyDenied("Unmaskierte Standardprompts sind für Cloudmodelle gesperrt. Layout-Eskalation benötigt einen separaten Nachweis.")
