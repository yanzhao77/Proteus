export type ConnectionState = 'live' | 'stale' | 'rehydrating' | 'degraded' | 'not_connected';
export type ProductionState = 'running' | 'planning' | 'waiting' | 'paused' | 'recovering' | 'completed' | 'failed' | 'stale';
export type PrimaryAction = 'open_production' | 'continue_planning' | 'review_gate' | 'review_resume' | 'open_delivery' | 'inspect_recovery' | 'refresh_snapshot';
export type Availability = 'CURRENT' | 'NOT_AVAILABLE' | 'NOT_IMPLEMENTED' | 'DEGRADED';

export interface Freshness { asOf: string | null; status: ConnectionState; source: string | null; }
export interface ProductionCardViewModel {
  productionId: string; displayName: string; state: ProductionState; phase: string | null;
  currentAction: string | null; progress: number | null; progressSource: string | null;
  lastUpdated: string | null; freshness: Freshness; owner: string | null;
  gateCount: number | null; planRevision: string | null; primaryAction: PrimaryAction;
}
export interface GateViewModel {
  gateId: string; productionName: string | null; action: string; risk: 'low' | 'medium' | 'high' | 'critical' | 'not_available';
  reason: string; evidenceCount: number | null; expiresAt: string | null; freshness: Freshness;
}
export interface DraftRevisionViewModel { revisionId: string; revisionNumber: number; title: string; rawInput: string; createdBy: string; draftVersion: number; createdAt: string; }
export interface DraftViewModel { draftId: string; title: string; state: 'DRAFT' | 'SUBMITTED' | 'ARCHIVED'; idea: string; latestRevision: number; createdAt: string; updatedAt: string; version: number; freshness: Freshness; revisions?: DraftRevisionViewModel[]; }
export interface DraftListViewModel { draftId: string; title: string; state: 'DRAFT' | 'SUBMITTED' | 'ARCHIVED'; latestRevision: number; createdAt: string; updatedAt: string; version: number; freshness: Freshness; }
export type AdapterResult<T> = { kind: 'data'; value: T } | { kind: 'not_implemented'; message: string } | { kind: 'error'; message: string };
export interface CommandMetadata { actor: string; reason: string; idempotencyKey: string; expectedVersion: number; }
export interface UnderstandingRevisionViewModel { revisionId: string; revisionNumber: number; sourceDraftId: string; sourceDraftRevision: number; interpretedIntent: string; objective: string | null; explicitRequirements: string[]; userConstraints: string[]; ambiguities: string[]; openQuestions: string[]; confidence: number | null; providerMetadata: Record<string, unknown> | null; generatedAt: string; }
export interface ClarificationViewModel { clarificationId: string; question: string; rationale: string | null; state: 'OPEN' | 'ANSWERED'; answer: string | null; answeredAt: string | null; }
export interface AssumptionViewModel { assumptionId: string; statement: string; basis: string | null; revisionId: string; }
export interface UnderstandingViewModel { understandingId: string; draftId: string; state: 'READY' | 'NEEDS_CLARIFICATION'; version: number; latestRevision: number; current: UnderstandingRevisionViewModel; revisions: UnderstandingRevisionViewModel[]; clarifications: ClarificationViewModel[]; assumptions: AssumptionViewModel[]; freshness: Freshness; }
export interface ProductionDraftApi { createDraft(title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; listDrafts(): Promise<AdapterResult<DraftListViewModel[]>>; getDraft(draftId: string): Promise<AdapterResult<DraftViewModel>>; submitIdeaRevision(draftId: string, title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; submitDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; archiveDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; requestUnderstanding(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>>; getUnderstanding(draftId: string): Promise<AdapterResult<UnderstandingViewModel>>; answerClarification(draftId: string, clarificationId: string, answer: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>>; }
export interface ProductionPortfolioApi { listProductions(): Promise<AdapterResult<ProductionCardViewModel[]>>; getProduction(id: string): Promise<AdapterResult<ProductionCardViewModel>>; }
export interface GateApi { listGates(): Promise<AdapterResult<GateViewModel[]>>; getGate(id: string): Promise<AdapterResult<GateViewModel>>; submitDecision(id: string, decision: 'APPROVE' | 'REJECT', metadata: CommandMetadata): Promise<AdapterResult<void>>; }
export interface ProductionApi { getSnapshot(id: string): Promise<AdapterResult<ProductionCardViewModel>>; pause(id: string, metadata: CommandMetadata): Promise<AdapterResult<void>>; resume(id: string, metadata: CommandMetadata): Promise<AdapterResult<void>>; stop(id: string, metadata: CommandMetadata): Promise<AdapterResult<void>>; }
export interface FactoryAdapters { mode: 'development_fixture' | 'authority_pending' | 'product_api'; draft: ProductionDraftApi; portfolio: ProductionPortfolioApi; gates: GateApi; production: ProductionApi; }
