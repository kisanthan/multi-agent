"""Streamlit Custom Component v2 for the right-hand AI status drawer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st


_HTML = """
<div class="ai-drawer-root"></div>
"""


_CSS = """
:host {
  display: block;
  height: 0;
  position: relative;
  z-index: 1000000;
}

* {
  box-sizing: border-box;
}

.ai-drawer-shell {
  --drawer-width: min(430px, calc(100vw - 56px));
  color: var(--st-text-color, #1f2937);
  font-family: var(--st-font, sans-serif);
  height: 100dvh;
  position: fixed;
  right: 0;
  top: 0;
  transform: translateX(100%);
  transition: transform 220ms ease;
  width: var(--drawer-width);
  z-index: 1000000;
}

.ai-drawer-shell[data-open="true"] {
  transform: translateX(0);
}

.ai-drawer-toggle {
  align-items: center;
  background: var(--st-background-color, #ffffff);
  border: 1px solid var(--st-border-color, #d8dee9);
  border-right: 0;
  border-radius: var(--st-button-radius, 0.5rem) 0 0 var(--st-button-radius, 0.5rem);
  box-shadow: -5px 3px 16px rgb(15 23 42 / 12%);
  color: var(--st-text-color, #1f2937);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  font: inherit;
  gap: 1px;
  height: 58px;
  justify-content: center;
  left: -48px;
  padding: 0;
  position: absolute;
  top: 92px;
  width: 48px;
}

.ai-drawer-toggle:hover,
.ai-drawer-toggle:focus-visible,
.ai-drawer-collapse:hover,
.ai-drawer-collapse:focus-visible {
  border-color: var(--st-primary-color, #0068c9);
  color: var(--st-primary-color, #0068c9);
  outline: none;
}

.ai-drawer-toggle__mark {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1;
}

.ai-drawer-toggle__chevron {
  font-size: 1.5rem;
  line-height: 0.8;
}

.ai-drawer {
  background: var(--st-background-color, #ffffff);
  border-left: 1px solid var(--st-border-color, #d8dee9);
  box-shadow: -12px 0 32px rgb(15 23 42 / 14%);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.ai-drawer-header {
  align-items: center;
  border-bottom: 1px solid var(--st-border-color-light, #e6eaf0);
  display: flex;
  flex: 0 0 auto;
  gap: 0.7rem;
  min-height: 72px;
  padding: 1.2rem 1.35rem;
}

.ai-drawer-header__icon {
  align-items: center;
  background: var(--st-secondary-background-color, #f3f6fa);
  border-radius: 999px;
  color: var(--st-primary-color, #0068c9);
  display: inline-flex;
  font-size: 0.72rem;
  font-weight: 800;
  height: 34px;
  justify-content: center;
  letter-spacing: 0.02em;
  width: 34px;
}

.ai-drawer-header h2 {
  color: var(--st-heading-color, var(--st-text-color, #1f2937));
  font-family: var(--st-heading-font, var(--st-font, sans-serif));
  font-size: 1.25rem;
  font-weight: 650;
  line-height: 1.25;
  margin: 0;
}

.ai-drawer-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 1.2rem 1.35rem 1.4rem;
  scrollbar-color: var(--st-border-color, #cbd5e1) transparent;
  scrollbar-width: thin;
}

.ai-drawer-status {
  align-items: flex-start;
  display: flex;
  gap: 0.65rem;
  margin-bottom: 1.25rem;
}

.ai-drawer-status__indicator,
.ai-drawer-step__indicator {
  align-items: center;
  border: 1.5px solid var(--st-border-color, #9aa4b2);
  border-radius: 999px;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 0.72rem;
  height: 19px;
  justify-content: center;
  margin-top: 0.1rem;
  width: 19px;
}

.ai-drawer-status[data-state="complete"] .ai-drawer-status__indicator,
.ai-drawer-step[data-state="complete"] .ai-drawer-step__indicator {
  border-color: var(--st-green-color, #15803d);
  color: var(--st-green-color, #15803d);
}

.ai-drawer-status[data-state="error"] .ai-drawer-status__indicator,
.ai-drawer-step[data-state="error"] .ai-drawer-step__indicator {
  border-color: var(--st-red-color, #dc2626);
  color: var(--st-red-color, #dc2626);
}

.ai-drawer-status[data-state="running"] .ai-drawer-status__indicator,
.ai-drawer-step[data-state="running"] .ai-drawer-step__indicator {
  animation: ai-drawer-spin 800ms linear infinite;
  border-color: var(--st-primary-color, #0068c9) transparent var(--st-primary-color, #0068c9) var(--st-primary-color, #0068c9);
}

@keyframes ai-drawer-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .ai-drawer-shell { transition: none; }
  .ai-drawer-status[data-state="running"] .ai-drawer-status__indicator,
  .ai-drawer-step[data-state="running"] .ai-drawer-step__indicator {
    animation: none;
  }
}

.ai-drawer-status__label {
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.35;
}

.ai-drawer-document {
  color: color-mix(in srgb, var(--st-text-color, #1f2937) 70%, transparent);
  font-size: 0.94rem;
  line-height: 1.45;
  margin: 0 0 1.55rem;
  overflow-wrap: anywhere;
}

.ai-drawer-steps {
  display: grid;
  gap: 1.35rem;
}

.ai-drawer-step__heading {
  align-items: flex-start;
  display: flex;
  gap: 0.55rem;
}

.ai-drawer-step__label {
  font-size: 1rem;
  font-weight: 650;
  line-height: 1.35;
}

.ai-drawer-step__model,
.ai-drawer-step__detail {
  color: color-mix(in srgb, var(--st-text-color, #1f2937) 68%, transparent);
  font-size: 0.88rem;
  line-height: 1.4;
  margin: 0.55rem 0 0 1.55rem;
  overflow-wrap: anywhere;
}

.ai-drawer-step__detail {
  color: var(--st-text-color, #1f2937);
  font-size: 0.96rem;
}

.ai-drawer-results-title {
  color: var(--st-heading-color, var(--st-text-color, #1f2937));
  font-size: 1rem;
  font-weight: 650;
  margin: 1.8rem 0 0.8rem;
}

.ai-drawer-table-wrap {
  border: 1px solid var(--st-dataframe-border-color, var(--st-border-color, #d8dee9));
  border-radius: var(--st-base-radius, 0.5rem);
  overflow: hidden;
}

.ai-drawer-table {
  border-collapse: collapse;
  font-size: 0.9rem;
  table-layout: fixed;
  width: 100%;
}

.ai-drawer-table th,
.ai-drawer-table td {
  border-bottom: 1px solid var(--st-dataframe-border-color, var(--st-border-color, #d8dee9));
  padding: 0.62rem 0.7rem;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}

.ai-drawer-table th + th,
.ai-drawer-table td + td {
  border-left: 1px solid var(--st-dataframe-border-color, var(--st-border-color, #d8dee9));
}

.ai-drawer-table th {
  background: var(--st-dataframe-header-background-color, var(--st-secondary-background-color, #f3f6fa));
  font-weight: 600;
}

.ai-drawer-table tr:last-child td {
  border-bottom: 0;
}

.ai-drawer-error {
  background: var(--st-red-background-color, #fff1f2);
  border: 1px solid color-mix(in srgb, var(--st-red-color, #dc2626) 35%, transparent);
  border-radius: var(--st-base-radius, 0.5rem);
  color: var(--st-red-text-color, #991b1b);
  font-size: 0.9rem;
  line-height: 1.45;
  margin-top: 1.25rem;
  padding: 0.8rem 0.9rem;
  overflow-wrap: anywhere;
}

.ai-drawer-footer {
  background: var(--st-background-color, #ffffff);
  border-top: 1px solid var(--st-border-color-light, #e6eaf0);
  flex: 0 0 auto;
  padding: 0.9rem 1.35rem 1.1rem;
}

.ai-drawer-collapse {
  align-items: center;
  background: transparent;
  border: 1px solid var(--st-widget-border-color, var(--st-border-color, #d8dee9));
  border-radius: var(--st-button-radius, 0.5rem);
  color: var(--st-text-color, #1f2937);
  cursor: pointer;
  display: flex;
  font: inherit;
  gap: 0.55rem;
  justify-content: center;
  min-height: 44px;
  padding: 0.6rem 0.8rem;
  width: 100%;
}

.ai-drawer-collapse__icon {
  font-size: 1.3rem;
  line-height: 1;
}

@media (max-width: 540px) {
  .ai-drawer-shell {
    --drawer-width: calc(100vw - 48px);
  }

  .ai-drawer-toggle {
    left: -42px;
    width: 42px;
  }

  .ai-drawer-header,
  .ai-drawer-scroll,
  .ai-drawer-footer {
    padding-left: 1rem;
    padding-right: 1rem;
  }
}
"""


_JS = """
const drawerStates = new WeakMap()

function createElement(tag, className, text) {
  const element = document.createElement(tag)
  if (className) element.className = className
  if (text !== undefined && text !== null) element.textContent = String(text)
  return element
}

function statusMark(state) {
  if (state === "complete") return "✓"
  if (state === "error") return "!"
  return ""
}

function setOpen(shell, body, toggle, state, labels) {
  shell.dataset.open = String(state.open)
  body.inert = !state.open
  toggle.setAttribute("aria-expanded", String(state.open))
  toggle.setAttribute("aria-label", state.open ? labels.collapse : labels.expand)
  toggle.title = state.open ? labels.collapse : labels.expand
  toggle.querySelector(".ai-drawer-toggle__chevron").textContent = state.open ? "›" : "‹"
}

function addStep(container, step) {
  const section = createElement("section", "ai-drawer-step")
  section.dataset.state = step.state

  const heading = createElement("div", "ai-drawer-step__heading")
  const indicator = createElement(
    "span",
    "ai-drawer-step__indicator",
    statusMark(step.state),
  )
  indicator.setAttribute("aria-hidden", "true")
  heading.append(indicator, createElement("span", "ai-drawer-step__label", step.label))
  section.appendChild(heading)

  if (step.model) {
    section.appendChild(createElement("p", "ai-drawer-step__model", step.model))
  }
  if (step.detail) {
    section.appendChild(createElement("p", "ai-drawer-step__detail", step.detail))
  }
  container.appendChild(section)
}

function addTable(container, data) {
  if (!Array.isArray(data.rows) || data.rows.length === 0) return

  container.appendChild(createElement("h3", "ai-drawer-results-title", data.labels.results))
  const wrap = createElement("div", "ai-drawer-table-wrap")
  const table = createElement("table", "ai-drawer-table")
  const head = document.createElement("thead")
  const headRow = document.createElement("tr")
  headRow.append(
    createElement("th", "", data.labels.field),
    createElement("th", "", data.labels.value),
  )
  head.appendChild(headRow)
  table.appendChild(head)

  const body = document.createElement("tbody")
  data.rows.forEach((row) => {
    const tableRow = document.createElement("tr")
    tableRow.append(
      createElement("td", "", row.field),
      createElement("td", "", row.value),
    )
    body.appendChild(tableRow)
  })
  table.appendChild(body)
  wrap.appendChild(table)
  container.appendChild(wrap)
}

export default function(component) {
  const { data, parentElement } = component
  const root = parentElement.querySelector(".ai-drawer-root")
  if (!root || !data) return

  let state = drawerStates.get(parentElement)
  if (!state) {
    state = { open: Boolean(data.initial_open), revision: data.open_revision ?? null }
    drawerStates.set(parentElement, state)
  } else if (
    data.force_open &&
    data.open_revision &&
    data.open_revision !== state.revision
  ) {
    state.open = true
  }
  state.revision = data.open_revision ?? state.revision

  const shell = createElement("aside", "ai-drawer-shell")
  shell.setAttribute("aria-label", data.labels.title)

  const toggle = createElement("button", "ai-drawer-toggle")
  toggle.type = "button"
  toggle.append(
    createElement("span", "ai-drawer-toggle__mark", "KI"),
    createElement("span", "ai-drawer-toggle__chevron"),
  )

  const panel = createElement("div", "ai-drawer")
  const header = createElement("header", "ai-drawer-header")
  header.append(
    createElement("span", "ai-drawer-header__icon", "KI"),
    createElement("h2", "", data.labels.title),
  )
  panel.appendChild(header)

  const scroll = createElement("div", "ai-drawer-scroll")
  scroll.setAttribute("aria-live", "polite")

  const status = createElement("div", "ai-drawer-status")
  status.dataset.state = data.status.state
  const statusIndicator = createElement(
    "span",
    "ai-drawer-status__indicator",
    statusMark(data.status.state),
  )
  statusIndicator.setAttribute("aria-hidden", "true")
  status.append(
    statusIndicator,
    createElement("span", "ai-drawer-status__label", data.status.label),
  )
  scroll.appendChild(status)
  scroll.appendChild(createElement("p", "ai-drawer-document", data.document))

  const steps = createElement("div", "ai-drawer-steps")
  data.steps.forEach((step) => addStep(steps, step))
  scroll.appendChild(steps)
  addTable(scroll, data)

  if (data.error) {
    const error = createElement("div", "ai-drawer-error", data.error)
    error.setAttribute("role", "alert")
    scroll.appendChild(error)
  }
  panel.appendChild(scroll)

  const footer = createElement("footer", "ai-drawer-footer")
  const collapse = createElement("button", "ai-drawer-collapse")
  collapse.type = "button"
  collapse.append(
    createElement("span", "ai-drawer-collapse__icon", "›"),
    createElement("span", "", data.labels.collapse),
  )
  footer.appendChild(collapse)
  panel.appendChild(footer)

  shell.append(toggle, panel)
  root.replaceChildren(shell)

  const toggleDrawer = () => {
    state.open = !state.open
    setOpen(shell, panel, toggle, state, data.labels)
  }
  toggle.onclick = toggleDrawer
  collapse.onclick = toggleDrawer
  setOpen(shell, panel, toggle, state, data.labels)
}
"""


_AI_DRAWER = st.components.v2.component(
    "ai_status_drawer",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def ai_status_drawer(data: Mapping[str, Any], *, key: str) -> None:
    """Mount the fixed-position drawer without taking page layout space."""
    _AI_DRAWER(data=dict(data), key=key, width="stretch", height=1)
