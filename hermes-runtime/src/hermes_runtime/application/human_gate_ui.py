from html import escape
from typing import Any, Mapping, Tuple


class HumanGateUiRejected(ValueError):
    pass


class HumanGateUiRenderer:
    def render_inbox(self, gates: Tuple[Mapping[str, Any], ...]) -> str:
        items = "\n".join(
            "<li><a href=\"/ui/human-gates/{id}\">{id}</a> — {summary}</li>".format(
                id=escape(str(gate.get("gate_request_id", ""))),
                summary=escape(str(gate.get("summary", gate.get("question", "")))),
            )
            for gate in gates
        )
        return self._page("Human Gate Inbox", f"<h1>Human Gate Inbox</h1><ul>{items}</ul>")

    def render_detail(self, gate: Mapping[str, Any]) -> str:
        self._reject_unsafe(gate)
        gate_id = escape(str(gate.get("gate_request_id", "")))
        evidence = "".join("<li>{}</li>".format(escape(str(ref))) for ref in gate.get("evidence_refs", ()))
        body = f"""
        <h1>Human Gate Detail</h1>
        <section id="question">{escape(str(gate.get("question", "")))}</section>
        <section id="reason">{escape(str(gate.get("reason", "")))}</section>
        <section id="risk">{escape(str(gate.get("risk", "")))}</section>
        <section id="evidence"><ul>{evidence}</ul></section>
        <a id="explain-link" href="/decisions/{escape(str(gate.get('decision_id', '')))} /explain">Explain/Audit</a>
        <form method="post" action="/ui/human-gates/{gate_id}/decisions">
          <input type="hidden" name="decision" value="APPROVE" />
          <button type="submit">Approve</button>
        </form>
        <form method="post" action="/ui/human-gates/{gate_id}/decisions">
          <input type="hidden" name="decision" value="REJECT" />
          <button type="submit">Reject</button>
        </form>
        <section id="status">{escape(str(gate.get("status", "REQUESTED")))}</section>
        """
        if any(marker in body.lower() for marker in ("apply_resume", "project_state", "task_status", "set_project_state", "update_task_status")):
            raise HumanGateUiRejected("UI_GENERIC_AUTHORITY_CONTROL_FORBIDDEN")
        return self._page("Human Gate Detail", body)

    def _page(self, title: str, body: str) -> str:
        return "<!doctype html><html><head><title>{}</title><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /></head><body>{}</body></html>".format(
            escape(title),
            body,
        )

    def _reject_unsafe(self, payload: Mapping[str, Any]) -> None:
        text = repr(payload).lower()
        if any(marker in text for marker in ("secret_value", "password=", "api_key", "token=")):
            raise HumanGateUiRejected("UI_SECRET_VALUE_FORBIDDEN")
