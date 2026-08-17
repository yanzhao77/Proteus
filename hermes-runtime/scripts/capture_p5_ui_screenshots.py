"""Capture Human Gate UI browser screenshots as P5-UI acceptance evidence.

Run from the repository root after installing Playwright into the runtime venv:

    hermes-runtime/.venv/bin/pip install playwright
    hermes-runtime/.venv/bin/python hermes-runtime/scripts/capture_p5_ui_screenshots.py

The script uses the locally installed Google Chrome (Playwright channel "chrome")
so no browser download is required. Screenshots are written to
docs/evidence/p5-ui/ and the process exits non-zero if any page assertion fails.
"""

import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "hermes-runtime" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from hermes_runtime.application.product_api import ProductApiFacade  # noqa: E402
from hermes_runtime.infrastructure.fastapi_app import create_app  # noqa: E402


HOST = "127.0.0.1"
PORT = 18080
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "p5-ui"


class ReadModel:
    def human_gate_request(self, gate_request_id, actor_scope):
        return {
            "gate_request_id": gate_request_id,
            "summary": "Approve verified deployment",
            "question": "Approve guarded continuation of project-1?",
            "reason": "policy requires human approval for production resume",
            "risk": "medium",
            "evidence_refs": ("evidence-1", "evidence-2"),
            "decision_id": "decision-1",
            "status": "REQUESTED",
        }

    def project_status(self, project_id, actor_scope):
        return {"project_id": project_id}

    def decision_explain(self, decision_id, actor_scope):
        return {"decision_id": decision_id}

    def replay_reconcile_findings(self, project_id, actor_scope):
        return {"findings": []}

    def docker_process_observations(self, process_id, actor_scope):
        return {"observations": []}


class Gateway:
    def submit_human_gate_decision(self, payload):
        return {"status": "ACCEPTED", "command_id": payload["command_id"]}


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    app = create_app(ProductApiFacade(ReadModel(), Gateway()))
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            response = httpx.get("http://{}:{}/livez".format(HOST, PORT), timeout=1)
            if response.status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("API server did not become ready")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            desktop = browser.new_context(
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"X-Hermes-Actor-ID": "ui-approver-1"},
            )
            page = desktop.new_page()

            page.goto("http://{}:{}/ui/human-gates".format(HOST, PORT), wait_until="networkidle")
            inbox = page.content()
            if "Human Gate Inbox" not in inbox:
                raise AssertionError("inbox page missing")
            page.screenshot(path=str(EVIDENCE_DIR / "human-gate-inbox-desktop.png"), full_page=True)

            page.goto("http://{}:{}/ui/human-gates/gate-1".format(HOST, PORT), wait_until="networkidle")
            detail = page.content()
            for marker in ("Human Gate Detail", "Approve", "Reject", "Explain/Audit"):
                if marker not in detail:
                    raise AssertionError("detail page missing: " + marker)
            for forbidden in ("apply_resume", "project_state", "task_status"):
                if forbidden in detail:
                    raise AssertionError("forbidden authority control present: " + forbidden)
            page.screenshot(path=str(EVIDENCE_DIR / "human-gate-detail-desktop.png"), full_page=True)
            desktop.close()

            mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=2,
                extra_http_headers={"X-Hermes-Actor-ID": "ui-approver-1"},
            )
            mobile_page = mobile.new_page()
            mobile_page.goto("http://{}:{}/ui/human-gates/gate-1".format(HOST, PORT), wait_until="networkidle")
            if "Human Gate Detail" not in mobile_page.content():
                raise AssertionError("mobile detail page missing")
            mobile_page.screenshot(path=str(EVIDENCE_DIR / "human-gate-detail-mobile.png"), full_page=True)
            mobile.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    print("P5 UI screenshots saved to", EVIDENCE_DIR)


if __name__ == "__main__":
    main()
