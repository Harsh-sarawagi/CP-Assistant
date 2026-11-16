/* Loaded only by the trusted background worker, never the content script. */
(function createClient() {
  const defaultBackendUrl = 'http://127.0.0.1:8000';
  const ready = chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
  let refreshPromise = null, connectionPromise = null;
  function backendOrigin(value) {
    const url = new URL(value);
    if (url.username || url.password || (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)))) throw new Error('Use HTTPS, or HTTP on localhost for development.');
    return url.origin;
  }
  async function getBackendUrl() {
    await ready;
    return backendOrigin((await chrome.storage.local.get({ backendUrl: defaultBackendUrl })).backendUrl);
  }
  async function request(path, options = {}, expectedBackend = null) {
    const backend = await getBackendUrl(), controller = new AbortController();
    if (expectedBackend && backend !== expectedBackend) throw new Error('Backend changed. Reconnect your account.');
    const timer = setTimeout(() => controller.abort(), path.includes('improvement-plan') ? 90000 : 45000);
    try {
      const response = await fetch(backend + path, { ...options, credentials: 'omit', redirect: 'error', signal: controller.signal,
        headers: { Accept: 'application/json', ...options.headers } });
      let data;
      try { data = await response.json(); } catch { throw new Error('The backend returned an unreadable response.'); }
      if (!response.ok) { const error = new Error(data.error || `Backend returned HTTP ${response.status}`); error.status = response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Request timed out. Retry when ready.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  const post = (path, data, backend = null) => request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }, backend);
  async function stored() {
    await ready;
    const auth = (await chrome.storage.local.get('authorization')).authorization;
    if (auth && auth.backendOrigin !== await getBackendUrl()) { await chrome.storage.local.remove('authorization'); return null; }
    return auth || null;
  }
  async function saveAuthorization(data, backend) {
    if (!data.access_token || !data.refresh_token || !data.account?.username) throw new Error('Invalid authorization response.');
    if (backend !== await getBackendUrl()) throw new Error('Backend changed. Reconnect your account.');
    const auth = { ...data, backendOrigin: backend, expires_at: Date.now() + data.expires_in * 1000 };
    await chrome.storage.local.set({ authorization: auth });
    return auth;
  }
  async function refresh() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      const auth = await stored(); if (!auth) return null;
      try { return await saveAuthorization(await post('/api/extension/auth/refresh/', { client_id: chrome.runtime.id, refresh_token: auth.refresh_token }, auth.backendOrigin), auth.backendOrigin); }
      catch (error) { if ([400, 401, 403].includes(error.status)) await chrome.storage.local.remove('authorization'); throw error; }
    })();
    try { return await refreshPromise; } finally { refreshPromise = null; }
  }
  async function authorized(path, options = {}) {
    let auth = await stored();
    if (!auth) throw new Error('Connect your Django account to use this feature.');
    if (auth.expires_at <= Date.now() + 30000) auth = await refresh();
    if (!auth) throw new Error('Reconnect your account.');
    const send = (token) => request(path, { ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` } }, auth.backendOrigin);
    try { return await send(auth.access_token); }
    catch (error) {
      if (error.status !== 401) throw error;
      auth = await refresh();
      try { return await send(auth.access_token); }
      catch (last) { if (last.status === 401) await chrome.storage.local.remove('authorization'); throw last; }
    }
  }
  async function status() {
    if (!await stored()) return { authenticated: false };
    try { return await authorized('/api/extension/auth/status/'); }
    catch (error) { return { authenticated: false, error: 'Connection unavailable or expired. Retry or reconnect.' }; }
  }
  function random(size) { return btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(size)))).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', ''); }
  async function connect() {
    if (connectionPromise) return connectionPromise;
    connectionPromise = (async () => {
      const expectedBackend = await getBackendUrl();
      const verifier = random(64), state = random(32), redirect = chrome.identity.getRedirectURL('callback');
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
      const proof = btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
      const begin = await post('/api/extension/auth/start/', { client_id: chrome.runtime.id, state, code_challenge: proof, code_challenge_method: 'S256', redirect_uri: redirect }, expectedBackend);
      if (new URL(begin.authorization_url).origin !== expectedBackend) throw new Error('Unexpected authorization destination.');
      await chrome.storage.local.set({ pendingConnection: { state, verifier, requestId: begin.request_id } });
      try {
        const returned = await chrome.identity.launchWebAuthFlow({ url: begin.authorization_url, interactive: true });
        const url = new URL(returned), expected = new URL(redirect);
        if (url.origin !== expected.origin || url.pathname !== expected.pathname || url.searchParams.get('state') !== state || url.searchParams.get('request_id') !== begin.request_id || !url.searchParams.get('code')) throw new Error('Authorization callback did not match.');
        // Credentials never leave this worker or appear in the profile page DOM.
        await saveAuthorization(await post('/api/extension/auth/exchange/', { client_id: chrome.runtime.id, request_id: begin.request_id, state, code: url.searchParams.get('code'), code_verifier: verifier }, expectedBackend), expectedBackend);
        return await status();
      } catch { throw new Error('Connection cancelled or could not be completed. Start Connect Account again.'); }
      finally { await chrome.storage.local.remove('pendingConnection'); }
    })();
    try { return await connectionPromise; } finally { connectionPromise = null; }
  }
  async function disconnect() {
    let confirmed = false;
    try { await authorized('/api/extension/auth/revoke/', { method: 'POST' }); confirmed = true; }
    catch { /* Clear local access even if remote revocation cannot be confirmed. */ }
    finally { await chrome.storage.local.remove(['authorization', 'pendingConnection']); }
    return { authenticated: false, revoked: confirmed };
  }
  globalThis.CPAssistantApi = {
    getBackendUrl, status, connect, disconnect,
    getSettings: async () => { await ready; return { backendUrl: await getBackendUrl(), collapsed: Boolean((await chrome.storage.local.get('panelCollapsed')).panelCollapsed), clientId: chrome.runtime.id }; },
    setCollapsed: async (collapsed) => { await ready; await chrome.storage.local.set({ panelCollapsed: Boolean(collapsed) }); return { saved: true }; },
    publicProfile: (handle) => request(`/api/profiles/${encodeURIComponent(handle)}/analytics/`),
    notes: (query) => authorized('/api/extension/notes/?' + new URLSearchParams(query)),
    saveNote: (payload, id) => authorized(`/api/extension/notes/${id ? id + '/' : ''}`, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
    deleteNote: (id, updated_at) => authorized(`/api/extension/notes/${id}/`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ updated_at }) }),
    plan: (handle) => authorized('/api/extension/improvement-plan/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ handle }) }),
    clearConnection: async () => { await ready; await chrome.storage.local.remove(['authorization', 'pendingConnection']); return { saved: true }; }
  };
})();
