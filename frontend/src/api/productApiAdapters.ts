import type { AdapterResult, CommandMetadata, DraftListViewModel, DraftViewModel, UnderstandingViewModel, FactoryAdapters, GateApi, GateViewModel, ProductionApi, ProductionCardViewModel, ProductionDraftApi, ProductionPortfolioApi, ProductionState } from '../models';

interface ApiEnvelope<T> { data: T | null; error: { code: string; message: string } | null; request_id: string; }
interface AvailabilityEnvelope { availability: string; reason: string | null; items?: unknown[]; item?: unknown; }
const stateMap: Record<string, ProductionState> = { CREATED: 'planning', INTAKE: 'planning', DISCOVERY: 'planning', PLANNING: 'planning', DESIGNING: 'planning', IMPLEMENTING: 'running', VERIFYING: 'running', HARDENING: 'running', PACKAGING: 'running', DELIVERING: 'running', WAITING_FOR_HUMAN: 'waiting', WAITING_FOR_RESOURCE: 'waiting', PAUSED: 'paused', BLOCKED: 'stale', RECOVERING: 'recovering', ACCEPTED: 'completed', FAILED: 'failed', CANCELLED: 'failed' };
const apiBase = import.meta.env.VITE_PRODUCT_API_BASE_URL ?? '';
const pending = <T>(name: string): Promise<AdapterResult<T>> => Promise.resolve({ kind: 'not_implemented', message: `${name} is outside FH-1 read-only scope.` });

async function get<T>(path: string): Promise<AdapterResult<T>> {
  try {
    const response = await fetch(`${apiBase}${path}`, { headers: { Accept: 'application/json' }, credentials: 'omit' });
    const envelope = await response.json() as ApiEnvelope<T>;
    if (!response.ok || envelope.error) return { kind: 'error', message: envelope.error?.message ?? 'Product API request failed.' };
    if (!envelope.data) return { kind: 'error', message: 'Product API returned no read model.' };
    const availability = envelope.data as unknown as AvailabilityEnvelope;
    if (availability.availability !== 'CURRENT') return { kind: 'not_implemented', message: availability.reason ?? `${path} is not available for this actor scope.` };
    return { kind: 'data', value: envelope.data };
  } catch { return { kind: 'error', message: 'Product API is unreachable. The affected read deck was not loaded.' }; }
}

