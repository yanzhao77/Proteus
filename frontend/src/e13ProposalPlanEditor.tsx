import { useCallback, useEffect, useState } from 'react';
import type {
  AdapterResult,
  CommandMetadata,
  MasterPlanContentEditViewModel,
  MasterPlanContentViewModel,
  MasterPlanRevisionViewModel,
  MasterPlanViewModel,
  ProposalContentEditViewModel,
  ProposalContentViewModel,
  ProposalRevisionViewModel,
  ProposalViewModel,
} from './models';
import { createAdapters } from './api';
import { useUi } from './ui-context';
import { StatusBadge, ViewState } from './design-system';

const adapters = createAdapters();

const COMPLEXITY_BANDS = ['LOW', 'MEDIUM', 'HIGH', 'REVIEW_REQUIRED'] as const;
const ARCH_STATUSES = ['NOT_AVAILABLE', 'SIMPLE', 'REFERENCE', 'OVERRIDDEN', 'REVIEW_REQUIRED'] as const;
const VERIFICATION_STATUSES = ['NOT_AVAILABLE', 'DRAFT', 'SPECIFIED', 'REVIEW_REQUIRED'] as const;

function editorMetadata(expectedVersion: number, t: (key: string) => string): CommandMetadata {
  return { expectedVersion, reason: t('e13.editor.saveReason'), idempotencyKey: `e13-${crypto.randomUUID()}` };
}

type Loaded = {
  proposal: ProposalViewModel;
  proposalRevisions: ProposalRevisionViewModel[];
  plan: MasterPlanViewModel;
  planRevisions: MasterPlanRevisionViewModel[];
};

