const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto, createHash } = require('node:crypto');
const rootPath = path.resolve(__dirname, '../..');
const read = (name) => fs.readFileSync(path.join(rootPath, name), 'utf8');
const CLIENT = 'a'.repeat(32), BASE = 'http://127.0.0.1:8000';
const flush = () => new Promise(setImmediate);
async function until(fn) { for (let i = 0; i < 100; i++) { if (fn()) return; await new Promise(r => setTimeout(r, 2)); } assert.fail('Expected asynchronous operation did not occur'); }
const data = (handle = 'viewedB') => ({
  summary: { handle, rating: 1200, max_rating: 1300, rank: 'pupil', max_rank: 'pupil', rated_contests: 3, unique_solved: 2, total_submissions: 5, judged_submissions: 4, pending_submissions: 1, acceptance_rate: 50 },
  history: { complete: true, note: 'Complete returned history.' }, solved_by_rating: [{ rating: 800, count: 2 }], unrated_solved: 0,
  topics: [{ tag: 'math', attempted: 3, solved: 2, solve_rate: 66.7 }], strong_topics: [], weak_topics: [], focus_topics: [], verdicts: [{ verdict: 'OK', count: 2, percentage: 50 }], patterns: [],
  methodology: { weakness_score: 'Minimum 5 distinct problems and 8 judged submissions.' }, rating: { actual: [1000, 1100, 1200], trend: [1000, 1100, 1200], estimate: [1300, 1400], recent_change: 200, recent_contests: 2 },
  practice: { problems: [{ name: 'Practice', rating: 1200, tags: ['math'], url: 'https://codeforces.com/problemset/problem/2/A', reason: 'Unseen and in range.' }], note: 'Deterministic ranking.' }
});
function harness({ pathname = '/profile/viewedB', store = {}, content = true, callbackState = null } = {}) {
  let host = null, interval = null, listener;
  const requests = [], replies = [], storage = structuredClone(store), accessLevels = [];
  const local = {
    async setAccessLevel(option) { accessLevels.push(option.accessLevel); },
    async get(keys) { if (typeof keys === 'string') return { [keys]: storage[keys] }; if (Array.isArray(keys)) return Object.fromEntries(keys.map(k => [k, storage[k]])); return { ...keys, ...Object.fromEntries(Object.keys(keys || storage).filter(k => k in storage).map(k => [k, storage[k]])) }; },
    async set(value) { Object.assign(storage, structuredClone(value)); }, async remove(keys) { for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key]; }
  };
  function fakeRoot() {
    const nodes = new Map(), arrays = new Map(); let html = '', revision = 0;
    const allHtml = () => html + [...nodes.values()].map(n => n.innerHTML).join('');
    function element(selector, opening = '') {
      const result = { value: '', checked: false, disabled: /\sdisabled\b/.test(opening), hidden: /\shidden\b/.test(opening), textContent: '', attributes: {}, listeners: {}, dataset: { id: opening.match(/data-id="([^"]+)"/)?.[1] },
        setAttribute(k, v) { this.attributes[k] = v; }, addEventListener(type, fn) { this.listeners[type] = fn; }, focus() { this.focused = true; },
        fire(type, event = {}) { return this.listeners[type]?.({ preventDefault() {}, ...event }); }, click() { if (!this.disabled) this.fire('click'); } };
      let inner = '';
      Object.defineProperty(result, 'innerHTML', { get: () => inner, set(value) { inner = value; revision++; } });
      return result;
    }
    function openings(selector) {
      const name = selector.slice(1).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return [...allHtml().matchAll(new RegExp('<[^>]+class="[^"<>]*\\b' + name + '\\b[^"<>]*"[^>]*>', 'g'))].map(m => m[0]);
    }
    return {
      get innerHTML() { return html; }, set innerHTML(value) { html = value; nodes.clear(); arrays.clear(); revision++; },
      querySelector(selector) { if (nodes.has(selector)) return nodes.get(selector); const opening = openings(selector)[0]; if (!opening) return null; const node = element(selector, opening); nodes.set(selector, node); return node; },
      querySelectorAll(selector) { const cache = arrays.get(selector); if (cache?.revision === revision) return cache.nodes; const found = openings(selector).map(o => element(selector, o)); arrays.set(selector, { revision, nodes: found }); return found; }
    };
  }
  const document = { body: { appendChild(el) { host = el; } }, querySelector(selector) { return selector === '#cp-assistant-profile-host' ? host : null; }, createElement() {
    const el = { remove() { if (host === el) host = null; }, attachShadow() { this.shadow = fakeRoot(); return this.shadow; } }; return el;
  } };
  const location = { protocol: 'https:', hostname: 'codeforces.com', pathname, href: 'https://codeforces.com' + pathname };
  const chrome = { storage: { local }, runtime: { id: CLIENT, getURL: p => `chrome-extension://${CLIENT}/${p}`, onMessage: { addListener(fn) { listener = fn; } }, sendMessage(message, callback) {
    listener(message, { id: CLIENT, frameId: 0, url: location.href, tab: { id: 1 } }, reply => { replies.push(reply); callback?.(reply); });
  } }, identity: { getRedirectURL: p => `https://${CLIENT}.chromiumapp.org/${p}`, async launchWebAuthFlow() {
    const initial = JSON.parse(requests.find(r => r.url.endsWith('/auth/start/')).options.body);
    return `https://${CLIENT}.chromiumapp.org/callback?` + new URLSearchParams({ state: callbackState || initial.state, request_id: 'flow-id', code: 'single-use-code' });
  } } };
  const common = { console, URL, URLSearchParams, AbortController, TextEncoder, Uint8Array, crypto: webcrypto, btoa, chrome,
    setTimeout(fn, ms) { const timer = setTimeout(fn, ms); timer.unref(); return timer; }, clearTimeout,
    fetch(url, options) { return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject, done: false })); } };
  let worker;
  function restartWorker() {
    worker = vm.createContext({ ...common });
    vm.runInContext(read('extension/shared/api.js'), worker);
    vm.runInContext(read('extension/background/service-worker.js').replace("import '../shared/api.js';", ''), worker);
  }
  restartWorker();
  if (content) vm.runInNewContext(read('extension/content/codeforces-profile.js'), { chrome, document, URL, window: { location, addEventListener() {}, setInterval(fn) { interval = fn; }, confirm: () => true } });
  function respond(request, body, status = 200) { request.done = true; request.resolve({ ok: status >= 200 && status < 300, status, json: async () => body }); }
  return { requests, replies, storage, accessLevels, chrome, restartWorker, respond,
    get html() { return host?.shadow.innerHTML || ''; }, node: s => host?.shadow.querySelector(s), nodes: s => host?.shadow.querySelectorAll(s),
    get api() { return worker.CPAssistantApi; },
    navigate(p) { location.pathname = p; location.href = 'https://codeforces.com' + p; interval?.(); },
    pending(part) { return requests.find(r => !r.done && r.url.includes(part)); },
    async reply(part, body, status = 200) { await until(() => this.pending(part)); respond(this.pending(part), body, status); await flush(); },
    dispatch(message, sender) { return new Promise(resolve => { const result = listener(message, sender || { id: CLIENT, frameId: 0, url: location.href, tab: { id: 1 } }, resolve); if (!result) resolve({ refused: true }); }); }
  };
}
const authStore = (extra = {}) => ({ authorization: { backendOrigin: BASE, access_token: 'fixture-access', refresh_token: 'fixture-refresh', expires_at: Date.now() + 600000, account: { username: 'ownerA', codeforces_handle: 'viewedB' }, ...extra } });
async function loaded(h) { await h.reply('/analytics/', data()); await flush(); }

