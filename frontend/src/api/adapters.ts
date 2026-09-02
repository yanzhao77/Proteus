import type { AdapterResult, CommandMetadata, DraftListViewModel, DraftViewModel, UnderstandingViewModel, FactoryAdapters, GateApi, GateViewModel, ProductionApi, ProductionCardViewModel, ProductionDraftApi, ProductionPortfolioApi, WorkerControlPlaneApi } from '../models';

const pending = <T>(name: string): Promise<AdapterResult<T>> => Promise.resolve({ kind: 'not_implemented', message: `${name} is not implemented by the current Product API.` });

class PendingDraftApi implements ProductionDraftApi {
  getProposal(_draftId: string): Promise<import('../models').AdapterResult<import('../models').ProposalViewModel>> { return pending('DraftApi.getProposal'); }
  generateProposal(_draftId: string, _metadata: import('../models').CommandMetadata): Promise<import('../models').AdapterResult<import('../models').ProposalViewModel>> { return pending('DraftApi.generateProposal'); }
  getMasterPlan(_draftId: string): Promise<import('../models').AdapterResult<import('../models').MasterPlanViewModel>> { return pending('DraftApi.getMasterPlan'); }
  generateMasterPlan(_draftId: string, _metadata: import('../models').CommandMetadata): Promise<import('../models').AdapterResult<import('../models').MasterPlanViewModel>> { return pending('DraftApi.generateMasterPlan'); }

  createDraft(_title: string, _idea: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return pending('ProductionDraftApi.createDraft'); }
  listDrafts(): Promise<AdapterResult<DraftListViewModel[]>> { return pending('ProductionDraftApi.listDrafts'); }
  getDraft(_draftId: string): Promise<AdapterResult<DraftViewModel>> { return pending('ProductionDraftApi.getDraft'); }
  submitIdeaRevision(_draftId: string, _title: string, _idea: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return pending('ProductionDraftApi.submitIdeaRevision'); }
  submitDraft(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return pending('ProductionDraftApi.submitDraft'); }
  archiveDraft(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<DraftViewModel>> { return pending('ProductionDraftApi.archiveDraft'); }
  requestUnderstanding(_draftId: string, _metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return pending('ProductionDraftApi.requestUnderstanding'); }
  getUnderstanding(_draftId: string): Promise<AdapterResult<UnderstandingViewModel>> { return Promise.resolve({ kind: 'not_implemented', message: 'E2 UNDERSTANDING AUTHORITY IS NOT AVAILABLE IN THIS ADAPTER.' }); }
  answerClarification(_draftId: string, _clarificationId: string, _answer: string, _metadata: CommandMetadata): Promise<AdapterResult<UnderstandingViewModel>> { return pending('ProductionDraftApi.answerClarification'); }
}
class PendingPortfolioApi implements ProductionPortfolioApi {
  listProductions(): Promise<AdapterResult<ProductionCardViewModel[]>> { return pending('ProductionPortfolioApi.listProductions'); }
  getProduction(): Promise<AdapterResult<ProductionCardViewModel>> { return pending('ProductionPortfolioApi.getProduction'); }
}
class PendingGateApi implements GateApi {
  listGates(): Promise<AdapterResult<GateViewModel[]>> { return pending('GateApi.listGates'); }
  getGate(): Promise<AdapterResult<import('../models').GateDetailViewModel>> { return pending('GateApi.getGate'); }
  submitDecision(): Promise<AdapterResult<import('../models').GateDecisionReceiptViewModel>> { return pending('GateApi.submitDecision'); }
}
class PendingProductionApi implements ProductionApi {
  getSnapshot(): Promise<AdapterResult<ProductionCardViewModel>> { return pending('ProductionApi.getSnapshot'); }
  getLiveSnapshot(_id: string, _signal?: AbortSignal): Promise<AdapterResult<import('../models').LiveProductionSnapshotViewModel>> { return pending('ProductionApi.getLiveSnapshot'); }
  getLiveEvents(_id: string, _after: number, _limit?: number, _signal?: AbortSignal): Promise<AdapterResult<import('../models').LiveProductionEventFeedViewModel>> { return pending('ProductionApi.getLiveEvents'); }
  getCommandReceipt(): Promise<AdapterResult<import('../models').ProjectCommandReceiptViewModel>> { return pending('ProductionApi.getCommandReceipt'); }
  pause(): Promise<AdapterResult<import('../models').ProjectCommandReceiptViewModel>> { return pending('ProductionApi.pause'); }
  resume(): Promise<AdapterResult<import('../models').ProjectCommandReceiptViewModel>> { return pending('ProductionApi.resume'); }
  stop(): Promise<AdapterResult<import('../models').ProjectCommandReceiptViewModel>> { return pending('ProductionApi.stop'); }
}
class PendingWorkerControlPlaneApi implements WorkerControlPlaneApi {
  listWorkers(): Promise<AdapterResult<import('../models').WorkerFleetItemViewModel[]>> { return pending('WorkerControlPlaneApi.listWorkers'); }
  getWorker(_workerId: string): Promise<AdapterResult<import('../models').WorkerDetailViewModel>> { return pending('WorkerControlPlaneApi.getWorker'); }
  getExecutionQueue(): Promise<AdapterResult<import('../models').ExecutionQueueItemViewModel[]>> { return pending('WorkerControlPlaneApi.getExecutionQueue'); }
}
export const authorityPendingAdapters = (): FactoryAdapters => ({ mode: 'authority_pending', draft: new PendingDraftApi(), portfolio: new PendingPortfolioApi(), gates: new PendingGateApi(), production: new PendingProductionApi(), workers: new PendingWorkerControlPlaneApi() });
