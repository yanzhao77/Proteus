export type SessionProfile = {
  authenticated: true;
  subject: string;
  issuer: string;
  expiresAt: number;
};
export type SessionResult = { kind: 'data'; value: SessionProfile } | { kind: 'unauthenticated'; message: string } | { kind: 'error'; message: string };

const apiBase = import.meta.env.VITE_PROTEUS_API_BASE ?? '';
export async function readSession(): Promise<SessionResult> {
  try {
    const response = await fetch(`${apiBase}/session`, { headers: { Accept: 'application/json' }, credentials: 'include' });
    if (response.status === 401) return { kind: 'unauthenticated', message: 'Session required.' };
    const envelope = await response.json() as { data?: Record<string, unknown>; error?: { message?: string } };
    if (!response.ok || !envelope.data) return { kind: 'error', message: envelope.error?.message ?? 'Session unavailable.' };
    const data = envelope.data;
    if (data.authenticated !== true || typeof data.subject !== 'string' || typeof data.issuer !== 'string' || typeof data.expires_at !== 'number') return { kind: 'error', message: 'Session profile is invalid.' };
    return { kind: 'data', value: { authenticated: true, subject: data.subject, issuer: data.issuer, expiresAt: data.expires_at } };
  } catch { return { kind: 'error', message: 'Session service unavailable.' }; }
}
export async function endSession(): Promise<boolean> {
  try { return (await fetch(`${apiBase}/session`, { method: 'DELETE', credentials: 'include' })).status === 204; } catch { return false; }
}