test('manifest injects only into profile pages and has no tabs permission', () => {
  const m = JSON.parse(read('extension/manifest.json'));
  assert.deepEqual(m.content_scripts[0].matches, ['https://codeforces.com/profile/*']);
  assert.equal(m.manifest_version, 3); assert.ok(!m.permissions.includes('tabs')); assert.ok(m.permissions.includes('identity'));
  for (const f of [m.background.service_worker, m.action.default_popup, m.options_page, ...m.content_scripts.flatMap(x => x.js)]) assert.ok(fs.existsSync(path.join(rootPath, 'extension', f)));
});
test('public analytics load automatically once, without credentials or AI, and tabs reuse data', async () => {
  const h = harness(); await loaded(h);
  assert.equal(h.requests.length, 1); assert.equal(h.requests[0].options.credentials, 'omit'); assert.equal(h.requests[0].options.headers.Authorization, undefined);
  h.node('.tab-Weaknesses').click(); h.node('.tab-Practice').click(); h.node('.tab-Overview').click(); await flush();
  assert.equal(h.requests.length, 1); assert.match(h.node('.pane-Overview').innerHTML, /Distinct problems solved by rating/);
  for (const tab of ['Weaknesses', 'Practice', 'Notes']) assert.equal(h.node('.tab-' + tab).hidden, true);
  assert.equal(h.node('.pane-Overview').hidden, false);
  assert.equal(h.node('.pane-Practice').innerHTML, '');
  assert.match(h.node('.pane-Overview').innerHTML, /vertical-chart/);
  assert.match(h.node('.pane-Overview').innerHTML, /pie-chart/);
});
test('no injection or fetch on problem/contest pages', async () => {
  for (const pathname of ['/problemset/problem/1/A', '/contest/1/problem/A', '/profile/not/valid']) {
    const h = harness({ pathname }); await flush(); assert.equal(h.html, ''); assert.equal(h.requests.length, 0);
  }
});
test('navigation resets analytics and discards a late old-profile response', async () => {
  const h = harness(); await until(() => h.pending('/analytics/')); const first = h.pending('/analytics/');
  h.navigate('/profile/other'); await until(() => h.requests.length === 2);
  h.respond(first, data('old')); await flush(); assert.doesNotMatch(h.node('.pane-Overview').innerHTML, /old/);
  await h.reply('/profiles/other/', data('other')); assert.match(h.node('.pane-Overview').innerHTML, /other/);
  h.navigate('/problemset/problem/1/A'); assert.equal(h.html, '');
});
test('preferred collapse state restores and changing it sends no analytics request', async () => {
  const h = harness({ store: { panelCollapsed: true } }); await loaded(h);
  assert.equal(h.node('.panel-content').hidden, true); h.node('.collapse').click(); await flush();
  assert.equal(h.storage.panelCollapsed, false); assert.equal(h.requests.length, 1);
});
test('keyboard navigation selects tabs and focuses their controls', async () => {
  const h = harness(); await loaded(h); h.node('.tab-Overview').fire('keydown', { key: 'ArrowRight' });
  assert.equal(h.node('.pane-Overview').hidden, false); assert.equal(h.node('.tab-Overview').focused, true);
  assert.equal(h.node('.pane-Weaknesses').hidden, true);
});
test('public error state offers explicit retry without AI', async () => {
  const h = harness(); await h.reply('/analytics/', { error: 'Rate limit reached' }, 429);
  assert.match(h.node('.load-status').textContent, /Rate limit/); h.node('.retry').click(); await flush();
  assert.equal(h.requests.length, 2); await h.reply('/analytics/', data());
});
test('notes on own profile escape content; no raw credentials reach DOM', async () => {
  const h = harness({ store: authStore() }); await loaded(h); await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  assert.match(h.node('.account-label').textContent, /ownerA.*viewedB/);
  h.node('.tab-Notes').click(); await h.reply('/notes/', { results: [{ id: 1, title: 'Private lesson', content: '<img onerror=alert(1)>', topic: 'dp', updated_at: 'v1' }], count: 1, topics: ['dp'], next_page: null });
  assert.match(h.node('.notes-owner').textContent, /ownerA/); assert.match(h.node('.note-list').innerHTML, /&lt;img/); assert.doesNotMatch(h.node('.note-list').innerHTML, /<img/);
  assert.ok(!JSON.stringify(h.replies).includes('fixture-refresh')); assert.ok(h.accessLevels.includes('TRUSTED_CONTEXTS'));
});
test('notes create/edit/delete/search use controlled messages and authenticated API routes', async () => {
  const h = harness({ store: authStore() }); await loaded(h); await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  h.node('.tab-Notes').click(); await h.reply('/notes/', { results: [], count: 0, topics: [], next_page: null });
  h.node('.note-title').value = 'DP'; h.node('.note-content').value = 'Memoization'; h.node('.note-form').fire('submit');
  await until(() => h.pending('/notes/')); const create = h.pending('/notes/'); assert.equal(create.options.method, 'POST'); assert.equal(JSON.parse(create.options.body).title, 'DP');
  h.respond(create, { id: 1 }); await h.reply('/notes/', { results: [{ id: 1, title: 'DP', content: 'Memoization', topic: '', updated_at: 'v1' }], count: 1, topics: [], next_page: null });
  h.nodes('.edit-note')[0].click(); h.node('.note-content').value = 'Tabulation'; h.node('.note-form').fire('submit'); await until(() => h.pending('/notes/1/'));
  assert.equal(h.pending('/notes/1/').options.method, 'PUT'); h.respond(h.pending('/notes/1/'), { id: 1 });
  await h.reply('/notes/', { results: [{ id: 1, title: 'DP', content: 'Tabulation', topic: '', updated_at: 'v2' }], count: 1, topics: [], next_page: null });
  h.nodes('.delete-note')[0].click(); await until(() => h.pending('/notes/1/')); assert.equal(h.pending('/notes/1/').options.method, 'DELETE'); h.respond(h.pending('/notes/1/'), { deleted: true });
  await h.reply('/notes/', { results: [], count: 0, topics: [], next_page: null });
  h.node('.note-search').value = 'prefix'; h.node('.note-filter').fire('submit'); await until(() => h.pending('q=prefix')); assert.ok(h.pending('q=prefix'));
});
test('AI runs only after explicit click, blocks simultaneous clicks, and escapes output', async () => {
  const h = harness({ store: authStore() }); await loaded(h); await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  h.node('.tab-Practice').click(); await flush(); assert.equal(h.requests.filter(r => r.url.includes('improvement-plan')).length, 0);
  h.node('.generate-plan').click(); h.node('.generate-plan').click(); await until(() => h.pending('improvement-plan'));
  assert.equal(h.requests.filter(r => r.url.includes('improvement-plan')).length, 1);
  await h.reply('improvement-plan', { plan: { major_areas: ['<script>x</script>'], topics_to_learn: ['dp'], learning_order: [], practice_strategy: 'Practise', supported_patterns: [], short_term_plan: [{ day: 'Day 1', task: 'Try a problem' }] } });
  assert.match(h.node('.plan-result').innerHTML, /&lt;script/); assert.doesNotMatch(h.node('.plan-result').innerHTML, /<script>/);
});
test('PKCE connection checks callback and returns account only to content', async () => {
  const h = harness({ content: false }); const pending = h.dispatch({ type: 'CONNECT_ACCOUNT' });
  await until(() => h.pending('/auth/start/')); const initial = JSON.parse(h.pending('/auth/start/').options.body);
  assert.match(initial.state, /^[A-Za-z0-9_-]{43}$/); assert.equal(initial.code_challenge_method, 'S256');
  await h.reply('/auth/start/', { request_id: 'flow-id', authorization_url: BASE + '/extension/authorize/flow-id/' });
  await until(() => h.pending('/auth/exchange/')); const proof = JSON.parse(h.pending('/auth/exchange/').options.body);
  assert.equal(createHash('sha256').update(proof.code_verifier).digest('base64url'), initial.code_challenge);
  await h.reply('/auth/exchange/', { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 600, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  const reply = await pending; assert.equal(reply.result.account.username, 'ownerA'); assert.ok(!JSON.stringify(reply).includes('new-refresh'));
  assert.equal(h.storage.pendingConnection, undefined);
});
test('state mismatch fails closed without exchanging credentials', async () => {
  const h = harness({ content: false, callbackState: 'wrong' }); const pending = h.api.connect();
  const rejected = assert.rejects(pending, /Connection cancelled/);
  await h.reply('/auth/start/', { request_id: 'flow-id', authorization_url: BASE + '/extension/authorize/flow-id/' });
  await rejected; assert.equal(h.requests.length, 1); assert.equal(h.storage.authorization, undefined);
});
test('valid authorization survives worker restart without interactive connection', async () => {
  const h = harness({ content: false, store: authStore() }); h.restartWorker(); const status = h.api.status();
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } }); assert.equal((await status).authenticated, true);
  assert.equal(h.requests.length, 1);
});
test('expired access rotates refresh once for simultaneous operations', async () => {
  const h = harness({ content: false, store: authStore({ expires_at: 0 }) }); const a = h.api.status(), b = h.api.status();
  await h.reply('/auth/refresh/', { access_token: 'rotated-access', refresh_token: 'rotated-refresh', expires_in: 600, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } }); await Promise.all([a, b]);
  assert.equal(h.requests.filter(r => r.url.includes('/auth/refresh/')).length, 1); assert.equal(h.storage.authorization.refresh_token, 'rotated-refresh');
});
test('revoked refresh clears credentials; backend change never forwards old tokens', async () => {
  const h = harness({ content: false, store: authStore({ expires_at: 0 }) }); const status = h.api.status();
  await h.reply('/auth/refresh/', { error: 'Revoked' }, 401); assert.equal((await status).authenticated, false); assert.equal(h.storage.authorization, undefined);
  const switched = harness({ content: false, store: { ...authStore(), backendUrl: 'https://new.example' } });
  assert.equal((await switched.api.status()).authenticated, false); assert.equal(switched.requests.length, 0);
});
test('untrusted messages and problem-page messages are rejected', async () => {
  const h = harness({ content: false });
  assert.equal((await h.dispatch({ type: 'GET_NOTES' }, { id: 'other', url: 'https://codeforces.com/profile/x', frameId: 0 })).refused, true);
  assert.equal((await h.dispatch({ type: 'GET_PROFILE' }, { id: CLIENT, url: 'https://codeforces.com/problemset/problem/1/A', frameId: 0 })).refused, true);
  assert.equal(h.requests.length, 0);
});

