import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { AdapterResult, ExecutionQueueItemViewModel } from '../models';
import { useUi } from '../ui-context';
import { Icon, StatusBadge, ViewState } from '../design-system';

function useResource<T>(loader: () => Promise<AdapterResult<T>>, deps: readonly unknown[] = []) {
  const [state, setState] = useState<{ phase: 'loading' | 'data' | 'error' | 'unavailable'; value?: T; message?: string }>({ phase: 'loading' });
  const load = useCallback(() => { setState({ phase: 'loading' }); return loader().then((result) => setState(result.kind === 'data' ? { phase: 'data', value: result.value } : { phase: result.kind === 'not_implemented' ? 'unavailable' : 'error', message: result.message })).catch(() => setState({ phase: 'error', message: 'Network request failed.' })); }, deps);
  useEffect(() => { void load(); }, [load]);
  return { ...state, reload: load };
}

export function ExecutionQueue() {
  const { t, formatDate } = useUi();
  const queue = useResource(async () => {
    const adapters = (window as unknown as { __adapters?: { workers?: { getExecutionQueue(): Promise<AdapterResult<ExecutionQueueItemViewModel[]>> } } }).__adapters;
    if (!adapters?.workers) return { kind: 'not_implemented' as const, message: 'Worker control plane is not configured.' };
    return adapters.workers.getExecutionQueue();
  }, []);
  const [filter, setFilter] = useState('');
  const items = (queue.value ?? []).filter((q) => `${q.queueItemId} ${q.executionRequestId ?? ''} ${q.projectId ?? ''} ${q.taskId ?? ''} ${q.workerTemplateId ?? ''}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const body = queue.phase === 'loading' ? <ViewState kind="loading"/> : queue.phase === 'error' ? <ViewState kind="error" title={t('error.UNKNOWN.title')} detail={queue.message} onRetry={() => void queue.reload()}/> : queue.phase === 'unavailable' ? <ViewState kind="unavailable" title={t('error.UNAUTHORIZED.title')} detail={t('error.UNAUTHORIZED.description')}/> : null;
  return <div className="workspace-content"><header className="ui-page-head"><div><span className="ui-kicker">{t('appName')} / {t('workspace')}</span><h1>{t('e14.executionQueue')}</h1><p>{t('e14.executionQueueDetail')}</p></div><div className="ui-actions"><Link className="ui-button secondary" to="/workers"><Icon name="arrow"/>{t('e14.workerFleet')}</Link></div></header><label className="ui-field"><span>Queue / Project / Task filter</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="queue item or execution request id"/></label>{body ?? (items.length ? <div className="ui-table-wrap"><table className="ui-table"><thead><tr><th>{t('e14.queueState')}</th><th>{t('e14.requestState')}</th><th>{t('e14.priority')}</th><th>{t('task')}</th><th>{t('e14.template')}</th><th>{t('e14.availableAt')}</th><th>{t('e14.enqueuedAt')}</th><th/></tr></thead><tbody>{items.map((item) => <tr key={item.queueItemId}><td><StatusBadge value={item.queueState ?? 'NOT_AVAILABLE'}/></td><td><StatusBadge value={item.requestState ?? 'NOT_AVAILABLE'}/></td><td>{item.priority ?? '—'}</td><td>{item.taskId ?? '—'}</td><td className="ui-kicker">{item.workerTemplateId ?? '—'}</td><td>{item.availableAt ? formatDate(item.availableAt) : '—'}</td><td>{item.enqueuedAt ? formatDate(item.enqueuedAt) : '—'}</td><td>{item.currentLeaseId ? <StatusBadge value="LEASED"/> : null}</td></tr>)}</tbody></table></div> : <ViewState kind="empty"/>)}</div>;
}
