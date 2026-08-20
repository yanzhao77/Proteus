import type { AdapterResult, CommandMetadata, DraftListViewModel, DraftViewModel, UnderstandingViewModel, FactoryAdapters, GateApi, GateViewModel, ProductionApi, ProductionCardViewModel, ProductionDraftApi, ProductionPortfolioApi } from '../models';

const now = '2026-08-18T09:40:00Z';
const fresh = { asOf: now, status: 'live' as const, source: 'DEVELOPMENT FIXTURE' };
const cards: ProductionCardViewModel[] = [
  { productionId: 'demo-running', displayName: 'DreamKnowledge', state: 'running', phase: 'Backend Implementation', currentAction: 'Verified implementation work is available in the source projection.', progress: null, progressSource: null, lastUpdated: now, freshness: fresh, owner: 'NOT AVAILABLE', gateCount: 0, planRevision: 'NOT AVAILABLE', primaryAction: 'open_production' },
  { productionId: 'demo-paused', displayName: 'NexaCache', state: 'paused', phase: 'Resume Review', currentAction: 'A resume decision must occur in Live Production, not on Home.', progress: null, progressSource: null, lastUpdated: now, freshness: fresh, owner: 'NOT AVAILABLE', gateCount: 0, planRevision: 'NOT AVAILABLE', primaryAction: 'review_resume' },
  { productionId: 'demo-waiting', displayName: 'Video Platform', state: 'waiting', phase: 'Human Gate', currentAction: 'A high-risk review is required before the authority resumes.', progress: null, progressSource: null, lastUpdated: now, freshness: fresh, owner: 'NOT AVAILABLE', gateCount: 1, planRevision: 'NOT AVAILABLE', primaryAction: 'review_gate' },
];
const gates: GateViewModel[] = [{ gateId: 'demo-gate-001', productionName: 'Video Platform', action: 'Approve database migration', risk: 'high', reason: 'The gate is a DEVELOPMENT fixture. Review routes are non-authoritative.', evidenceCount: null, expiresAt: null, freshness: fresh }];
const data = <T>(value: T): Promise<AdapterResult<T>> => Promise.resolve({ kind: 'data', value });
const noMutation = <T>(): Promise<AdapterResult<T>> => Promise.resolve({ kind: 'not_implemented', message: 'DEVELOPMENT FIXTURE does not submit authority commands.' });
class FixtureDraftApi implements ProductionDraftApi {
  getProposal(_draftId: string): Promise<AdapterResult<import('../models').ProposalViewModel>> { return Promise.resolve({ kind: 'not_implemented', message: 'E3 PROPOSAL AUTHORITY IS NOT AVAILABLE IN THIS ADAPTER.' }); }
  generateProposal(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<import('../models').ProposalViewModel>> { return noMutation(); }
  getMasterPlan(_draftId: string): Promise<AdapterResult<import('../models').MasterPlanViewModel>> { return Promise.resolve({ kind: 'not_implemented', message: 'E3 MASTER PLAN AUTHORITY IS NOT AVAILABLE IN THIS ADAPTER.' }); }
  generateMasterPlan(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<import('../models').MasterPlanViewModel>> { return noMutation(); }

  createDraft(_title: string, _idea: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return noMutation(); }
  listDrafts(): Promise<AdapterResult<DraftListViewModel[]>> { return Promise.resolve({ kind: 'not_implemented', message: 'DEVELOPMENT FIXTURE DOES NOT PROVIDE DRAFT AUTHORITY' }); }
  getDraft(_draftId: string): Promise<AdapterResult<DraftViewModel>> { return Promise.resolve({ kind: 'not_implemented', message: 'DEVELOPMENT FIXTURE DOES NOT PROVIDE DRAFT AUTHORITY' }); }
  submitIdeaRevision(_draftId: string, _title: string, _idea: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return noMutation(); }
  submitDraft(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return noMutation(); }
  archiveDraft(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return noMutation(); }
  requestUnderstanding(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return noMutation(); }
  getUnderstanding(_draftId: string): Promise<AdapterResult<UnderstandingViewModel>> { return Promise.resolve({ kind: 'not_implemented', message: 'E2 UNDERSTANDING AUTHORITY IS NOT AVAILABLE IN THIS ADAPTER.' }); }
  answerClarification(_draftId: string, _clarificationId: string, _answer: string, _metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return noMutation(); }
}
class FixturePortfolioApi implements ProductionPortfolioApi {
  listProductions(): Promise<AdapterResult<ProductionCardViewModel[]>> { return data(cards); }
  getProduction(id: string): Promise<AdapterResult<ProductionCardViewModel>> { return data(cards.find((card) => card.productionId === id) ?? cards[0]); }
}
class FixtureGateApi implements GateApi {
  listGates(): Promise<AdapterResult<GateViewModel[]>> { return data(gates); }
  getGate(id: string): Promise<AdapterResult<GateViewModel>> { return data(gates.find((gate) => gate.gateId === id) ?? gates[0]); }
  submitDecision(): Promise<AdapterResult<void>> { return noMutation(); }
}
class FixtureProductionApi implements ProductionApi {
  getSnapshot(id: string): Promise<AdapterResult<ProductionCardViewModel>> { return data(cards.find((card) => card.productionId === id) ?? cards[0]); }
  pause(): Promise<AdapterResult<void>> { return noMutation(); }
  resume(): Promise<AdapterResult<void>> { return noMutation(); }
  stop(): Promise<AdapterResult<void>> { return noMutation(); }
}
export const developmentFixtureAdapters = (): FactoryAdapters => ({ mode: 'development_fixture', draft: new FixtureDraftApi(), portfolio: new FixturePortfolioApi(), gates: new FixtureGateApi(), production: new FixtureProductionApi() });