test('anonymous Notes and Register never block public analytics or fetch private data', async () => {
  const h = harness(); await loaded(h); h.node('.tab-Notes').click(); await flush();
  assert.equal(h.requests.length, 1); assert.match(h.node('.notes-owner').textContent, /Connect your Django account/);
  assert.equal(h.node('.register').href, BASE + '/register/'); assert.equal(h.node('.register').hidden, false);
});
test('disconnect revokes remotely and clears local credentials', async () => {
  const h = harness({ content: false, store: authStore() }); const pending = h.api.disconnect();
  await h.reply('/auth/revoke/', { revoked: true }); assert.equal((await pending).revoked, true); assert.equal(h.storage.authorization, undefined);
});
test('AI limit errors remain actionable and never retry automatically', async () => {
  const h = harness({ store: authStore() }); await loaded(h); await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  h.node('.tab-Practice').click(); h.node('.generate-plan').click(); await h.reply('improvement-plan', { error: 'Three attempts per hour. Retry later.' }, 429);
  assert.match(h.node('.plan-status').textContent, /Three attempts/); assert.equal(h.requests.filter(r => r.url.includes('improvement-plan')).length, 1);
});

test('connected public profiles expose only Overview and never fetch personal tools', async () => {
  const h = harness({ store: authStore() }); await loaded(h);
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'someoneElse' } });
  for (const tab of ['Weaknesses', 'Practice', 'Notes']) {
    assert.equal(h.node('.tab-' + tab).hidden, true);
    h.node('.tab-' + tab).click();
    assert.equal(h.node('.pane-' + tab).hidden, true);
  }
  h.node('.note-filter').fire('submit'); h.node('.note-form').fire('submit'); await flush();
  assert.equal(h.requests.length, 2); assert.match(h.node('.own-notice').innerHTML, /Open your linked profile/);
  assert.equal(h.node('.pane-Overview').hidden, false);
});

