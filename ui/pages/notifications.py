"""Personal approval notifications for the signed-in actor."""

from __future__ import annotations

import streamlit as st

from graph.approval_queue import ApprovalTask
from ui.cases import list as case_list
from ui.shared import i18n, style

SESSION_VISIBLE_TASKS = "approval_notification_visible_tasks"


def announce_new(actor: str, tasks: list[ApprovalTask]) -> None:
    """Toast once when new actionable cases enter this actor's queue."""
    current = {task.case.thread_id for task in tasks}
    visible_by_actor = dict(st.session_state.get(SESSION_VISIBLE_TASKS, {}))
    previous = set(visible_by_actor.get(actor, ()))
    visible_by_actor[actor] = sorted(current)
    st.session_state[SESSION_VISIBLE_TASKS] = visible_by_actor

    new_count = len(current - previous)
    if new_count:
        key = "notifications.toast.one" if new_count == 1 else "notifications.toast.many"
        st.toast(
            i18n.t(key, count=new_count),
            icon=":material/notifications_active:",
        )


def render(tasks: list[ApprovalTask]) -> None:
    style.css()
    st.title(i18n.t("page.notifications"))
    st.caption(i18n.t("notifications.caption"))

    if not tasks:
        st.info(
            i18n.t("notifications.empty"),
            icon=":material/notifications_none:",
        )
        return

    st.metric(i18n.t("notifications.metric"), len(tasks))
    case_list.as_cards(
        [task.case for task in tasks],
        key="notifications",
    )