async function post<T>(path: string, body: Record<string, unknown>): Promise<AdapterResult<T>> {
  try {
    const response = await fetch(`${apiBase}${path}`, { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Idempotency-Key': String(body.idempotency_key ?? '') }, credentials: 'omit', body: JSON.stringify(body) });
    const envelope = await response.json() as ApiEnvelope<T>;
    if (!response.ok || envelope.error) return { kind: 'error', message: envelope.error?.code ?? envelope.error?.message ?? 'Product API command failed.' };
    if (!envelope.data) return { kind: 'error', message: 'Product API returned no authority result.' };
    return { kind: 'data', value: envelope.data };
  } catch { return { kind: 'error', message: 'Product API is unreachable. No local Draft state was created.' }; }
}

function freshness(input: Record<string, unknown>) { return { asOf: typeof input.as_of === 'string' ? input.as_of : null, status: input.freshness === 'CURRENT' ? 'live' as const : input.availability === 'DEGRADED' ? 'degraded' as const : 'not_connected' as const, source: typeof input.source === 'string' ? input.source : null }; }
function production(raw: unknown): ProductionCardViewModel { const row = raw as Record<string, unknown>; const rawState = typeof row.display_state === 'string' ? row.display_state : ''; return { productionId: String(row.production_id), displayName: typeof row.display_name === 'string' ? row.display_name : 'NOT AVAILABLE', state: stateMap[rawState] ?? 'stale', phase: typeof row.phase === 'string' ? row.phase : null, currentAction: typeof row.current_summary === 'string' ? row.current_summary : null, progress: typeof row.progress === 'number' ? row.progress : null, progressSource: typeof row.progress_basis === 'string' && row.progress_basis !== 'NOT_AVAILABLE' ? row.progress_basis : null, lastUpdated: typeof row.last_updated === 'string' ? row.last_updated : null, freshness: freshness(row), owner: typeof row.owner === 'string' ? row.owner : null, gateCount: typeof row.gate_count === 'number' ? row.gate_count : null, planRevision: typeof row.plan_revision === 'string' ? row.plan_revision : null, primaryAction: rawState === 'WAITING_FOR_HUMAN' ? 'review_gate' : rawState === 'PAUSED' ? 'review_resume' : 'open_production' }; }
function asStringList(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
function understanding(raw: unknown): UnderstandingViewModel { const row = raw as Record<string, any>; const revision = (item: any) => ({ revisionId: String(item.understanding_revision_id), revisionNumber: Number(item.revision_number), sourceDraftId: String(item.source_draft_id), sourceDraftRevision: Number(item.source_draft_revision_number), interpretedIntent: String(item.interpreted_intent), objective: typeof item.objective === 'string' ? item.objective : null, explicitRequirements: asStringList(item.explicit_requirements), userConstraints: asStringList(item.user_constraints), ambiguities: asStringList(item.ambiguities), openQuestions: asStringList(item.open_questions), confidence: typeof item.confidence === 'number' ? item.confidence : null, providerMetadata: item.provider_metadata && typeof item.provider_metadata === 'object' ? item.provider_metadata : null, generatedAt: String(item.generated_at) }); return { understandingId: String(row.understanding_id), draftId: String(row.draft_id), state: row.state === 'READY' ? 'READY' : 'NEEDS_CLARIFICATION', version: Number(row.version), latestRevision: Number(row.latest_revision_number), current: revision(row.current), revisions: Array.isArray(row.revisions) ? row.revisions.map(revision) : [], clarifications: Array.isArray(row.clarifications) ? row.clarifications.map((item: any) => ({ clarificationId: String(item.clarification_id), question: String(item.question), rationale: typeof item.rationale === 'string' ? item.rationale : null, state: item.state === 'ANSWERED' ? 'ANSWERED' : 'OPEN', answer: typeof item.answer === 'string' ? item.answer : null, answeredAt: typeof item.answered_at === 'string' ? item.answered_at : null })) : [], assumptions: Array.isArray(row.assumptions) ? row.assumptions.map((item: any) => ({ assumptionId: String(item.assumption_id), statement: String(item.statement), basis: typeof item.basis === 'string' ? item.basis : null, revisionId: String(item.understanding_revision_id) })) : [], freshness: freshness(row) }; }
function gate(raw: unknown): GateViewModel { const row = raw as Record<string, unknown>; return { gateId: String(row.gate_id), productionName: typeof row.production_name === 'string' ? row.production_name : null, action: typeof row.action_summary === 'string' ? row.action_summary : 'NOT AVAILABLE', risk: 'not_available', reason: typeof row.reason === 'string' ? row.reason : 'NOT AVAILABLE', evidenceCount: typeof row.evidence_count === 'number' ? row.evidence_count : null, expiresAt: typeof row.expires_at === 'string' ? row.expires_at : null, freshness: freshness(row) }; }
class ProductApiDrafts implements ProductionDraftApi {
  private map(item: any): DraftViewModel { return { draftId: item.draft_id, title: item.title, idea: item.raw_input, state: item.state, latestRevision: item.latest_revision, createdAt: item.created_at, updatedAt: item.updated_at, version: item.version, freshness: freshness(item), revisions: item.revisions?.map((revision: any) => ({ revisionId: revision.revision_id, revisionNumber: revision.revision_number, title: revision.title, rawInput: revision.raw_input, createdBy: revision.created_by, draftVersion: revision.draft_version, createdAt: revision.created_at })) }; }
  private listMap(item: any): DraftListViewModel { return { draftId: item.draft_id, title: item.title, state: item.state, latestRevision: item.latest_revision, createdAt: item.created_at, updatedAt: item.updated_at, version: item.version, freshness: freshness(item) }; }
  private async command(path: string, payload: Record<string, unknown>): Promise<AdapterResult<DraftViewModel>> { const result = await post<any>(path, payload); if (result.kind !== 'data') return result; return result.value.item ? { kind: 'data', value: this.map(result.value.item) } : { kind: 'not_implemented', message: result.value.reason ?? 'Draft authority is not available.' }; }
  createDraft(title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return this.command('/production-drafts', { title, raw_input: idea, reason: metadata.reason, idempotency_key: metadata.idempotencyKey }); }
  async listDrafts(): Promise<AdapterResult<DraftListViewModel[]>> { const result = await get<any>('/production-drafts'); if (result.kind !== 'data') return result; return result.value.availability === 'CURRENT' ? { kind: 'data', value: (result.value.items ?? []).map((item: any) => this.listMap(item)) } : { kind: 'not_implemented', message: result.value.reason ?? 'Draft authority is not available.' }; }
  async getDraft(draftId: string): Promise<AdapterResult<DraftViewModel>> { const result = await get<any>(`/production-drafts/${encodeURIComponent(draftId)}`); if (result.kind !== 'data') return result; return result.value.item ? { kind: 'data', value: this.map(result.value.item) } : { kind: 'not_implemented', message: result.value.reason ?? 'Draft is not available.' }; }
  submitIdeaRevision(draftId: string, title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return this.command(`/production-drafts/${encodeURIComponent(draftId)}/revisions`, { title, raw_input: idea, reason: metadata.reason, idempotency_key: metadata.idempotencyKey, expected_version: metadata.expectedVersion }); }
  submitDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return this.command(`/production-drafts/${encodeURIComponent(draftId)}/submit`, { reason: metadata.reason, idempotency_key: metadata.idempotencyKey, expected_version: metadata.expectedVersion }); }
  archiveDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return this.command(`/production-drafts/${encodeURIComponent(draftId)}/archive`, { reason: metadata.reason, idempotency_key: metadata.idempotencyKey, expected_version: metadata.expectedVersion }); }
  private mapUnderstanding(result: AdapterResult<any>): AdapterResult<UnderstandingViewModel> { if (result.kind !== 'data') return result; return result.value.item ? { kind: 'data', value: understanding(result.value.item) } : { kind: 'not_implemented', message: result.value.reason ?? 'Understanding is not available.' }; }
  getUnderstanding(draftId: string): Promise<AdapterResult<UnderstandingViewModel>> { return get<any>(`/production-drafts/${encodeURIComponent(draftId)}/understanding`).then((result) => this.mapUnderstanding(result)); }
  requestUnderstanding(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return post<any>(`/production-drafts/${encodeURIComponent(draftId)}/understanding`, { reason: metadata.reason, idempotency_key: metadata.idempotencyKey, expected_version: metadata.expectedVersion }).then((result) => this.mapUnderstanding(result)); }
  answerClarification(draftId: string, clarificationId: string, answer: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return post<any>(`/production-drafts/${encodeURIComponent(draftId)}/understanding/clarifications/${encodeURIComponent(clarificationId)}/answer`, { answer, reason: metadata.reason, idempotency_key: metadata.idempotencyKey, expected_version: metadata.expectedVersion }).then((result) => this.mapUnderstanding(result)); }
}
class ProductApiPortfolio implements ProductionPortfolioApi {
  async listProductions(): Promise<AdapterResult<ProductionCardViewModel[]>> {
    const result = await get<AvailabilityEnvelope>('/factory-home/productions');
    if (result.kind !== 'data') return result;
    return { kind: 'data', value: (result.value.items ?? []).map(production) };
  }
  async getProduction(id: string): Promise<AdapterResult<ProductionCardViewModel>> {
    const result = await get<AvailabilityEnvelope>(`/factory-home/productions/${encodeURIComponent(id)}`);
    if (result.kind !== 'data') return result;
    return result.value.item ? { kind: 'data', value: production(result.value.item) } : { kind: 'not_implemented', message: result.value.reason ?? 'Production is not available for this actor scope.' };
  }
}
class ProductApiGates implements GateApi {
  async listGates(): Promise<AdapterResult<GateViewModel[]>> {
    const result = await get<AvailabilityEnvelope>('/factory-home/gates');
    if (result.kind !== 'data') return result;
    return { kind: 'data', value: (result.value.items ?? []).map(gate) };
  }
  getGate(_id: string): Promise<AdapterResult<GateViewModel>> { return pending('GateApi.getGate'); }
  submitDecision(_id: string, _decision: 'APPROVE' | 'REJECT', _metadata: import('../models').CommandMetadata): Promise<AdapterResult<void>> { return pending('GateApi.submitDecision'); }
}
class ProductApiProduction implements ProductionApi {
  getSnapshot(id: string): Promise<AdapterResult<ProductionCardViewModel>> { return new ProductApiPortfolio().getProduction(id); }
  pause(_id: string, _metadata: import('../models').CommandMetadata): Promise<AdapterResult<void>> { return pending('ProductionApi.pause'); }
  resume(_id: string, _metadata: import('../models').CommandMetadata): Promise<AdapterResult<void>> { return pending('ProductionApi.resume'); }
  stop(_id: string, _metadata: import('../models').CommandMetadata): Promise<AdapterResult<void>> { return pending('ProductionApi.stop'); }
}
export const productApiAdapters = (): FactoryAdapters => ({ mode: 'product_api', draft: new ProductApiDrafts(), portfolio: new ProductApiPortfolio(), gates: new ProductApiGates(), production: new ProductApiProduction() });
