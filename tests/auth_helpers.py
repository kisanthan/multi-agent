"""Explicit authenticated interaction adapter for pre-v2 scenario fixtures.

It performs actual local login, attaches the displayed approval reference and
never bypasses production authentication/authorization. Security tests use the
raw graph to exercise forged or missing sessions.
"""
import config
from data.migrations import connect
from governance import identity, ad
from langgraph.types import Command

PASSWORD = "synthetic-fixture-password"


def token_for(upn):
    with connect(config.DB_PATH) as con:
        try:
            ad.load_user(con, upn)
        except ad.UnknownUser:
            return ""
        if not con.execute("SELECT 1 FROM local_credentials WHERE upn=?", (upn,)).fetchone():
            identity.set_password(con, upn, PASSWORD)
        # Other isolated scenario fixtures may have provisioned this account.
        try:
            return identity.login(con, upn, PASSWORD)
        except identity.AuthenticationError:
            identity.set_password(con, upn, PASSWORD)
            return identity.login(con, upn, PASSWORD)


class SignedInGraph:
    def __init__(self, graph):
        self.graph = graph

    def __getattr__(self, name):
        return getattr(self.graph, name)

    def invoke(self, value, config, **kwargs):
        if isinstance(value, dict):
            actor = value.get("actor", "")
        else:
            response = dict(value.resume)
            actor = response.get("approver", "")
            snapshot = self.graph.get_state(config)
            if snapshot.interrupts:
                request = snapshot.interrupts[0].value
                response.setdefault("approval_id", request.get("approval_id"))
                response.setdefault("version", request.get("version"))
            value = Command(resume=response)
        with identity.session(token_for(actor)):
            return self.graph.invoke(value, config, **kwargs)
