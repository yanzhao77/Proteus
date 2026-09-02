import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { createAdapters } from './api';
import type { AdapterResult, CommandMetadata, DraftListViewModel, GateViewModel, LiveProductionSnapshotViewModel, ProductionCardViewModel } from './models';
import { Icon, IconButton, PreferencePanel, StatusBadge, UiProvider, ViewState } from './design-system';
import { useUi } from './ui-context';
import { endSession, readSession } from './api/session';
import { reconcileE11Receipt, type E11ReconciliationContext } from './e11Reconciliation';
import { E13ProposalPlanEditor } from './e13ProposalPlanEditor';
import { WorkerFleet } from './components/WorkerFleet';
import { WorkerDetail } from './components/WorkerDetail';
import { ExecutionQueue } from './components/ExecutionQueue';

const adapters = createAdapters();

type Resource<T> = { phase: 'loading' | 'data' | 'error' | 'unavailable'; value?: T; message?: string };
function useResource<T>(loader: () => Promise<AdapterResult<T>>, deps: readonly unknown[] = []) {
  const [state, setState] = useState<Resource<T>>({ phase: 'loading' });
  const load = useCallback(() => {
    setState({ phase: 'loading' });
    return loader().then((result) => setState(result.kind === 'data' ? { phase: 'data', value: result.value } : { phase: result.kind === 'not_implemented' ? 'unavailable' : 'error', message: result.message })).catch(() => setState({ phase: 'error', message: 'Network request failed.' }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { void load(); }, [load]);
  return { ...state, reload: load };
}
function metadata(expectedVersion: number): CommandMetadata {
  return { expectedVersion, reason: 'Workspace request', idempotencyKey: `workspace-${crypto.randomUUID()}` };
}
function Shell({ children }: { children: ReactNode }) {
  const { t } = useUi();
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const session = useResource(async () => { const result = await readSession(); return result.kind === 'unauthenticated' ? { kind: 'not_implemented' as const, message: result.message } : result; }, []);
  const signOut = async () => { if (await endSession()) void session.reload(); };
  const nav = [
    ['/home', 'home', 'home'], ['/productions', 'grid', 'productions'], ['/drafts', 'info', 'drafts'], ['/gates', 'gate', 'gates'], ['/workers', 'grid', 'workers'], ['/new', 'plus', 'newEntry'],
  ] as const;
  return <div className="workspace-shell"><a className="skip-link" href="#workspace-main">{t('skipToContent')}</a><aside className="workspace-sidebar"><Link className="workspace-brand" to="/home"><span className="workspace-brand-mark">P</span><span>{t('appName')}<small className="ui-kicker">{t('workspace')}</small></span></Link><nav className="workspace-nav" aria-label={t('workspaceNavigation')}>{nav.map(([to, icon, label]) => <NavLink key={to} to={to}><Icon name={icon}/><span>{t(label)}</span></NavLink>)}</nav></aside><main id="workspace-main" className="workspace-main" tabIndex={-1}><header className="workspace-topbar"><span className="ui-kicker">{t('readOnly')} · {t('productApi')}</span><div className="workspace-identity"><StatusBadge value={session.phase === 'data' ? 'CURRENT' : t('signedOut')} />{session.phase === 'data' && <button className="ui-button secondary" onClick={() => void signOut()}>{session.value?.subject}</button>}<IconButton icon="settings" label={t('settings')} onClick={() => setPreferencesOpen((value) => !value)} pressed={preferencesOpen}/></div></header>{preferencesOpen && <PreferencePanel onClose={() => setPreferencesOpen(false)}/>}<div className="workspace-content">{children}</div></main></div>;
}
function PageHead({ title, detail, actions }: { title: string; detail: string; actions?: ReactNode }) { const { t } = useUi(); return <header className="ui-page-head"><div><span className="ui-kicker">{t('appName')} / {t('workspace')}</span><h1>{title}</h1><p>{detail}</p></div>{actions}</header>; }
function ResourceState<T>(resource: Resource<T> & { reload: () => unknown }) { const { t } = useUi(); if (resource.phase === 'loading') return <ViewState kind="loading"/>; if (resource.phase === 'error') return <ViewState kind="error" title={t('error.UNKNOWN.title')} detail={t('error.UNKNOWN.description')} onRetry={() => void resource.reload()}/>; if (resource.phase === 'unavailable') return <ViewState kind="unavailable" title={t('error.UNAUTHORIZED.title')} detail={t('error.UNAUTHORIZED.description')}/>; return null; }
function ProductionCard({ card }: { card: ProductionCardViewModel }) { const { formatDate, t } = useUi(); return <Link className="ui-card-link" to={`/productions/${encodeURIComponent(card.productionId)}/operations`}><article className="ui-panel"><header><div><span className="ui-kicker">{card.phase ?? 'PROJECT'}</span><h2>{card.displayName}</h2></div><StatusBadge value={card.state}/></header><div className="ui-panel-body"><p>{card.currentAction ?? t('unavailable')}</p><div className="ui-grid two" style={{ marginTop: '1rem' }}><div className="ui-metric"><strong>{card.progress === null ? '—' : `${card.progress}%`}</strong><span>{t('progress')}</span></div><div className="ui-metric"><strong>{card.gateCount ?? '—'}</strong><span>{t('gateCount')}</span></div></div><p className="ui-kicker" style={{ marginTop: '1rem' }}>{formatDate(card.lastUpdated)}</p></div></article></Link>; }
function Home() { const { t } = useUi(); const projects = useResource(() => adapters.portfolio.listProductions(), []); const gates = useResource(() => adapters.gates.listGates(), []); const body = ResourceState(projects); return <Shell><PageHead title={t('home')} detail={t('homeDetail')} actions={<Link className="ui-button" to="/new"><Icon name="plus"/>{t('newEntry')}</Link>}/>{body ?? <><section className="ui-grid two">{[[t('projects'), projects.value?.length ?? 0], [t('attention'), gates.value?.length ?? 0], [t('adapter'), adapters.mode]].map(([label, value]) => <div className="ui-metric" key={String(label)}><strong>{value}</strong><span>{label}</span></div>)}</section><section style={{ marginTop: '1.25rem' }}><div className="ui-page-head"><div><span className="ui-kicker">{t('portfolio')}</span><h1 style={{ fontSize: '1.25rem' }}>{t('productions')}</h1></div><Link className="ui-button secondary" to="/productions">{t('open')}<Icon name="arrow"/></Link></div>{projects.value?.length ? <div className="ui-grid cards">{projects.value.map((card) => <ProductionCard key={card.productionId} card={card}/>)}</div> : <ViewState kind="empty"/>}</section></>}</Shell>; }
function Productions() { const { t } = useUi(); const projects = useResource(() => adapters.portfolio.listProductions(), []); return <Shell><PageHead title={t('productions')} detail={t('projectsDetail')}/>{ResourceState(projects) ?? (projects.value?.length ? <div className="ui-grid cards">{projects.value.map((card) => <ProductionCard key={card.productionId} card={card}/>)}</div> : <ViewState kind="empty"/>)}</Shell>; }
function Drafts() { const { t, formatDate } = useUi(); const drafts = useResource(() => adapters.draft.listDrafts(), []); return <Shell><PageHead title={t('drafts')} detail={t('draftsDetail')} actions={<Link className="ui-button" to="/new"><Icon name="plus"/>{t('newEntry')}</Link>}/>{ResourceState(drafts) ?? (drafts.value?.length ? <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t('draft')}</th><th>{t('state')}</th><th>{t('revision')}</th><th>{t('updated')}</th><th/></tr></thead><tbody>{drafts.value.map((draft: DraftListViewModel) => <tr key={draft.draftId}><td><strong>{draft.title}</strong><br/><span className="ui-kicker">{draft.draftId}</span></td><td><StatusBadge value={draft.state}/></td><td>{draft.latestRevision}</td><td>{formatDate(draft.updatedAt)}</td><td><Link className="ui-button secondary" to={`/drafts/${encodeURIComponent(draft.draftId)}`}>{t('open')}</Link></td></tr>)}</tbody></table></div> : <ViewState kind="empty"/>)}</Shell>; }
function NewEntry() { const { t } = useUi(); const navigate = useNavigate(); const [title, setTitle] = useState(''); const [idea, setIdea] = useState(''); const [message, setMessage] = useState<string | null>(null); const [busy, setBusy] = useState(false); const submit = async () => { if (!title.trim() || !idea.trim()) { setMessage(t('titleIdeaRequired')); return; } setBusy(true); const result = await adapters.draft.createDraft(title.trim(), idea.trim(), metadata(0)); setBusy(false); if (result.kind === 'data') navigate(`/drafts/${encodeURIComponent(result.value.draftId)}`); else setMessage(result.message); }; return <Shell><PageHead title={t('newEntry')} detail={t('newDetail')}/><section className="ui-panel"><div className="ui-panel-body"><label className="ui-kicker">{t('title')}<input value={title} onChange={(event) => setTitle(event.target.value)} style={{ width: '100%', marginTop: '.5rem', minHeight: 40 }}/></label><label className="ui-kicker" style={{ display: 'block', marginTop: '1rem' }}>{t('idea')}<textarea value={idea} onChange={(event) => setIdea(event.target.value)} rows={7} style={{ width: '100%', marginTop: '.5rem' }}/></label>{message && <ViewState kind="error" detail={message}/>}<button className="ui-button" disabled={busy} onClick={() => void submit()} style={{ marginTop: '1rem' }}>{busy ? t('loading') : t('newEntry')}</button></div></section></Shell>; }
function DetailPanel({ title, children }: { title: string; children: ReactNode }) { return <section className="ui-panel"><header><h2>{title}</h2></header><div className="ui-panel-body">{children}</div></section>; }
function DataRows({ headings, rows }: { headings: string[]; rows: string[][] }) { return <div className="ui-table-wrap"><table className="ui-table"><thead><tr>{headings.map((heading) => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.join(':')}-${index}`}>{row.map((value, column) => <td key={`${index}-${column}`}>{value}</td>)}</tr>)}</tbody></table></div>; }
function DraftWorkspace() { const { id = '' } = useParams(); const { t } = useUi(); const draft = useResource(() => adapters.draft.getDraft(id), [id]); const understanding = useResource(() => adapters.draft.getUnderstanding(id), [id]); const proposal = useResource(() => adapters.draft.getProposal(id), [id]); const plan = useResource(() => adapters.draft.getMasterPlan(id), [id]); const overview = ResourceState(draft); return <Shell><PageHead title={t('draftWorkspaceTitle')} detail={t('draftWorkspaceDetail')}/>{overview ?? (draft.value && <div className="ui-grid"><DetailPanel title={t('entryDraft')}><span className="ui-kicker">{draft.value.draftId}</span><h2>{draft.value.title}</h2><p>{draft.value.idea}</p><StatusBadge value={draft.value.state}/></DetailPanel><div className="ui-grid two"><DetailPanel title={t('understanding')}>{understanding.phase === 'data' && understanding.value ? <><StatusBadge value={understanding.value.state}/><p>{understanding.value.current.interpretedIntent}</p><p className="ui-kicker">{t('clarifications')} {understanding.value.clarifications.length} · {t('assumptions')} {understanding.value.assumptions.length}</p></> : <ViewState kind={understanding.phase === 'error' ? 'error' : 'unavailable'} detail={understanding.message}/>}</DetailPanel><DetailPanel title={t('proposal')}>{proposal.phase === 'data' && proposal.value ? <><StatusBadge value={proposal.value.preApprovalOnly ? 'REVIEW_REQUIRED' : 'CURRENT'}/><p>{proposal.value.current.content.productStatement}</p><p className="ui-kicker">{t('requirements')} {proposal.value.current.content.requirements.length}</p></> : <ViewState kind={proposal.phase === 'error' ? 'error' : 'unavailable'} detail={proposal.message}/>}</DetailPanel></div><DetailPanel title={t('masterPlan')}>{plan.phase === 'data' && plan.value ? <><p>{plan.value.current.content.goal}</p><div className="ui-dag">{plan.value.current.content.nodes.map((node) => <div className="ui-dag-node" key={node.nodeKey}><strong>{node.title}</strong><span className="ui-kicker">{node.phase} · {node.requirementRefs.join(', ')}</span></div>)}</div></> : <ViewState kind={plan.phase === 'error' ? 'error' : 'unavailable'} detail={plan.message}/>}</DetailPanel><E13ProposalPlanEditor draftId={id} /></div>)}</Shell>; }
function Gates() {
  const { t, formatDate } = useUi(); const gates = useResource(() => adapters.gates.listGates(), []); const [filter, setFilter] = useState('');
  const items = (gates.value ?? []).filter((gate) => `${gate.gateId} ${gate.productionName ?? ''}`.toLowerCase().includes(filter.trim().toLowerCase()));
  return <Shell><PageHead title={t('gates')} detail={t('gatesDetail')}/><label className="ui-field"><span>Project / Gate filter</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="project or gate id"/></label>{ResourceState(gates) ?? (items.length ? <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t('gate')}</th><th>{t('risk')}</th><th>{t('reason')}</th><th>{t('expiry')}</th></tr></thead><tbody>{items.map((gate: GateViewModel) => <tr key={gate.gateId}><td><Link to={`/gates/${encodeURIComponent(gate.gateId)}`}><strong>{gate.action}</strong><br/><span className="ui-kicker">{gate.productionName ?? gate.gateId}</span></Link></td><td><StatusBadge value={gate.risk}/></td><td>{gate.reason}</td><td>{formatDate(gate.expiresAt)}</td></tr>)}</tbody></table></div> : <ViewState kind="empty"/>)}</Shell>;
}
function GateDetail() {
  const { id = '' } = useParams(); const { formatDate } = useUi(); const [refresh, setRefresh] = useState(0); const gate = useResource(() => adapters.gates.getGate(id), [id, refresh]); const [reason, setReason] = useState(''); const [busy, setBusy] = useState(false); const [receipt, setReceipt] = useState<import('./models').GateDecisionReceiptViewModel | null>(null); const [message, setMessage] = useState(''); const [audit, setAudit] = useState(false);
  const decide = async (decision: 'APPROVE' | 'REJECT') => { if (!gate.value || gate.value.status !== 'REQUESTED' || !reason.trim()) { setMessage('Decision reason is required or Gate is no longer pending.'); return; } setBusy(true); setMessage(''); const result = await adapters.gates.submitDecision(gate.value.gateId, decision, { reason: reason.trim(), expectedGateVersion: gate.value.version }); setBusy(false); if (result.kind === 'data') { setReceipt(result.value); setRefresh((value) => value + 1); } else { setMessage(result.message); } };
  return <Shell><PageHead title="Gate Detail" detail="Creator-scoped, source-derived review. Approve or reject delegates only to the existing Human Gate authority."/><Link className="ui-button secondary" to="/gates">← Gate Inbox</Link>{ResourceState(gate) ?? (gate.value && <div className="ui-grid two" style={{ marginTop: '1rem' }}><DetailPanel title="Gate request"><p className="ui-kicker">{gate.value.gateId} · V{gate.value.version} · {gate.value.status}</p><h2>{gate.value.productionName ?? gate.value.projectId}</h2><p>{gate.value.action}</p><p>{gate.value.reason}</p><p className="ui-kicker">risk {gate.value.riskRef ?? 'NOT AVAILABLE'} · evidence {gate.value.evidenceCount ?? 0} · expires {formatDate(gate.value.expiresAt)}</p><p className="ui-kicker">{gate.value.evidenceRefs.length ? gate.value.evidenceRefs.join(', ') : 'No supporting evidence references.'}</p></DetailPanel><DetailPanel title="Human decision"><p className="ui-kicker">Existing Human Gate authority · expected gate version {gate.value.version}</p>{gate.value.status === 'REQUESTED' && <><label className="ui-field"><span>Decision reason</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} maxLength={500} disabled={busy || Boolean(receipt)}/></label><div className="ui-actions"><button className="ui-button" type="button" disabled={busy || Boolean(receipt)} onClick={() => void decide('APPROVE')}>Approve</button><button className="ui-button secondary" type="button" disabled={busy || Boolean(receipt)} onClick={() => void decide('REJECT')}>Reject</button></div></>}{receipt && <div className="ui-panel-body" data-testid="e12-gate-receipt"><StatusBadge value={receipt.receiptStatus}/><p className="ui-kicker">{receipt.resultCode} · gate V{receipt.requestVersion ?? '—'} · decision {receipt.gateDecisionId}</p><p className="ui-kicker">{receipt.completionClaim}</p></div>}{message && <ViewState kind="error" detail={message}/>}</DetailPanel><DetailPanel title="Explain / Audit"><button className="ui-button secondary" type="button" onClick={() => setAudit((value) => !value)}>{audit ? 'Hide audit' : 'View audit'}</button>{audit && <DataRows headings={['Decision', 'Kind', 'Status', 'Issued']} rows={gate.value.audit.map((row) => [row.decisionId, row.decision, row.status, formatDate(row.issuedAt)])}/>}</DetailPanel></div>)}</Shell>;
}
type E11CommandAction = 'pause' | 'resume';
type E11CommandPhase = 'idle' | 'submitting' | 'receipt_accepted' | 'reconciling' | 'applied' | 'rejected' | 'uncertain' | 'terminal_failure';
type E11CommandState = {
  kind: E11CommandPhase;
  action: E11CommandAction | 'project.command' | null;
  receipt?: import('./models').ProjectCommandReceiptViewModel;
  attempts?: number;
  code?: string;
  idempotencyHint?: string;
};
const commandBusy = (state: E11CommandState) => ['submitting', 'receipt_accepted', 'reconciling'].includes(state.kind);
const redactedCorrelation = (value: string | undefined) => value ? `…${value.slice(-6)}` : 'NOT_AVAILABLE';

function Operations() {
  const { id = '' } = useParams();
  const { t, formatDate } = useUi();
  const [searchParams, setSearchParams] = useSearchParams();
  const snapshot = useResource(() => adapters.production.getLiveSnapshot(id), [id]);
  const [sourceSnapshot, setSourceSnapshot] = useState<LiveProductionSnapshotViewModel | null>(null);
  const [reason, setReason] = useState('');
  const [commandState, setCommandState] = useState<E11CommandState>({ kind: 'idle', action: null });
  const reconciliationAbort = useRef<AbortController | null>(null);
  const reconciliationEpoch = useRef(0);
  const restoredCommand = useRef<string | null>(null);
  const live = sourceSnapshot ?? snapshot.value;

  useEffect(() => {
    if (snapshot.value) setSourceSnapshot(snapshot.value);
  }, [snapshot.value]);
  useEffect(() => () => {
    reconciliationEpoch.current += 1;
    reconciliationAbort.current?.abort();
  }, []);

  const runReconciliation = useCallback(async (context: E11ReconciliationContext, action: E11CommandAction | 'project.command', idempotencyHint?: string) => {
    reconciliationAbort.current?.abort();
    const controller = new AbortController();
    reconciliationAbort.current = controller;
    const epoch = ++reconciliationEpoch.current;
    setCommandState({ kind: 'reconciling', action, receipt: context.receipt, attempts: 0, idempotencyHint });
    const outcome = await reconcileE11Receipt(adapters.production, context, controller.signal);
    if (controller.signal.aborted || epoch !== reconciliationEpoch.current) return;
    if (outcome.lastSnapshot) setSourceSnapshot(outcome.lastSnapshot);
    if (outcome.kind === 'applied') {
      setSourceSnapshot(outcome.snapshot);
      setCommandState({ kind: 'applied', action, receipt: context.receipt, attempts: outcome.attempts, idempotencyHint });
    } else if (outcome.kind === 'uncertain') {
      setCommandState({ kind: 'uncertain', action, receipt: context.receipt, attempts: outcome.attempts, code: outcome.code, idempotencyHint });
    } else if (outcome.kind === 'terminal_failure') {
      setCommandState({ kind: 'terminal_failure', action, receipt: context.receipt, attempts: outcome.attempts, code: outcome.code, idempotencyHint });
    }
  }, []);

  const reconcileReceipt = useCallback((receipt: import('./models').ProjectCommandReceiptViewModel, action: E11CommandAction | 'project.command', idempotencyHint?: string) => {
    const context: E11ReconciliationContext = { projectId: id, receipt, initialSnapshotWatermark: live?.snapshotWatermark ?? 0 };
    setCommandState({ kind: 'receipt_accepted', action, receipt, attempts: 0, idempotencyHint });
    void runReconciliation(context, action, idempotencyHint);
  }, [id, live?.snapshotWatermark, runReconciliation]);

  useEffect(() => {
    const commandId = searchParams.get('e11_command');
    if (!commandId || !id || restoredCommand.current === commandId) return;
    restoredCommand.current = commandId;
    const controller = new AbortController();
    reconciliationAbort.current?.abort();
    reconciliationAbort.current = controller;
    const epoch = ++reconciliationEpoch.current;
    setCommandState({ kind: 'receipt_accepted', action: 'project.command', attempts: 0, code: 'E11_RECEIPT_RECOVERY_READ' });
    void adapters.production.getCommandReceipt(id, commandId, controller.signal).then((result) => {
      if (controller.signal.aborted || epoch !== reconciliationEpoch.current) return;
      if (result.kind !== 'data') {
        setCommandState({ kind: 'uncertain', action: 'project.command', attempts: 0, code: result.kind === 'not_implemented' ? 'E11_RECEIPT_NOT_AVAILABLE' : 'E11_RECEIPT_READ_FAILED' });
        return;
      }
      if (result.value.receiptStatus === 'REJECTED') {
        setCommandState({ kind: 'rejected', action: result.value.action === 'pause' || result.value.action === 'resume' ? result.value.action : 'project.command', receipt: result.value, attempts: 0, code: result.value.resultCode });
        return;
      }
      reconcileReceipt(result.value, result.value.action === 'pause' || result.value.action === 'resume' ? result.value.action : 'project.command');
    }).catch(() => {
      if (!controller.signal.aborted && epoch === reconciliationEpoch.current) setCommandState({ kind: 'uncertain', action: 'project.command', attempts: 0, code: 'E11_RECEIPT_READ_FAILED' });
    });
  }, [id, reconcileReceipt, searchParams]);

  const submit = async (action: E11CommandAction) => {
    if (!live || !reason.trim() || commandBusy(commandState)) { if (!reason.trim()) setCommandState({ kind: 'terminal_failure', action, code: 'E11_COMMAND_REASON_REQUIRED' }); return; }
    reconciliationAbort.current?.abort();
    const idempotencyKey = `e11-${Date.now()}-${action}`;
    setCommandState({ kind: 'submitting', action, idempotencyHint: idempotencyKey });
    const metadata: CommandMetadata = { reason: reason.trim(), idempotencyKey, expectedVersion: live.project.version };
    const result = action === 'pause' ? await adapters.production.pause(live.project.projectId, metadata) : await adapters.production.resume(live.project.projectId, metadata);
    if (result.kind !== 'data') {
      setCommandState({ kind: 'terminal_failure', action, code: result.kind === 'not_implemented' ? 'E11_COMMAND_NOT_AVAILABLE' : result.message, idempotencyHint: idempotencyKey });
      return;
    }
    restoredCommand.current = result.value.commandId;
    setSearchParams({ e11_command: result.value.commandId, e11_action: action }, { replace: true });
    if (result.value.receiptStatus === 'REJECTED') {
      setCommandState({ kind: 'rejected', action, receipt: result.value, attempts: 0, code: result.value.resultCode, idempotencyHint: idempotencyKey });
      return;
    }
    reconcileReceipt(result.value, action, idempotencyKey);
  };

  const retryRead = () => {
    if (!commandState.receipt || commandBusy(commandState)) return;
    reconcileReceipt(commandState.receipt, commandState.action ?? 'project.command', commandState.idempotencyHint);
  };
  const body = ResourceState(snapshot);
  const phase = commandState.kind.toUpperCase();
  const isPendingProjection = ['receipt_accepted', 'reconciling', 'uncertain'].includes(commandState.kind);
  return <Shell><PageHead title={t('productionWorkspace')} detail={t('operationsDetail')} actions={<Link className="ui-button secondary" to={`/productions/${encodeURIComponent(id)}`}>{t('open')}</Link>}/>{body ?? (live && <><section className="ui-grid two"><div className="ui-metric"><strong>{live.project.title}</strong><span>{live.project.projectId}</span></div><div className="ui-metric"><strong><StatusBadge value={live.project.state}/></strong><span>{t('watermark')} {live.snapshotWatermark} · {formatDate(live.project.updatedAt)}</span></div></section><div className="ui-split" style={{ marginTop: '1rem' }}><DetailPanel title={t('recovery')}><p className="ui-kicker">E11 trusted Control Plane transport · receipt-first · creator-scoped E7 reconciliation</p><label className="ui-field"><span>{t('reason')}</span><input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} disabled={commandBusy(commandState)} /></label><div className="ui-actions"><button className="ui-button secondary" type="button" disabled={commandBusy(commandState)} onClick={() => submit('pause')}>project.pause</button><button className="ui-button secondary" type="button" disabled={commandBusy(commandState)} onClick={() => submit('resume')}>project.resume</button></div>{commandState.kind !== 'idle' && <div className="ui-panel-body" data-testid="e11-command-reconciliation" data-phase={commandState.kind}><StatusBadge value={phase}/><p className="ui-kicker">{commandState.action ?? 'project.command'} · {commandState.receipt?.commandId ?? 'RECEIPT_PENDING'} · {commandState.receipt?.projectionStatus ?? 'AWAITING_E7_RECONCILIATION'}</p><p className="ui-kicker">target V{commandState.receipt?.targetVersion ?? '—'} · snapshot V{live.project.version} · watermark {live.snapshotWatermark} · {live.freshness} · {live.asOf ?? 'NOT_AVAILABLE'} · attempt {commandState.attempts ?? 0}/4 · correlation {redactedCorrelation(commandState.idempotencyHint)}</p>{isPendingProjection && <p className="ui-kicker">AWAITING E7 RECONCILIATION — source-derived snapshot remains pending.</p>}{commandState.code && <p className="ui-kicker">{commandState.code}</p>}{commandState.kind === 'uncertain' && <button className="ui-button secondary" type="button" onClick={retryRead}>retry read</button>}</div>}<p className="ui-kicker">{t('waiting')} {live.waiting.length} · {t('findings')} {live.recovery.length} · {t('gates')} {live.gates.length}</p><DataRows headings={[t('waitingRecord'), t('task'), t('state')]} rows={live.waiting.map((row) => [row.waitingRecordId, row.taskId, row.state])}/><DataRows headings={[t('finding'), t('kind'), t('status')]} rows={live.recovery.map((row) => [row.findingId, row.kind, row.status])}/><Link className="ui-button secondary" to={`/gates?project=${encodeURIComponent(live.project.projectId)}&entry=recovery`}>{t('controlledRecovery')}<Icon name="arrow"/></Link></DetailPanel><DetailPanel title={t('workflow')}><div className="ui-dag">{live.workflow.nodes.map((node) => <div className="ui-dag-node" key={node.nodeId}><strong>{node.title}</strong><StatusBadge value={node.state}/><span className="ui-kicker">{node.nodeId} · V{node.version}</span></div>)}{live.workflow.edges.map((edge) => <span className="ui-dag-edge" key={edge.edgeId}>↳ {edge.dependsOnTaskId} → {edge.taskId}</span>)}</div></DetailPanel></div><div className="ui-grid two" style={{ marginTop: '1rem' }}><DetailPanel title={t('execution')}><DataRows headings={[t('request'), t('task'), t('state')]} rows={live.executionRequests.map((row) => [row.executionRequestId, row.taskId, row.state])}/></DetailPanel><DetailPanel title={t('verification')}><DataRows headings={[t('plan'), t('task'), t('status')]} rows={live.verification.plans.map((row) => [row.planId, row.taskId, row.status])}/></DetailPanel><DetailPanel title={t('evidence')}><p className="ui-kicker">{t('validCount')} {live.evidence.validCount} · {t('invalidatedCount')} {live.evidence.invalidatedCount} · {t('missingCount')} {live.evidence.missingCount}</p><DataRows headings={[t('evidence'), t('media'), t('valid')]} rows={live.evidence.items.map((row) => [row.evidenceId, row.mediaType, String(row.valid)])}/></DetailPanel><DetailPanel title={t('authoritativeEventLog')}><div className="ui-log">{live.recentEvents.map((event) => <div key={event.eventId}>#{event.productionSequence} {event.eventKind} · {event.aggregateType}/{event.aggregateId}</div>)}</div></DetailPanel></div></>)}</Shell>;
}

function ProductionRedirect() { const { id = '' } = useParams(); return <Navigate replace to={`/productions/${encodeURIComponent(id)}/operations`}/>; }
export default function App() { return <UiProvider><Routes><Route path="/" element={<Navigate replace to="/home"/>}/><Route path="/home" element={<Home/>}/><Route path="/new" element={<NewEntry/>}/><Route path="/drafts" element={<Drafts/>}/><Route path="/drafts/:id" element={<DraftWorkspace/>}/><Route path="/productions" element={<Productions/>}/><Route path="/productions/:id" element={<ProductionRedirect/>}/><Route path="/productions/:id/operations" element={<Operations/>}/><Route path="/gates" element={<Gates/>}/><Route path="/gates/:id" element={<GateDetail/>}/><Route path="/workers" element={<WorkerFleet/>}/><Route path="/workers/:id" element={<WorkerDetail/>}/><Route path="/execution-queue" element={<ExecutionQueue/>}/><Route path="*" element={<Navigate replace to="/home"/>}/></Routes></UiProvider>; }