test('own-profile tabs match saved handle case-insensitively and support keyboard selection', async () => {
  const h = harness({ store: authStore() }); await loaded(h);
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'VIEWEDb' } });
  for (const tab of ['Weaknesses', 'Practice', 'Notes']) assert.equal(h.node('.tab-' + tab).hidden, false);
  h.node('.tab-Overview').fire('keydown', { key: 'ArrowRight' });
  assert.equal(h.node('.pane-Weaknesses').hidden, false); assert.equal(h.node('.tab-Weaknesses').focused, true);
  h.node('.tab-Practice').click(); assert.match(h.node('.pane-Practice').innerHTML, /Generate AI Improvement Plan/);
  assert.equal(h.requests.length, 2);
});

test('an unlinked connected account keeps private tabs hidden and offers profile settings', async () => {
  const h = harness({ store: authStore() }); await loaded(h);
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: null } });
  assert.equal(h.node('.tab-Notes').hidden, true); assert.match(h.node('.own-notice').innerHTML, /profile\/update/);
});

test('own-to-other navigation hides personal tools and discards a pending notebook response', async () => {
  const h = harness({ store: authStore() }); await loaded(h);
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  h.node('.tab-Notes').click(); await until(() => h.pending('/notes/')); const pending = h.pending('/notes/');
  h.navigate('/profile/other');
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  await h.reply('/profiles/other/', data('other'));
  h.respond(pending, { results: [{ id: 1, title: 'Old private note', content: 'Secret', topic: '', updated_at: 'v1' }], topics: [], count: 1 });
  await flush(); assert.equal(h.node('.tab-Notes').hidden, true);
  assert.equal(h.node('.note-list').innerHTML, ''); assert.equal(h.node('.pane-Overview').hidden, false);
});