type Resource<T> = { phase: 'loading' | 'data' | 'error' | 'unavailable'; value?: T; message?: string };
function useResource<T>(loader: () => Promise<AdapterResult<T>>, deps: readonly unknown[] = []) {
  const [state, setState] = useState<Resource<T>>({ phase: 'loading' });
  const load = useCallback(() => {
    setState({ phase: 'loading' });
    return loader()
      .then((result) => setState(result.kind === 'data' ? { phase: 'data', value: result.value } : { phase: result.kind === 'not_implemented' ? 'unavailable' : 'error', message: result.message }))
      .catch(() => setState({ phase: 'error', message: 'Network request failed.' }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { void load(); }, [load]);
  return { ...state, reload: load };
}

function toProposalEdit(content: ProposalContentViewModel): ProposalContentEditViewModel {
  return {
    productStatement: content.productStatement,
    targetOutcome: content.targetOutcome,
    scopeIn: [...content.scopeIn],
    scopeOut: [...content.scopeOut],
    requirements: content.requirements.map((r) => ({ ...r })),
    assumptions: content.assumptions.map((a) => ({ ...a })),
    unresolvedItems: [...content.unresolvedItems],
    complexityBand: content.complexityBand,
    candidateArchitecture: { status: content.candidateArchitecture.status, reason: content.candidateArchitecture.reason ?? '' },
  };
}

function toMasterPlanEdit(content: MasterPlanContentViewModel): MasterPlanContentEditViewModel {
  return {
    goal: content.goal,
    requirements: content.requirements.map((r) => ({ ...r })),
    constraints: [...content.constraints],
    phases: [...content.phases],
    nodes: content.nodes.map((n) => ({ ...n, requirementRefs: [...n.requirementRefs], verificationRefs: [...n.verificationRefs] })),
    dependencies: content.dependencies.map((d) => ({ ...d })),
    risks: [...content.risks],
    verificationIntent: content.verificationIntent
      ? { status: content.verificationIntent.status, requirementKeys: [...content.verificationIntent.requirementKeys] }
      : { status: 'REVIEW_REQUIRED', requirementKeys: [] },
  };
}

function validateProposal(form: ProposalContentEditViewModel, t: (key: string, values?: Record<string, string>) => string): string[] {
  const errors: string[] = [];
  if (!form.productStatement.trim()) errors.push(t('e13.validate.productStatementRequired'));
  if (!form.targetOutcome.trim()) errors.push(t('e13.validate.targetOutcomeRequired'));
  if (!COMPLEXITY_BANDS.includes(form.complexityBand as (typeof COMPLEXITY_BANDS)[number])) errors.push(t('e13.validate.complexityBandInvalid'));
  if (!form.candidateArchitecture.status.trim()) errors.push(t('e13.validate.architectureStatusRequired'));
  if (!Array.isArray(form.requirements) || form.requirements.length === 0) errors.push(t('e13.validate.requirementRequired'));
  else {
    const keys = new Set<string>();
    for (const r of form.requirements) {
      if (!r.key.trim()) errors.push(t('e13.validate.requirementKeyRequired'));
      if (!r.statement.trim()) errors.push(t('e13.validate.requirementStatementNeeded', { key: r.key || '(blank)' }));
      if (r.key.trim()) { if (keys.has(r.key)) errors.push(t('e13.validate.requirementDuplicateKey', { key: r.key })); keys.add(r.key); }
      if (!r.source.trim()) errors.push(t('e13.validate.requirementSourceNeeded', { key: r.key || '(blank)' }));
    }
  }
  if (!Array.isArray(form.assumptions)) errors.push(t('e13.validate.assumptionsMustBeList'));
  else for (const a of form.assumptions) {
    if (!a.assumptionId.trim()) errors.push(t('e13.validate.assumptionIdRequired'));
    if (!a.statement.trim()) errors.push(t('e13.validate.assumptionStatementRequired'));
    if (!a.status.trim()) errors.push(t('e13.validate.assumptionStatusRequired'));
  }
  if (!form.scopeIn.every((s) => s.trim())) errors.push(t('e13.validate.scopeInNonEmpty'));
  if (!form.scopeOut.every((s) => s.trim())) errors.push(t('e13.validate.scopeOutNonEmpty'));
  if (!form.unresolvedItems.every((s) => s.trim())) errors.push(t('e13.validate.unresolvedNonEmpty'));
  return errors;
}

function validatePlan(form: MasterPlanContentEditViewModel, t: (key: string, values?: Record<string, string>) => string): string[] {
  const errors: string[] = [];
  if (!form.goal.trim()) errors.push(t('e13.validate.goalRequired'));
  if (!Array.isArray(form.requirements) || form.requirements.length === 0) errors.push(t('e13.validate.requirementRequired'));
  else {
    const keys = new Set<string>();
    for (const r of form.requirements) {
      if (!r.key.trim()) errors.push(t('e13.validate.requirementKeyRequired'));
      if (!r.statement.trim()) errors.push(t('e13.validate.requirementStatementNeeded', { key: r.key || '(blank)' }));
      if (r.key.trim()) { if (keys.has(r.key)) errors.push(t('e13.validate.requirementDuplicateKey', { key: r.key })); keys.add(r.key); }
      if (!r.source.trim()) errors.push(t('e13.validate.requirementSourceNeeded', { key: r.key || '(blank)' }));
    }
  }
  if (!Array.isArray(form.nodes) || form.nodes.length === 0) errors.push(t('e13.validate.planNodeRequired'));
  else {
    const keys = new Set<string>();
    for (const n of form.nodes) {
      if (!n.nodeKey.trim()) errors.push(t('e13.validate.nodeKeyRequired'));
      if (!n.phase.trim()) errors.push(t('e13.validate.nodePhaseRequired'));
      if (!n.title.trim()) errors.push(t('e13.validate.nodeTitleRequired'));
      if (n.nodeKey.trim()) { if (keys.has(n.nodeKey)) errors.push(t('e13.validate.nodeDuplicateKey', { key: n.nodeKey })); keys.add(n.nodeKey); }
    }
  }
  if (!VERIFICATION_STATUSES.includes(form.verificationIntent.status as (typeof VERIFICATION_STATUSES)[number])) errors.push(t('e13.validate.verificationStatusInvalid'));
  if (!form.constraints.every((s) => s.trim())) errors.push(t('e13.validate.constraintsNonEmpty'));
  if (!form.phases.every((s) => s.trim())) errors.push(t('e13.validate.phasesNonEmpty'));
  if (!form.risks.every((s) => s.trim())) errors.push(t('e13.validate.risksNonEmpty'));
  errors.push(...validatePlanDependencies(form, t));
  return errors;
}

function validatePlanDependencies(form: MasterPlanContentEditViewModel, t: (key: string) => string): string[] {
  const errors: string[] = [];
  const nodeKeys = new Set(form.nodes.filter((n) => n.nodeKey.trim()).map((n) => n.nodeKey));
  const edgeSet = new Set<string>();
  for (const dep of form.dependencies) {
    if (!dep.source.trim() || !dep.target.trim()) continue;
    if (dep.source === dep.target) { errors.push(t('e13.validate.dependencySelfLoop')); continue; }
    if (!nodeKeys.has(dep.source)) { errors.push(t('e13.validate.dependencyMissingNode')); continue; }
    if (!nodeKeys.has(dep.target)) { errors.push(t('e13.validate.dependencyMissingNode')); continue; }
    const edgeKey = `${dep.source}->${dep.target}`;
    if (edgeSet.has(edgeKey)) { errors.push(t('e13.validate.dependencyDuplicate')); continue; }
    edgeSet.add(edgeKey);
  }
  if (errors.length === 0 && form.dependencies.length > 0) {
    const adj = new Map<string, string[]>();
    for (const n of form.nodes.filter((n) => n.nodeKey.trim())) adj.set(n.nodeKey, []);
    for (const dep of form.dependencies) {
      if (dep.source.trim() && dep.target.trim() && nodeKeys.has(dep.source) && nodeKeys.has(dep.target)) {
        adj.get(dep.source)!.push(dep.target);
      }
    }
    const WHITE = 0, GRAY = 1, BLACK = 2;
    const color = new Map<string, number>();
    for (const k of nodeKeys) color.set(k, WHITE);
    let hasCycle = false;
    const dfs = (u: string) => {
      if (hasCycle) return;
      color.set(u, GRAY);
      for (const v of adj.get(u) ?? []) {
        if (color.get(v) === GRAY) { hasCycle = true; return; }
        if (color.get(v) === WHITE) dfs(v);
      }
      color.set(u, BLACK);
    };
    for (const k of nodeKeys) { if (color.get(k) === WHITE) dfs(k); if (hasCycle) break; }
    if (hasCycle) errors.push(t('e13.validate.dependencyCycle'));
  }
  return errors;
}

function StringListField({ label, items, onChange, placeholder, t }: { label: string; items: string[]; onChange: (next: string[]) => void; placeholder?: string; t: (key: string) => string }) {
  return (
    <fieldset className="ui-fieldset">
      <legend className="ui-kicker">{label}</legend>
      {items.map((item, index) => (
        <div key={index} style={{ display: 'flex', gap: '.5rem', marginBottom: '.5rem' }}>
          <input
            value={item}
            placeholder={placeholder}
            onChange={(e) => { const next = [...items]; next[index] = e.target.value; onChange(next); }}
            style={{ flex: 1, minHeight: 36 }}
          />
          <button type="button" className="ui-button secondary" onClick={() => onChange(items.filter((_, i) => i !== index))}>{t('e13.remove')}</button>
        </div>
      ))}
      <button type="button" className="ui-button secondary" onClick={() => onChange([...items, ''])}>{t('e13.add')}</button>
    </fieldset>
  );
}

function RequirementListField({ label, items, onChange, t }: { label: string; items: { key: string; statement: string; source: string }[]; onChange: (next: { key: string; statement: string; source: string }[]) => void; t: (key: string) => string }) {
  const update = (index: number, patch: Partial<{ key: string; statement: string; source: string }>) => onChange(items.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  return (
    <fieldset className="ui-fieldset">
      <legend className="ui-kicker">{label}</legend>
      {items.map((item, index) => (
        <div key={index} style={{ border: '1px solid var(--border, #ccc)', borderRadius: 6, padding: '.5rem', marginBottom: '.5rem' }}>
          <div style={{ display: 'flex', gap: '.5rem' }}>
            <input aria-label={t('e13.requirementKey')} placeholder={t('e13.requirementKey')} value={item.key} onChange={(e) => update(index, { key: e.target.value })} style={{ width: '8rem', minHeight: 36 }} />
            <input aria-label={t('e13.requirementSource')} placeholder={t('e13.requirementSource')} value={item.source} onChange={(e) => update(index, { source: e.target.value })} style={{ width: '10rem', minHeight: 36 }} />
            <button type="button" className="ui-button secondary" onClick={() => onChange(items.filter((_, i) => i !== index))}>{t('e13.remove')}</button>
          </div>
          <textarea aria-label={t('e13.requirementStatement')} placeholder={t('e13.requirementStatement')} value={item.statement} onChange={(e) => update(index, { statement: e.target.value })} rows={2} style={{ width: '100%', marginTop: '.5rem' }} />
        </div>
      ))}
      <button type="button" className="ui-button secondary" onClick={() => onChange([...items, { key: '', statement: '', source: 'entry_understanding' }])}>{t('e13.addRequirement')}</button>
    </fieldset>
  );
}

function AssumptionListField({ label, items, onChange, t }: { label: string; items: { assumptionId: string; statement: string; basis: string; status: string }[]; onChange: (next: { assumptionId: string; statement: string; basis: string; status: string }[]) => void; t: (key: string) => string }) {
  const update = (index: number, patch: Partial<{ assumptionId: string; statement: string; basis: string; status: string }>) => onChange(items.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  return (
    <fieldset className="ui-fieldset">
      <legend className="ui-kicker">{label}</legend>
      {items.map((item, index) => (
        <div key={index} style={{ border: '1px solid var(--border, #ccc)', borderRadius: 6, padding: '.5rem', marginBottom: '.5rem' }}>
          <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap' }}>
            <input aria-label={t('e13.assumptionId')} placeholder={t('e13.assumptionId')} value={item.assumptionId} onChange={(e) => update(index, { assumptionId: e.target.value })} style={{ width: '8rem', minHeight: 36 }} />
            <input aria-label={t('e13.assumptionStatus')} placeholder={t('e13.assumptionStatus')} value={item.status} onChange={(e) => update(index, { status: e.target.value })} style={{ width: '10rem', minHeight: 36 }} />
            <button type="button" className="ui-button secondary" onClick={() => onChange(items.filter((_, i) => i !== index))}>{t('e13.remove')}</button>
          </div>
          <textarea aria-label={t('e13.assumptionStatement')} placeholder={t('e13.assumptionStatement')} value={item.statement} onChange={(e) => update(index, { statement: e.target.value })} rows={2} style={{ width: '100%', marginTop: '.5rem' }} />
          <input aria-label={t('e13.assumptionBasis')} placeholder={t('e13.assumptionBasis')} value={item.basis} onChange={(e) => update(index, { basis: e.target.value })} style={{ width: '100%', marginTop: '.5rem', minHeight: 36 }} />
        </div>
      ))}
      <button type="button" className="ui-button secondary" onClick={() => onChange([...items, { assumptionId: '', statement: '', basis: '', status: 'UNCONFIRMED_SOURCE_ASSUMPTION' }])}>{t('e13.addAssumption')}</button>
    </fieldset>
  );
}

function NodeListField({ label, items, onChange, t }: { label: string; items: { nodeKey: string; phase: string; title: string; requirementRefs: string[]; verificationRefs: string[] }[]; onChange: (next: { nodeKey: string; phase: string; title: string; requirementRefs: string[]; verificationRefs: string[] }[]) => void; t: (key: string) => string }) {
  const update = (index: number, patch: Partial<{ nodeKey: string; phase: string; title: string; requirementRefs: string[]; verificationRefs: string[] }>) => onChange(items.map((n, i) => (i === index ? { ...n, ...patch } : n)));
  return (
    <fieldset className="ui-fieldset">
      <legend className="ui-kicker">{label}</legend>
      {items.map((item, index) => (
        <div key={index} style={{ border: '1px solid var(--border, #ccc)', borderRadius: 6, padding: '.5rem', marginBottom: '.5rem' }}>
          <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap' }}>
            <input aria-label={t('e13.nodeKey')} placeholder={t('e13.nodeKey')} value={item.nodeKey} onChange={(e) => update(index, { nodeKey: e.target.value })} style={{ width: '8rem', minHeight: 36 }} />
            <input aria-label={t('e13.nodePhase')} placeholder={t('e13.nodePhase')} value={item.phase} onChange={(e) => update(index, { phase: e.target.value })} style={{ width: '8rem', minHeight: 36 }} />
            <button type="button" className="ui-button secondary" onClick={() => onChange(items.filter((_, i) => i !== index))}>{t('e13.remove')}</button>
          </div>
          <input aria-label={t('e13.nodeTitle')} placeholder={t('e13.nodeTitle')} value={item.title} onChange={(e) => update(index, { title: e.target.value })} style={{ width: '100%', marginTop: '.5rem', minHeight: 36 }} />
          <input aria-label={t('e13.requirementRefs')} placeholder={t('e13.requirementRefs')} value={item.requirementRefs.join(', ')} onChange={(e) => update(index, { requirementRefs: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} style={{ width: '100%', marginTop: '.5rem', minHeight: 36 }} />
          <input aria-label={t('e13.verificationRefs')} placeholder={t('e13.verificationRefs')} value={item.verificationRefs.join(', ')} onChange={(e) => update(index, { verificationRefs: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} style={{ width: '100%', marginTop: '.5rem', minHeight: 36 }} />
        </div>
      ))}
      <button type="button" className="ui-button secondary" onClick={() => onChange([...items, { nodeKey: '', phase: '', title: '', requirementRefs: [], verificationRefs: [] }])}>{t('e13.addNode')}</button>
    </fieldset>
  );
}

function DependencyListField({ label, items, onChange, t }: { label: string; items: { source: string; target: string }[]; onChange: (next: { source: string; target: string }[]) => void; t: (key: string) => string }) {
  const update = (index: number, patch: Partial<{ source: string; target: string }>) => onChange(items.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  return (
    <fieldset className="ui-fieldset">
      <legend className="ui-kicker">{label}</legend>
      {items.map((item, index) => (
        <div key={index} style={{ display: 'flex', gap: '.5rem', marginBottom: '.5rem' }}>
          <input aria-label={t('e13.sourceNode')} placeholder={t('e13.sourceNode')} value={item.source} onChange={(e) => update(index, { source: e.target.value })} style={{ flex: 1, minHeight: 36 }} />
          <input aria-label={t('e13.targetNode')} placeholder={t('e13.targetNode')} value={item.target} onChange={(e) => update(index, { target: e.target.value })} style={{ flex: 1, minHeight: 36 }} />
          <button type="button" className="ui-button secondary" onClick={() => onChange(items.filter((_, i) => i !== index))}>{t('e13.remove')}</button>
        </div>
      ))}
      <button type="button" className="ui-button secondary" onClick={() => onChange([...items, { source: '', target: '' }])}>{t('e13.addDependency')}</button>
    </fieldset>
  );
}

function RevisionDiff({ before, after, t }: { before: Record<string, unknown>; after: Record<string, unknown>; t: (key: string) => string }) {
  const keys = Object.keys({ ...before, ...after });
  const rows = keys.filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
  if (rows.length === 0) return <p className="ui-kicker">{t('e13.noDiff')}</p>;
  return (
    <div className="ui-table-wrap">
      <table className="ui-table">
        <thead><tr><th>{t('e13.diffField')}</th><th>{t('e13.diffCurrent')}</th><th>{t('e13.diffSelected')}</th></tr></thead>
        <tbody>
          {rows.map((k) => (
            <tr key={k}>
              <td><strong>{k}</strong></td>
              <td><pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{JSON.stringify(before[k], null, 1)}</pre></td>
              <td><pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{JSON.stringify(after[k], null, 1)}</pre></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProposalRevisionHistory({ revisions, current, t }: { revisions: ProposalRevisionViewModel[]; current: ProposalRevisionViewModel; t: (key: string) => string }) {
  const [selected, setSelected] = useState('');
  const selectedRev = revisions.find((r) => r.revisionId === selected);
  return (
    <section style={{ marginTop: '1rem' }}>
      <h3>{t('e13.revisionHistory')}</h3>
      <ul>
        {revisions.map((r) => (
          <li key={r.revisionId}>#{r.revisionNumber} · {r.compiler} · {r.createdAt}{r.revisionId === current.revisionId ? ` ${t('e13.current')}` : ''}</li>
        ))}
      </ul>
      <label className="ui-kicker">
        {t('e13.compareWithRevision')}
        <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ marginLeft: '.5rem', minHeight: 36 }}>
          <option value="">{t('e13.selectRevision')}</option>
          {revisions.filter((r) => r.revisionId !== current.revisionId).map((r) => <option key={r.revisionId} value={r.revisionId}>#{r.revisionNumber}</option>)}
        </select>
      </label>
      {selectedRev && <RevisionDiff before={current.content as unknown as Record<string, unknown>} after={selectedRev.content as unknown as Record<string, unknown>} t={t} />}
    </section>
  );
}

function MasterPlanRevisionHistory({ revisions, current, t }: { revisions: MasterPlanRevisionViewModel[]; current: MasterPlanRevisionViewModel; t: (key: string) => string }) {
  const [selected, setSelected] = useState('');
  const selectedRev = revisions.find((r) => r.revisionId === selected);
  return (
    <section style={{ marginTop: '1rem' }}>
      <h3>{t('e13.revisionHistory')}</h3>
      <ul>
        {revisions.map((r) => (
          <li key={r.revisionId}>#{r.revisionNumber} · {r.compiler} · {r.createdAt}{r.revisionId === current.revisionId ? ` ${t('e13.current')}` : ''}</li>
        ))}
      </ul>
      <label className="ui-kicker">
        {t('e13.compareWithRevision')}
        <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ marginLeft: '.5rem', minHeight: 36 }}>
          <option value="">{t('e13.selectRevision')}</option>
          {revisions.filter((r) => r.revisionId !== current.revisionId).map((r) => <option key={r.revisionId} value={r.revisionId}>#{r.revisionNumber}</option>)}
        </select>
      </label>
      {selectedRev && <RevisionDiff before={current.content as unknown as Record<string, unknown>} after={selectedRev.content as unknown as Record<string, unknown>} t={t} />}
    </section>
  );
}

export function E13ProposalPlanEditor({ draftId }: { draftId: string }) {
  const { t } = useUi();
  const load = useCallback(async (): Promise<AdapterResult<Loaded>> => {
    const [p, pr, m, mr] = await Promise.all([
      adapters.draft.getProposal(draftId),
      adapters.draft.listProposalRevisions(draftId),
      adapters.draft.getMasterPlan(draftId),
      adapters.draft.listMasterPlanRevisions(draftId),
    ]);
    if (p.kind !== 'data') return p;
    if (m.kind !== 'data') return m;
    return {
      kind: 'data',
      value: {
        proposal: p.value,
        proposalRevisions: pr.kind === 'data' ? pr.value : [],
        plan: m.value,
        planRevisions: mr.kind === 'data' ? mr.value : [],
      },
    };
  }, [draftId]);
  const resource = useResource(load, [load]);

  const [tab, setTab] = useState<'proposal' | 'master-plan'>('proposal');
  const [editingProposal, setEditingProposal] = useState(false);
  const [proposalForm, setProposalForm] = useState<ProposalContentEditViewModel | null>(null);
  const [editingPlan, setEditingPlan] = useState(false);
  const [planForm, setPlanForm] = useState<MasterPlanContentEditViewModel | null>(null);
  const [savingProposal, setSavingProposal] = useState(false);
  const [savingPlan, setSavingPlan] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const dirty = editingProposal || editingPlan;
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  if (resource.phase === 'loading') return <ViewState kind="loading" />;
  if (resource.phase === 'error') return <ViewState kind="error" detail={resource.message} onRetry={() => void resource.reload()} />;
  if (resource.phase === 'unavailable') return <ViewState kind="unavailable" detail={resource.message} />;
  const data = resource.value!;

  const startProposalEdit = () => { setProposalForm(toProposalEdit(data.proposal.current.content)); setEditingProposal(true); setSaveMessage(null); };
  const startPlanEdit = () => { setPlanForm(toMasterPlanEdit(data.plan.current.content)); setEditingPlan(true); setSaveMessage(null); };
  const discardProposal = () => { if (proposalForm && JSON.stringify(proposalForm) !== JSON.stringify(toProposalEdit(data.proposal.current.content)) && !window.confirm(t('e13.discardConfirmProposal'))) return; setEditingProposal(false); setProposalForm(null); };
  const discardPlan = () => { if (planForm && JSON.stringify(planForm) !== JSON.stringify(toMasterPlanEdit(data.plan.current.content)) && !window.confirm(t('e13.discardConfirmPlan'))) return; setEditingPlan(false); setPlanForm(null); };

  const saveProposal = async () => {
    if (!proposalForm) return;
    const errors = validateProposal(proposalForm, t);
    if (errors.length) { setSaveMessage(errors.join(' ')); return; }
    setSavingProposal(true);
    setSaveMessage(null);
    const result = await adapters.draft.saveProposalRevision(draftId, proposalForm, editorMetadata(data.proposal.latestRevision, t));
    setSavingProposal(false);
    if (result.kind === 'data') {
      setEditingProposal(false); setProposalForm(null);
      setSaveMessage(t('e13.savedProposal', { n: String(result.value.latestRevision) }));
      void resource.reload();
    } else setSaveMessage(result.message);
  };
  const savePlan = async () => {
    if (!planForm) return;
    const errors = validatePlan(planForm, t);
    if (errors.length) { setSaveMessage(errors.join(' ')); return; }
    setSavingPlan(true);
    setSaveMessage(null);
    const result = await adapters.draft.saveMasterPlanRevision(draftId, planForm, editorMetadata(data.plan.latestRevision, t));
    setSavingPlan(false);
    if (result.kind === 'data') {
      setEditingPlan(false); setPlanForm(null);
      setSaveMessage(t('e13.savedPlan', { n: String(result.value.latestRevision) }));
      void resource.reload();
    } else setSaveMessage(result.message);
  };

  const proposalErrors = proposalForm ? validateProposal(proposalForm, t) : [];
  const planErrors = planForm ? validatePlan(planForm, t) : [];

return (
    <section className="ui-panel" aria-label={t('e13.tab.aria')}>
      <header>
        <span className="ui-kicker">{t('e13.editor')}</span>
        <h2>{t('e13.title')}</h2>
        <p className="ui-kicker">{t('e13.subtitle')}</p>
      </header>
      <div className="ui-panel-body">
        <div role="tablist" aria-label={t('e13.tab.aria')} style={{ display: 'flex', gap: '.5rem', marginBottom: '1rem' }}>
          <button role="tab" aria-selected={tab === 'proposal'} className={tab === 'proposal' ? 'ui-button' : 'ui-button secondary'} onClick={() => setTab('proposal')}>{t('proposal')}</button>
          <button role="tab" aria-selected={tab === 'master-plan'} className={tab === 'master-plan' ? 'ui-button' : 'ui-button secondary'} onClick={() => setTab('master-plan')}>{t('masterPlan')}</button>
        </div>

        {saveMessage && <ViewState kind="unavailable" title={t('e13.status')} detail={saveMessage} />}

        {tab === 'proposal' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', marginBottom: '.5rem' }}>
              <StatusBadge value={data.proposal.preApprovalOnly ? 'REVIEW_REQUIRED' : 'CURRENT'} />
              <span className="ui-kicker">{t('e13.revision')}{data.proposal.latestRevision}</span>
              {!editingProposal && <button className="ui-button" style={{ marginLeft: 'auto' }} onClick={startProposalEdit}>{t('e13.edit')}</button>}
            </div>
            {editingProposal && proposalForm ? (
              <div>
                {proposalErrors.length > 0 && <ViewState kind="error" title={t('e13.validation')} detail={proposalErrors.join(' ')} />}
                <label className="ui-kicker">{t('e13.productStatement')}<textarea aria-label={t('e13.productStatement')} value={proposalForm.productStatement} onChange={(e) => setProposalForm({ ...proposalForm, productStatement: e.target.value })} rows={3} style={{ width: '100%', marginTop: '.25rem' }} /></label>
                <label className="ui-kicker" style={{ display: 'block', marginTop: '.5rem' }}>{t('e13.targetOutcome')}<textarea aria-label={t('e13.targetOutcome')} value={proposalForm.targetOutcome} onChange={(e) => setProposalForm({ ...proposalForm, targetOutcome: e.target.value })} rows={3} style={{ width: '100%', marginTop: '.25rem' }} /></label>
                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '.5rem' }}>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <label className="ui-kicker">{t('e13.complexityBand')}
                      <select value={proposalForm.complexityBand} onChange={(e) => setProposalForm({ ...proposalForm, complexityBand: e.target.value })} style={{ width: '100%', marginTop: '.25rem', minHeight: 36 }}>
                        {COMPLEXITY_BANDS.map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </label>
                  </div>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <label className="ui-kicker">{t('e13.architectureStatus')}
                      <select value={proposalForm.candidateArchitecture.status} onChange={(e) => setProposalForm({ ...proposalForm, candidateArchitecture: { ...proposalForm.candidateArchitecture, status: e.target.value } })} style={{ width: '100%', marginTop: '.25rem', minHeight: 36 }}>
                        {ARCH_STATUSES.map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </label>
                  </div>
                </div>
                <label className="ui-kicker" style={{ display: 'block', marginTop: '.5rem' }}>{t('e13.architectureReason')}<textarea aria-label={t('e13.architectureReason')} value={proposalForm.candidateArchitecture.reason} onChange={(e) => setProposalForm({ ...proposalForm, candidateArchitecture: { ...proposalForm.candidateArchitecture, reason: e.target.value } })} rows={2} style={{ width: '100%', marginTop: '.25rem' }} /></label>
                <StringListField label={t('e13.scopeIn')} items={proposalForm.scopeIn} onChange={(v) => setProposalForm({ ...proposalForm, scopeIn: v })} placeholder={t('e13.scopeItem')} t={t} />
                <StringListField label={t('e13.scopeOut')} items={proposalForm.scopeOut} onChange={(v) => setProposalForm({ ...proposalForm, scopeOut: v })} placeholder={t('e13.scopeItem')} t={t} />
                <RequirementListField label={t('requirements')} items={proposalForm.requirements} onChange={(v) => setProposalForm({ ...proposalForm, requirements: v })} t={t} />
                <AssumptionListField label={t('assumptions')} items={proposalForm.assumptions} onChange={(v) => setProposalForm({ ...proposalForm, assumptions: v })} t={t} />
                <StringListField label={t('e13.unresolvedItems')} items={proposalForm.unresolvedItems} onChange={(v) => setProposalForm({ ...proposalForm, unresolvedItems: v })} placeholder={t('e13.unresolvedItem')} t={t} />
                <div style={{ display: 'flex', gap: '.5rem', marginTop: '1rem' }}>
                  <button className="ui-button" disabled={savingProposal || proposalErrors.length > 0} onClick={() => void saveProposal()}>{savingProposal ? t('e13.saving') : t('e13.saveNewRevision')}</button>
                  <button className="ui-button secondary" onClick={discardProposal}>{t('e13.discard')}</button>
                </div>
              </div>
            ) : (
              <div>
                <p><strong>{data.proposal.current.content.productStatement}</strong></p>
                <p>{data.proposal.current.content.targetOutcome}</p>
                <p className="ui-kicker">{t('requirements')}: {data.proposal.current.content.requirements.length} · {t('assumptions')}: {data.proposal.current.content.assumptions.length} · {t('e13.complexityLabel')} {data.proposal.current.content.complexityBand}</p>
                <ProposalRevisionHistory revisions={data.proposalRevisions} current={data.proposal.current} t={t} />
              </div>
            )}
          </div>
        )}

        {tab === 'master-plan' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', marginBottom: '.5rem' }}>
              <StatusBadge value={data.plan.preApprovalOnly ? 'REVIEW_REQUIRED' : 'CURRENT'} />
              <span className="ui-kicker">{t('e13.revision')}{data.plan.latestRevision}</span>
              {data.plan.proposalRevisionStatus && data.plan.proposalRevisionStatus !== 'CURRENT' && <StatusBadge value="STALE" />}
              {!editingPlan && <button className="ui-button" style={{ marginLeft: 'auto' }} onClick={startPlanEdit}>{t('e13.edit')}</button>}
            </div>
            {editingPlan && planForm ? (
              <div>
                {planErrors.length > 0 && <ViewState kind="error" title={t('e13.validation')} detail={planErrors.join(' ')} />}
                <label className="ui-kicker">{t('e13.goal')}<textarea aria-label={t('e13.goal')} value={planForm.goal} onChange={(e) => setPlanForm({ ...planForm, goal: e.target.value })} rows={3} style={{ width: '100%', marginTop: '.25rem' }} /></label>
                <RequirementListField label={t('requirements')} items={planForm.requirements} onChange={(v) => setPlanForm({ ...planForm, requirements: v })} t={t} />
                <StringListField label={t('e13.constraints')} items={planForm.constraints} onChange={(v) => setPlanForm({ ...planForm, constraints: v })} placeholder={t('e13.constraintPlaceholder')} t={t} />
                <StringListField label={t('e13.phases')} items={planForm.phases} onChange={(v) => setPlanForm({ ...planForm, phases: v })} placeholder={t('e13.phasePlaceholder')} t={t} />
                <NodeListField label={t('e13.nodes')} items={planForm.nodes} onChange={(v) => setPlanForm({ ...planForm, nodes: v })} t={t} />
                <DependencyListField label={t('e13.dependencies')} items={planForm.dependencies} onChange={(v) => setPlanForm({ ...planForm, dependencies: v })} t={t} />
                <StringListField label={t('e13.risks')} items={planForm.risks} onChange={(v) => setPlanForm({ ...planForm, risks: v })} placeholder={t('e13.riskPlaceholder')} t={t} />
                <label className="ui-kicker" style={{ display: 'block', marginTop: '.5rem' }}>{t('e13.verificationIntentStatus')}
                  <select value={planForm.verificationIntent.status} onChange={(e) => setPlanForm({ ...planForm, verificationIntent: { ...planForm.verificationIntent, status: e.target.value } })} style={{ width: '100%', marginTop: '.25rem', minHeight: 36 }}>
                    {VERIFICATION_STATUSES.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </label>
                <StringListField label={t('e13.verificationRequirementKeys')} items={planForm.verificationIntent.requirementKeys} onChange={(v) => setPlanForm({ ...planForm, verificationIntent: { ...planForm.verificationIntent, requirementKeys: v } })} placeholder={t('e13.requirementKeyPlaceholder')} t={t} />
                <div style={{ display: 'flex', gap: '.5rem', marginTop: '1rem' }}>
                  <button className="ui-button" disabled={savingPlan || planErrors.length > 0} onClick={() => void savePlan()}>{savingPlan ? t('e13.saving') : t('e13.saveNewRevision')}</button>
                  <button className="ui-button secondary" onClick={discardPlan}>{t('e13.discard')}</button>
                </div>
              </div>
            ) : (
              <div>
                <p><strong>{data.plan.current.content.goal}</strong></p>
                <p className="ui-kicker">{t('requirements')}: {data.plan.current.content.requirements.length} · {t('e13.nodeCount')} {data.plan.current.content.nodes.length} · {t('e13.riskCount')} {data.plan.current.content.risks.length}</p>
                <MasterPlanRevisionHistory revisions={data.planRevisions} current={data.plan.current} t={t} />
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
