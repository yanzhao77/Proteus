"""Non-authoritative Factory Workspace UI skeleton.

This module intentionally contains only static, server-rendered information
architecture for the Production Entry experience. It does not import database,
command, scheduler, worker, trial, or authority modules. All displayed data is a
labelled UI fixture until a future source-derived read model is wired.
"""

from __future__ import annotations

from html import escape
from typing import Iterable


_DEMO_NOTICE = (
    "DEMO / NON-AUTHORITATIVE UI FIXTURE — not connected to Project, Task, "
    "Execution, Worker, Gate, or P6 runtime authority."
)


class FactoryWorkspaceRenderer:
    """Renders navigable Factory Workspace information architecture only."""

    def render_home(self) -> str:
        content = """
        <section class="hero" aria-labelledby="idea-title">
          <p class="eyebrow">FACTORY HOME // ENTRY</p>
          <h1 id="idea-title">What do you want to build?</h1>
          <p class="lede">Start with an outcome. Proteus will turn the idea into a reviewable plan before any production is created.</p>
          <form action="/drafts/demo-draft" method="get" class="idea-composer" aria-label="Idea Composer demo">
            <label for="idea">Describe the software outcome you want to produce</label>
            <textarea id="idea" name="idea" rows="5" placeholder="For example: a team workspace for incident response…"></textarea>
            <button type="submit">Start Planning <span aria-hidden="true">→</span></button>
          </form>
        </section>
        <div class="deck-grid">
          <section class="deck attention" aria-labelledby="actions-title">
            <p class="eyebrow">ACTION REQUIRED</p><h2 id="actions-title">No live gate data connected</h2>
            <p>When the source-derived Gate inbox is wired, waiting human approvals and recovery blockers will appear here.</p>
            <a class="quiet-link" href="/gates">Open Gate Inbox</a>
          </section>
          <section class="deck" aria-labelledby="continue-title">
            <p class="eyebrow">CONTINUE PRODUCTION</p><h2 id="continue-title">No live production snapshot connected</h2>
            <p>Running, paused, recovering and waiting productions will be sourced from authoritative Project projections.</p>
            <a class="quiet-link" href="/productions">Open Portfolio</a>
          </section>
          <section class="deck" aria-labelledby="outcomes-title">
            <p class="eyebrow">RECENT OUTCOMES</p><h2 id="outcomes-title">No outcomes yet</h2>
            <p>Completed, failed and cancelled outcomes are read-only projection data, not browser state.</p>
          </section>
        </div>
        <section class="status-strip" aria-label="Factory Status">
          <span>FACTORY STATUS</span><strong>NOT CONNECTED</strong><span>Snapshot-first read model required</span>
        </section>
        """
        return self._page("Factory Home", content)

    def render_new(self) -> str:
        content = """
        <section class="hero compact" aria-labelledby="new-title">
          <p class="eyebrow">NEW PRODUCTION // IDEA INPUT</p>
          <h1 id="new-title">Start with the outcome, not implementation choices.</h1>
          <p class="lede">Frameworks, databases, workers and models are assumptions or plan inputs. This fixture does not submit an authoritative Draft.</p>
          <form action="/drafts/demo-draft" method="get" class="idea-composer" aria-label="New Idea demo">
            <label for="new-idea">What do you want to build?</label>
            <textarea id="new-idea" name="idea" rows="7" placeholder="A concise product goal…"></textarea>
            <button type="submit">Continue to Draft <span aria-hidden="true">→</span></button>
          </form>
        </section>
        """
        return self._page("New Production", content)

    def render_draft(self, draft_id: str) -> str:
        safe_id = escape(draft_id)
        content = f"""
        <section class="hero compact" aria-labelledby="draft-title">
          <p class="eyebrow">DRAFT {safe_id} // FIXTURE FLOW</p>
          <h1 id="draft-title">Idea → Understanding → Proposal → Master Plan</h1>
          <p class="lede">This route demonstrates Entry flow navigation only. No Draft, Plan, Project or approval receipt has been created.</p>
        </section>
        <ol class="flow" aria-label="Production Entry flow">
          <li class="current"><strong>01 IDEA</strong><span>Captured as an eventual immutable revision.</span></li>
          <li><strong>02 UNDERSTANDING</strong><span>Structured objective, users, outcomes, unknowns and assumptions.</span></li>
          <li><strong>03 CLARIFICATION</strong><span>One to three high-impact questions; not a Human Gate.</span></li>
          <li><strong>04 PROPOSAL</strong><span>Scope, approach, risk, verification and delivery strategy.</span></li>
          <li><strong>05 MASTER PLAN</strong><span>Revision/hash review before explicit approval.</span></li>
          <li><strong>06 APPROVAL BRIDGE</strong><span>Only future boundary that may delegate to existing Project authority.</span></li>
        </ol>
        <section class="deck" aria-labelledby="approval-title">
          <p class="eyebrow">PLAN APPROVAL</p><h2 id="approval-title">Authority bridge is not connected</h2>
          <p>An accepted command receipt is not Production Created. The UI must wait for authoritative Project/Graph/Verification source confirmation.</p>
          <a class="quiet-link" href="/productions/demo-production">Preview Live Production Handoff</a>
        </section>
        """
        return self._page("Production Draft", content)

    def render_productions(self) -> str:
        content = """
        <section class="hero compact" aria-labelledby="portfolio-title">
          <p class="eyebrow">PRODUCTION PORTFOLIO // READ MODEL</p>
          <h1 id="portfolio-title">Authoritative production snapshots will appear here.</h1>
          <p class="lede">Portfolio cards require Project, Gate, verification, evidence and freshness projections. This fixture intentionally has no simulated runtime state.</p>
        </section>
        <section class="empty-state"><h2>No production projection connected</h2><p>Connect a source-derived Portfolio read model; do not create a separate Production authority.</p><a href="/new">Start a fixture Entry flow</a></section>
        """
        return self._page("Productions", content)

    def render_production(self, production_id: str) -> str:
        safe_id = escape(production_id)
        content = f"""
        <section class="hero compact" aria-labelledby="production-title">
          <p class="eyebrow">LIVE PRODUCTION // HANDOFF</p>
          <h1 id="production-title">Production {safe_id}</h1>
          <p class="lede">Live Production will render a source-derived Project snapshot, workflow, Gate, verification, evidence, recovery and delivery facts.</p>
        </section>
        <section class="deck attention"><h2>Runtime snapshot unavailable</h2><p>This fixture has no Project binding and cannot display or control Worker, Task, Execution, Scheduler or Verification state.</p><a class="quiet-link" href="/productions">Return to Portfolio</a></section>
        """
        return self._page("Live Production", content)

    def render_gates(self) -> str:
        content = """
        <section class="hero compact" aria-labelledby="gates-title">
          <p class="eyebrow">ACTION REQUIRED // HUMAN GATES</p>
          <h1 id="gates-title">Gate decisions stay in existing Gate authority.</h1>
          <p class="lede">Factory Home can show a source-derived inbox and route users to existing Gate detail. It must not inline direct state mutation.</p>
        </section>
        <section class="empty-state"><h2>No Gate inbox projection connected</h2><p>Existing minimal Gate UI remains available when a real Gate ID is supplied by the read model.</p><a href="/ui/human-gates">Open Existing Gate UI</a></section>
        """
        return self._page("Gates", content)

    def _page(self, title: str, content: str) -> str:
        navigation = self._navigation()
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Proteus</title>
  <style>
    :root {{ color-scheme: dark; --canvas:#071014; --surface:#0c1a20; --line:#294a53; --ink:#e6f7f5; --muted:#9bb9b7; --cyan:#55e5de; --amber:#f1b95a; --red:#ff737b; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--canvas); color:var(--ink); font-family:ui-sans-serif,system-ui,sans-serif; line-height:1.5; }}
    body:before {{ content:""; position:fixed; inset:0; pointer-events:none; opacity:.045; background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px); background-size:48px 48px; }}
    a {{ color:var(--cyan); }} .shell {{ position:relative; max-width:1280px; margin:auto; padding:24px; }} header {{ display:flex; gap:20px; justify-content:space-between; align-items:center; border-bottom:1px solid var(--line); padding:0 0 16px; }}
    .brand {{ font-weight:800; letter-spacing:.14em; }} nav {{ display:flex; gap:14px; flex-wrap:wrap; }} nav a {{ color:var(--muted); text-decoration:none; font-size:.85rem; }} nav a:hover, nav a:focus {{ color:var(--cyan); }} .notice {{ border-left:3px solid var(--amber); background:#261f13; color:#ffe9bd; padding:10px 12px; font:600 .75rem ui-monospace,monospace; margin:20px 0; }}
    .hero,.deck,.empty-state {{ background:linear-gradient(145deg,rgba(12,26,32,.98),rgba(7,16,20,.94)); border:1px solid var(--line); clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px)); }}
    .hero {{ padding:56px; margin:24px 0; }} .hero.compact {{ padding:36px; }} .eyebrow {{ color:var(--cyan); font:700 .76rem ui-monospace,monospace; letter-spacing:.1em; }} h1 {{ margin:.25rem 0 1rem; font-size:clamp(2rem,5vw,3.9rem); line-height:1.05; }} h2 {{ margin:.25rem 0 .7rem; font-size:1.2rem; }} .lede {{ color:var(--muted); max-width:780px; }}
    .idea-composer {{ display:grid; gap:10px; margin-top:28px; max-width:780px; }} label {{ font-weight:700; }} textarea {{ resize:vertical; padding:16px; background:#071014; border:1px solid var(--line); color:var(--ink); font:1rem ui-sans-serif,system-ui,sans-serif; }} textarea:focus {{ outline:2px solid var(--cyan); outline-offset:2px; }} button {{ justify-self:start; border:1px solid var(--cyan); background:var(--cyan); color:#062126; padding:12px 16px; font-weight:800; cursor:pointer; }}
    .deck-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }} .deck,.empty-state {{ padding:22px; }} .attention {{ border-color:#6f5528; }} .quiet-link {{ font-weight:700; }} .status-strip {{ display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; padding:12px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); color:var(--muted); font:.8rem ui-monospace,monospace; }} .status-strip strong {{ color:var(--amber); }}
    .flow {{ list-style:none; padding:0; display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }} .flow li {{ border-left:2px solid var(--line); padding:12px; background:rgba(12,26,32,.7); }} .flow li.current {{ border-color:var(--cyan); }} .flow strong,.flow span {{ display:block; }} .flow span {{ color:var(--muted); font-size:.88rem; }}
    @media (max-width:760px) {{ .shell {{ padding:16px; }} header {{ align-items:flex-start; flex-direction:column; }} .hero,.hero.compact {{ padding:26px; }} .deck-grid,.flow {{ grid-template-columns:1fr; }} }} @media (prefers-reduced-motion:reduce) {{ * {{ scroll-behavior:auto; }} }}
  </style>
</head>
<body><main class="shell"><header><div class="brand">PROTEUS // FACTORY</div>{navigation}</header><aside class="notice" aria-label="Demo status">{_DEMO_NOTICE}</aside>{content}</main></body>
</html>"""

    @staticmethod
    def _navigation() -> str:
        links: Iterable[tuple[str, str]] = (
            ("/home", "Home"), ("/productions", "Productions"),
            ("/gates", "Gates"), ("/new", "New Entry"),
        )
        return "<nav aria-label=\"Factory navigation\">" + "".join(
            '<a href="{}">{}</a>'.format(path, label) for path, label in links
        ) + "</nav>"