test('disconnect clears private panes and discards a pending AI response', async () => {
  const h = harness({ store: authStore() }); await loaded(h);
  await h.reply('/auth/status/', { authenticated: true, account: { username: 'ownerA', codeforces_handle: 'viewedB' } });
  h.node('.tab-Practice').click(); h.node('.generate-plan').click(); await until(() => h.pending('improvement-plan'));
  const pending = h.pending('improvement-plan'); h.node('.disconnect').click(); await h.reply('/auth/revoke/', { revoked: true });
  h.respond(pending, { plan: { major_areas: ['Late advice'], topics_to_learn: [], learning_order: [], practice_strategy: '', supported_patterns: [], short_term_plan: [] } });
  await flush(); assert.equal(h.node('.tab-Practice').hidden, true); assert.equal(h.node('.pane-Practice').innerHTML, '');
  assert.equal(h.node('.pane-Overview').hidden, false);
});

test('overview charts handle empty, unrated, multiple and unsafe topic labels', async () => {
  const empty = harness(); const p = data(); p.solved_by_rating = []; p.topics = []; p.rating.actual = [];
  await empty.reply('/analytics/', p);
  assert.match(empty.node('.pane-Overview').innerHTML, /No accepted problems yet/);
  assert.match(empty.node('.pane-Overview').innerHTML, /No solved-topic data/);
  assert.match(empty.node('.pane-Overview').innerHTML, /No rated contests/);
  const h = harness(); const many = data(); many.unrated_solved = 1;
  many.topics = Array.from({ length: 10 }, (_, i) => ({ tag: i ? 'topic' + i : '<img onerror=alert(1)>', solved: 10 - i, attempted: 12, solve_rate: 50 }));
  await h.reply('/analytics/', many); const html = h.node('.pane-Overview').innerHTML;
  assert.match(html, /<rect class="rating-bar"/); assert.match(html, /Problem rating/); assert.match(html, /Unrated/);
  assert.match(html, /<path d="M 100 100/); assert.match(html, /Other topics/);
  assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img/); assert.doesNotMatch(html, /NaN|Infinity/);
  assert.match(html, /solved-topic assignments/);
});

test('one and two rated contests remain visible without inventing a regression estimate', async () => {
  for (const ratings of [[1000], [1000, 1100]]) {
    const h = harness(); const p = data(); p.rating = { actual: ratings, trend: [], estimate: [], recent_change: ratings.length === 2 ? 100 : 0, recent_contests: ratings.length - 1 };
    await h.reply('/analytics/', p);
    const html = h.node('.pane-Overview').innerHTML;
    assert.match(html, /Contest 1: 1000/); assert.doesNotMatch(html, /NaN|Infinity/);
    if (ratings.length === 2) assert.match(html, /Contest 2: 1100/);
  }
});
