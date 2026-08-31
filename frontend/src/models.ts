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
export interface GateDetailViewModel extends GateViewModel {
  projectId: string; requestType: string; riskRef: string | null; status: string; version: number;
  evidenceRefs: string[]; asOf: string | null;
  audit: { decisionId: string; decision: string; status: string; issuedAt: string | null; expiresAt: string | null }[];
}
export interface GateDecisionMetadata { reason: string; expectedGateVersion: number; }
export interface GateDecisionReceiptViewModel {
  commandId: string; gateRequestId: string; gateDecisionId: string; receiptStatus: string;
  resultCode: string; requestState: string; requestVersion: number | null; decision: string;
  eventIds: string[]; completionClaim: string;
}
export interface DraftRevisionViewModel { revisionId: string; revisionNumber: number; title: string; rawInput: string; createdBy: string; draftVersion: number; createdAt: string; }
export interface DraftViewModel { draftId: string; title: string; state: 'DRAFT' | 'SUBMITTED' | 'ARCHIVED'; idea: string; latestRevision: number; createdAt: string; updatedAt: string; version: number; freshness: Freshness; revisions?: DraftRevisionViewModel[]; }
export interface DraftListViewModel { draftId: string; title: string; state: 'DRAFT' | 'SUBMITTED' | 'ARCHIVED'; latestRevision: number; createdAt: string; updatedAt: string; version: number; freshness: Freshness; }
export type AdapterResult<T> = { kind: 'data'; value: T } | { kind: 'not_implemented'; message: string } | { kind: 'error'; message: string };
export interface CommandMetadata { reason: string; idempotencyKey: string; expectedVersion: number; authorizationRef?: string; }
export interface ProjectCommandReceiptViewModel { commandId: string; action: string | null; receiptStatus: string; resultCode: string; targetVersion: number | null; eventIds: string[]; projectionStatus: string; }
export interface UnderstandingRevisionViewModel { revisionId: string; revisionNumber: number; sourceDraftId: string; sourceDraftRevision: number; interpretedIntent: string; objective: string | null; explicitRequirements: string[]; userConstraints: string[]; ambiguities: string[]; openQuestions: string[]; confidence: number | null; providerMetadata: Record<string, unknown> | null; generatedAt: string; }
export interface ClarificationViewModel { clarificationId: string; question: string; rationale: string | null; state: 'OPEN' | 'ANSWERED'; answer: string | null; answeredAt: string | null; }
export interface AssumptionViewModel { assumptionId: string; statement: string; basis: string | null; revisionId: string; }
export interface UnderstandingViewModel { understandingId: string; draftId: string; state: 'READY' | 'NEEDS_CLARIFICATION'; version: number; latestRevision: number; current: UnderstandingRevisionViewModel; revisions: UnderstandingRevisionViewModel[]; clarifications: ClarificationViewModel[]; assumptions: AssumptionViewModel[]; freshness: Freshness; }
export interface ApprovalPreviewViewModel { bridgeId: string; compiledBlueprintHash: string; requiredAcknowledgements: string[]; status: string; projectId: string | null; }
export interface ApprovalResultViewModel { bridgeId: string; status: string; projectId: string | null; compiledBlueprintHash?: string; }
export interface ProductionDraftApi { createDraft(title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; listDrafts(): Promise<AdapterResult<DraftListViewModel[]>>; getDraft(draftId: string): Promise<AdapterResult<DraftViewModel>>; submitIdeaRevision(draftId: string, title: string, idea: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; submitDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; archiveDraft(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>>; requestUnderstanding(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>>; getUnderstanding(draftId: string): Promise<AdapterResult<UnderstandingViewModel>>; answerClarification(draftId: string, clarificationId: string, answer: string, metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>>; getProposal(draftId: string): Promise<AdapterResult<ProposalViewModel>>; generateProposal(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<ProposalViewModel>>; listProposalRevisions(draftId: string): Promise<AdapterResult<ProposalRevisionViewModel[]>>; saveProposalRevision(draftId: string, content: ProposalContentEditViewModel, metadata: CommandMetadata): Promise<AdapterResult<ProposalViewModel>>; getMasterPlan(draftId: string): Promise<AdapterResult<MasterPlanViewModel>>; generateMasterPlan(draftId: string, metadata: CommandMetadata): Promise<AdapterResult<MasterPlanViewModel>>; listMasterPlanRevisions(draftId: string): Promise<AdapterResult<MasterPlanRevisionViewModel[]>>; saveMasterPlanRevision(draftId: string, content: MasterPlanContentEditViewModel, metadata: CommandMetadata): Promise<AdapterResult<MasterPlanViewModel>>; getApprovalPreview?(draftId: string): Promise<AdapterResult<ApprovalPreviewViewModel>>; getApprovalStatus?(draftId: string): Promise<AdapterResult<ApprovalResultViewModel>>; approveMasterPlan?(draftId: string, payload: Record<string, unknown>): Promise<AdapterResult<ApprovalResultViewModel>>; }

export interface ProposalContentViewModel {
  productStatement: string; targetOutcome: string; scopeIn: string[]; scopeOut: string[];
  requirements: { key: string; statement: string; source: string }[];
  assumptions: { assumptionId: string; statement: string; basis: string; status: string }[];
  unresolvedItems: string[]; complexityBand: string;
  candidateArchitecture: { status: string; reason?: string };
  sourceDraftRevisionId: string; sourceUnderstandingRevisionId: string;
}
export interface ProposalRevisionViewModel { revisionId: string; revisionNumber: number; contentHash: string; compiler: string; schemaVersion: string; content: ProposalContentViewModel; createdAt: string; }
export interface ProposalViewModel { proposalId: string; draftId: string; version: number; latestRevision: number; current: ProposalRevisionViewModel; revisions: ProposalRevisionViewModel[]; preApprovalOnly: boolean; }
export interface MasterPlanContentViewModel { goal: string; requirements: { key: string; statement: string; source: string }[]; constraints: string[]; phases: string[]; nodes: { nodeKey: string; phase: string; title: string; requirementRefs: string[]; verificationRefs: string[] }[]; dependencies: { source: string; target: string }[]; risks: string[]; verificationIntent?: { status: string; requirementKeys: string[] }; preApprovalOnly: boolean; sourceDraftRevisionId: string; sourceUnderstandingRevisionId: string; }
export interface MasterPlanRevisionViewModel { revisionId: string; revisionNumber: number; contentHash: string; compiler: string; schemaVersion: string; proposalRevisionId: string; content: MasterPlanContentViewModel; createdAt: string; }
export interface MasterPlanViewModel { masterPlanId: string; proposalId: string; draftId: string; version: number; latestRevision: number; current: MasterPlanRevisionViewModel; revisions: MasterPlanRevisionViewModel[]; preApprovalOnly: boolean; proposalRevisionStatus?: string; }
export interface ProposalContentEditViewModel {
  productStatement: string; targetOutcome: string; scopeIn: string[]; scopeOut: string[];
  requirements: { key: string; statement: string; source: string }[];
  assumptions: { assumptionId: string; statement: string; basis: string; status: string }[];
  unresolvedItems: string[]; complexityBand: string;
  candidateArchitecture: { status: string; reason?: string };
}
export interface MasterPlanContentEditViewModel {
  goal: string; requirements: { key: string; statement: string; source: string }[]; constraints: string[];
  phases: string[]; nodes: { nodeKey: string; phase: string; title: string; requirementRefs: string[]; verificationRefs: string[] }[];
  dependencies: { source: string; target: string }[]; risks: string[];
  verificationIntent: { status: string; requirementKeys: string[] };
}
export interface ProductionPortfolioApi { listProductions(): Promise<AdapterResult<ProductionCardViewModel[]>>; getProduction(id: string): Promise<AdapterResult<ProductionCardViewModel>>; }
export interface GateApi { listGates(): Promise<AdapterResult<GateViewModel[]>>; getGate(id: string): Promise<AdapterResult<GateDetailViewModel>>; submitDecision(id: string, decision: 'APPROVE' | 'REJECT', metadata: GateDecisionMetadata): Promise<AdapterResult<GateDecisionReceiptViewModel>>; }
export interface LiveProductionEventViewModel { eventId: string; productionSequence: number; aggregateType: string; aggregateId: string; aggregateVersion: number | null; eventKind: string; occurredAt: string | null; schemaVersion: string; }
export interface LiveProductionSnapshotViewModel { productionId: string; project: { projectId: string; title: string; state: string; version: number; updatedAt: string | null }; snapshotWatermark: number; projectionSchemaVersion: string; workflow: { nodes: { nodeId: string; title: string; state: string; version: number; sourceIdentity: string }[]; edges: { edgeId: string; taskId: string; dependsOnTaskId: string; sourceIdentity: string | null }[] }; executionRequests: { executionRequestId: string; taskId: string; state: string; version: number }[]; verification: { plans: { planId: string; taskId: string; status: string; version: number }[]; results: { verificationId: string; taskId: string; verdict: string; authorityStatus: string }[] }; evidence: { validCount: number; invalidatedCount: number; missingCount: number; items: { evidenceId: string; valid: boolean; artifactHash: string; mediaType: string }[] }; gates: { gateId: string; status: string; reason: string; reviewLink: string }[]; waiting: { waitingRecordId: string; taskId: string; type: string; reason: string; state: string; gateId: string | null }[]; recovery: { findingId: string; kind: string; status: string; observedSequence: number | null }[]; recentEvents: LiveProductionEventViewModel[]; freshness: string; asOf: string | null; }
export interface LiveProductionEventFeedViewModel { availability: string; reason: string | null; items: LiveProductionEventViewModel[]; after: number; nextCursor: number; snapshotWatermark: number; projectionSchemaVersion: string; }
export interface ProductionApi { getSnapshot(id: string): Promise<AdapterResult<ProductionCardViewModel>>; getLiveSnapshot(id: string, signal?: AbortSignal): Promise<AdapterResult<LiveProductionSnapshotViewModel>>; getLiveEvents(id: string, after: number, limit?: number, signal?: AbortSignal): Promise<AdapterResult<LiveProductionEventFeedViewModel>>; getCommandReceipt(id: string, commandId: string, signal?: AbortSignal): Promise<AdapterResult<ProjectCommandReceiptViewModel>>; pause(id: string, metadata: CommandMetadata): Promise<AdapterResult<ProjectCommandReceiptViewModel>>; resume(id: string, metadata: CommandMetadata): Promise<AdapterResult<ProjectCommandReceiptViewModel>>; stop(id: string, metadata: CommandMetadata): Promise<AdapterResult<ProjectCommandReceiptViewModel>>; }
export interface FactoryAdapters { mode: 'development_fixture' | 'authority_pending' | 'product_api'; draft: ProductionDraftApi; portfolio: ProductionPortfolioApi; gates: GateApi; production: ProductionApi; }
