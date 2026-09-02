import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { AdapterResult, WorkerFleetItemViewModel } from '../models';
import { useUi } from '../ui-context';
import { Icon, StatusBadge, ViewState } from '../design-system';

function useResource<T>(loader: () => Promise<AdapterResult<T>>, deps: readonly unknown[] = []) {
  const [state, setState] = useState<{ phase: 'loading' | 'data' | 'error' | 'unavailable'; value?: T; message?: string }>({ phase: 'loading' });
  const load = useCallback(() => { setState({ phase: 'loading' }); return loader().then((result) => setState(result.kind === 'data' ? { phase: 'data', value: result.value } : { phase: result.kind === 'not_implemented' ? 'unavailable' : 'error', message: result.message })).catch(() => setState({ phase: 'error', message: 'Network request failed.' })); }, deps);
  useEffect(() => { void load(); }, [load]);
  return { ...state, reload: load };
}

export function WorkerFleet() {
  const { t, formatDate } = useUi();
  const workers = useResource(async () => {
    const adapters = (window as unknown as { __adapters?: { workers?: { listWorkers(): Promise<AdapterResult<WorkerFleetItemViewModel[]>> } } }).__adapters;
    if (!adapters?.workers) return { kind: 'not_implemented' as const, message: 'Worker control plane is not configured.' };
    return adapters.workers.listWorkers();
  }, []);
  const [filter, setFilter] = useState('');
  const items = (workers.value ?? []).filter((w) => `${w.workerId} ${w.runtimeKind ?? ''} ${w.trustLevel ?? ''}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const body = workers.phase === 'loading' ? <ViewState kind="loading"/> : workers.phase === 'error' ? <ViewState kind="error" title={t('error.UNKNOWN.title')} detail={workers.message} onRetry={() => void workers.reload()}/> : workers.phase === 'unavailable' ? <ViewState kind="unavailable" title={t('error.UNAUTHORIZED.title')} detail={t('error.UNAUTHORIZED.description')}/> : null;
  return <div className="workspace-content"><header className="ui-page-head"><div><span className="ui-kicker">{t('appName')} / {t('workspace')}</span><h1>{t('e14.workerFleet')}</h1><p>{t('e14.workerFleetDetail')}</p></div><div className="ui-actions"><Link className="ui-button secondary" to="/execution-queue">{t('e14.executionQueue')}<Icon name="arrow"/></Link></div></header><label className="ui-field"><span>Template / Runtime filter</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="worker id or runtime kind"/></label>{body ?? (items.length ? <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t('e14.workerId')}</th><th>{t('e14.runtimeKind')}</th><th>{t('e14.trustLevel')}</th><th>{t('e14.availability')}</th><th>{t('e14.admission')}</th><th>{t('e14.activeAssignments')}</th><th>{t('e14.concurrency')}</th><th/></tr></thead><tbody>{items.map((worker) => <tr key={worker.workerId}><td><Link to={`/workers/${encodeURIComponent(worker.workerId)}`}><strong>{worker.workerId}</strong><br/><span className="ui-kicker">V{worker.revision ?? '—'}</span></Link></td><td>{worker.runtimeKind ?? '—'}</td><td><StatusBadge value={worker.trustLevel ?? 'NOT_AVAILABLE'}/></td><td><StatusBadge value={worker.availabilityStatus ?? 'NOT_AVAILABLE'}/></td><td><StatusBadge value={worker.admissionStatus ?? 'NOT_AVAILABLE'}/></td><td>{worker.activeAssignments ?? 0} / {worker.totalAssignments ?? 0}</td><td>{worker.concurrencyCapacity ?? '—'}</td><td><Link className="ui-button secondary" to={`/workers/${encodeURIComponent(worker.workerId)}`}>{t('open')}</Link></td></tr>)}</tbody></table></div> : <ViewState kind="empty"/>)}</div>;
}
