import { afterEach, describe, expect, it, vi } from 'vitest';
import { endSession, readSession } from './session';

afterEach(() => vi.unstubAllGlobals());

describe('E10 browser session adapter', () => {
  it('reads only the sanitized profile through an opaque credentialed cookie request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { authenticated: true, subject: 'user-1', issuer: 'https://issuer.invalid', expires_at: 123 }, error: null }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(readSession()).resolves.toEqual({ kind: 'data', value: { authenticated: true, subject: 'user-1', issuer: 'https://issuer.invalid', expiresAt: 123 } });
    expect(fetchMock).toHaveBeenCalledWith('/session', expect.objectContaining({ credentials: 'include' }));
  });
  it('fails closed on unauthenticated and never accepts a browser token argument', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: 'required' } }), { status: 401 })));
    await expect(readSession()).resolves.toEqual({ kind: 'unauthenticated', message: 'Session required.' });
  });
  it('ends the opaque cookie session with DELETE only', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(endSession()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith('/session', { method: 'DELETE', credentials: 'include' });
  });
});
