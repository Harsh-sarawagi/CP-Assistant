(function profileAssistant() {
  const handleFromLocation = () => {
    const match = window.location.pathname.match(/^\/profile\/([A-Za-z0-9_.-]{1,24})\/?$/);
    return window.location.protocol === 'https:' && window.location.hostname === 'codeforces.com' && match ? match[1] : null;
  };
  if (!handleFromLocation()) return;
  let current = null, generation = 0, state = null, root = null;
  const tabs = ['Overview', 'Weaknesses', 'Practice', 'Notes'];
  function ownProfile() {
    const linked = state?.account?.codeforces_handle?.trim().toLowerCase();
    return Boolean(linked && [current?.toLowerCase(), state?.analytics?.summary?.handle?.toLowerCase()].includes(linked));
  }
  function send(type, extra, callback) {
    chrome.runtime.sendMessage({ type, ...extra }, (reply) => {
      const error = chrome.runtime.lastError;
      callback(error ? { error: 'Extension connection lost. Reload the page.' } : reply || { error: 'No response from extension.' });
    });
  }
  const escape = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const metric = (label, value) => `<div class="metric"><span>${label}</span><strong>${escape(value ?? 'Unrated')}</strong></div>`;
  const list = (items, empty) => items?.length ? `<ul>${items.map(x => `<li>${escape(x)}</li>`).join('')}</ul>` : `<p class="muted">${escape(empty)}</p>`;
  function live(version) { syncProfile(); return generation === version && Boolean(root); }
  function syncProfile() {
    const handle = handleFromLocation(); if (handle === current) return;
    current = handle; generation++;
    document.querySelector('#cp-assistant-profile-host')?.remove(); root = null;
    if (!handle) return;
    const version = generation;
    state = { tab: 'Overview', account: null, accountEpoch: 0, analytics: null, loading: false, connecting: false, planBusy: false, noteBusy: false, notesLoaded: false, notes: [], page: 1, editing: null, backend: null, collapsed: false };
    const host = document.createElement('div'); host.id = 'cp-assistant-profile-host'; root = host.attachShadow({ mode: 'closed' });
    const anchor = document.querySelector('.userbox');
    if (anchor) anchor.insertAdjacentElement('afterend', host); else (document.querySelector('#pageContent') || document.body).appendChild(host);
    root.innerHTML = styles() + `<section class="panel" aria-label="CP Assistant profile analytics">
      <header><div><strong>CP Assistant</strong><span class="viewed">Public profile: ${escape(handle)}</span></div><button class="collapse" aria-expanded="true" type="button">Collapse</button></header>
      <div class="account"><span class="account-label">Public analytics · no login required</span><button class="connect" type="button">Connect Account</button><a class="register" hidden target="_blank" rel="noopener noreferrer">Register</a><button class="disconnect" hidden type="button">Disconnect</button></div>
      <p class="account-status" role="status" aria-live="polite"></p><p class="own-notice"></p><div class="panel-content">
      <nav role="tablist" aria-label="Profile tools">${tabs.map((tab, i) => `<button class="tab-${tab}" id="cpa-tab-${tab}-${version}" role="tab" aria-controls="cpa-pane-${tab}-${version}" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}" type="button" ${i ? 'hidden' : ''}>${tab}</button>`).join('')}</nav>
      ${tabs.map((tab, i) => `<section class="pane-${tab}" id="cpa-pane-${tab}-${version}" role="tabpanel" tabindex="0" aria-labelledby="cpa-tab-${tab}-${version}" ${i ? 'hidden' : ''}>${tab === 'Notes' ? noteShell() : '<p class="muted">Loading public analytics...</p>'}</section>`).join('')}
      <p class="load-status" role="status" aria-live="polite"></p><button class="retry" type="button" hidden>Retry public analytics</button></div></section>`;
    root.querySelector('.collapse').addEventListener('click', () => { state.collapsed = !state.collapsed; collapse(); send('SET_COLLAPSED', { collapsed: state.collapsed }, () => {}); });
    for (const tab of tabs) {
      root.querySelector('.tab-' + tab).addEventListener('click', () => selectTab(tab));
      root.querySelector('.tab-' + tab).addEventListener('keydown', (event) => {
        const available = ownProfile() ? tabs : ['Overview'];
        let index = available.indexOf(tab);
        if (event.key === 'ArrowRight') index = (index + 1) % available.length;
        else if (event.key === 'ArrowLeft') index = (index + available.length - 1) % available.length;
        else if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = available.length - 1;
        else return;
        event.preventDefault(); selectTab(available[index]); root.querySelector('.tab-' + available[index]).focus();
      });
    }
    root.querySelector('.connect').addEventListener('click', connect);
    root.querySelector('.disconnect').addEventListener('click', () => {
      if (state.connecting) return;
      state.accountEpoch++;
      state.connecting = true; root.querySelector('.disconnect').disabled = true;
      send('DISCONNECT_ACCOUNT', {}, (reply) => { if (!live(version)) return; state.connecting = false; setAccount(null); root.querySelector('.account-status').textContent = reply.result?.revoked ? 'Disconnected and revoked.' : 'Disconnected locally. If revocation was not confirmed, revoke it on the website.'; });
    });
    root.querySelector('.retry').addEventListener('click', loadProfile);
    bindNotes(version);
    send('GET_SETTINGS', {}, (reply) => {
      if (!live(version) || !reply.result) return;
      state.collapsed = reply.result.collapsed; state.backend = reply.result.backendUrl;
      root.querySelector('.register').href = state.backend + '/register/'; root.querySelector('.register').hidden = Boolean(state.account); collapse();
      updateTabs();
    });
    const statusEpoch = state.accountEpoch;
    send('AUTH_STATUS', {}, (reply) => { if (live(version) && state.accountEpoch === statusEpoch) { setAccount(reply.result?.authenticated ? reply.result.account : null); if (reply.result?.error) root.querySelector('.account-status').textContent = reply.result.error; } });
    loadProfile();
  }
  function collapse() {
    root.querySelector('.panel-content').hidden = state.collapsed;
    root.querySelector('.collapse').textContent = state.collapsed ? 'Expand' : 'Collapse';
    root.querySelector('.collapse').setAttribute('aria-expanded', String(!state.collapsed));
  }
  function selectTab(tab) {
    if (tab !== 'Overview' && !ownProfile()) tab = 'Overview';
    state.tab = tab;
    for (const name of tabs) { root.querySelector('.pane-' + name).hidden = name !== tab; root.querySelector('.tab-' + name).setAttribute('aria-selected', String(name === tab)); root.querySelector('.tab-' + name).setAttribute('tabindex', name === tab ? '0' : '-1'); }
    if (tab === 'Notes' && ownProfile() && !state.notesLoaded && !state.noteBusy) loadNotes();
  }
  function updateTabs() {
    const own = ownProfile();
    for (const tab of tabs) root.querySelector('.tab-' + tab).hidden = tab !== 'Overview' && !own;
    if (!own && state.tab !== 'Overview') selectTab('Overview');
    root.querySelector('.own-notice').innerHTML = own ? '<span class="workspace-badge">Your workspace</span> Personal tools are available on your linked profile.' : state.account?.codeforces_handle ? `Public overview only. <a href="https://codeforces.com/profile/${encodeURIComponent(state.account.codeforces_handle)}">Open your linked profile</a> for personal tools.` : state.account && state.backend ? `Link your Codeforces handle in <a href="${escape(state.backend)}/profile/update/" target="_blank" rel="noopener noreferrer">profile settings</a> to show your personal tabs.` : 'Public overview. Connect your account to unlock personal tools on your linked profile.';
  }
  function setAccount(account) {
    const changed = state.account?.username !== account?.username || state.account?.codeforces_handle !== account?.codeforces_handle;
    if (changed) state.accountEpoch++;
    state.account = account;
    root.querySelector('.account-label').textContent = account ? `Connected Django account: ${account.username} · Viewing public profile: ${current}` : 'Public analytics · no login required';
    root.querySelector('.connect').hidden = Boolean(account); root.querySelector('.connect').disabled = false;
    root.querySelector('.disconnect').hidden = !account; root.querySelector('.disconnect').disabled = false;
    root.querySelector('.register').hidden = Boolean(account) || !state.backend;
    root.querySelector('.notes-owner').textContent = account ? `Your personal notebook: ${account.username}. These are not the viewed profile's private notes.` : 'Connect your Django account to use your personal notebook. Public analytics remain available.';
    root.querySelector('.note-controls').disabled = !ownProfile();
    if (changed || !ownProfile()) {
      state.notesLoaded = false; state.notes = []; state.editing = null; state.noteBusy = false; state.planBusy = false; state.page = 1;
      root.querySelector('.note-list').innerHTML = ''; root.querySelector('.note-status').textContent = ''; root.querySelector('.note-save').disabled = false;
      root.querySelector('.note-search').value = ''; root.querySelector('.note-topic-filter').innerHTML = '<option value="">All topics</option>'; root.querySelector('.note-topic-filter').value = ''; root.querySelector('.note-next').hidden = true; clearNote();
    }
    updateTabs();
    if (state.analytics) renderAnalytics();
    if (state.tab === 'Notes' && ownProfile() && !state.notesLoaded && !state.noteBusy) loadNotes();
  }
  function connect() {
    if (state.connecting) return;
    state.connecting = true; root.querySelector('.connect').disabled = true; root.querySelector('.account-status').textContent = 'Complete login and approve CP Assistant in the opened window.';
    // Account identity is global, not tied to the profile that launched the flow.
    send('CONNECT_ACCOUNT', {}, (reply) => {
      if (!root) return;
      state.connecting = false; root.querySelector('.connect').disabled = false;
      if (reply.result?.authenticated) { setAccount(reply.result.account); root.querySelector('.account-status').textContent = 'Account connected. Authorization restores automatically until expiry or revocation.'; }
      else root.querySelector('.account-status').textContent = reply.error || 'Connection cancelled. Retry when ready.';
    });
  }
  function loadProfile() {
    if (state.loading) return;
    const version = generation; state.loading = true; root.querySelector('.retry').hidden = true; root.querySelector('.load-status').textContent = 'Loading deterministic profile analytics...';
    send('GET_PROFILE', {}, (reply) => {
      if (!live(version)) return;
      state.loading = false;
      if (!reply.result?.summary) { root.querySelector('.load-status').textContent = reply.error || 'Public analytics unavailable. Retry later.'; root.querySelector('.retry').hidden = false; return; }
      state.analytics = reply.result; root.querySelector('.load-status').textContent = reply.result.history.note;
      root.querySelector('.retry').hidden = !reply.result.practice.error;
      renderAnalytics();
    });
  }
  function ratingChart(series) {
    const actual = series.actual || [], estimates = series.estimate || [];
    if (!actual.length) return '<p class="muted">No rated contests yet.</p>';
    const all = [...actual, ...estimates], low = Math.min(...all) - 50, high = Math.max(...all) + 50;
    const point = (value, index) => `${30 + index * 560 / Math.max(1, all.length - 1)},${150 - (number(value) - low) * 120 / Math.max(1, high - low)}`;
    const real = actual.map(point).join(' '), trend = (series.trend || []).map(point).join(' ');
    const estimate = estimates.length ? [point(actual.at(-1), actual.length - 1), ...estimates.map((value, i) => point(value, actual.length + i))].join(' ') : '';
    return `<svg viewBox="0 0 620 180" role="img" aria-label="Rating history. Blue: actual; gray: regression trend; green dashed: future estimate."><line x1="30" y1="155" x2="600" y2="155" stroke="#dce4ef"/><line x1="30" y1="90" x2="600" y2="90" class="grid-line"/><line x1="30" y1="25" x2="600" y2="25" class="grid-line"/><polyline points="${real}" fill="none" stroke="#5268ca" stroke-width="2.5"/><polyline points="${trend}" fill="none" stroke="#9ba7bc"/><polyline points="${estimate}" fill="none" stroke="#40a8a1" stroke-dasharray="5 4" stroke-width="2"/>${actual.map((value, i) => { const [x, y] = point(value, i).split(','); return `<circle cx="${x}" cy="${y}" r="3" fill="#5268ca"><title>Contest ${i + 1}: ${escape(value)}</title></circle>`; }).join('')}<text x="0" y="20">${escape(Math.round(high))}</text><text x="0" y="155">${escape(Math.round(low))}</text><text x="310" y="177" text-anchor="middle">Rated contest sequence</text></svg><p class="small muted">Blue: actual; gray: regression; teal dashed: estimate. Recent change: ${escape(series.recent_change)} over ${escape(series.recent_contests)} interval(s). Estimates are not guaranteed ratings.</p>`;
  }
  function ratingColor(rating) {
    if (!Number.isFinite(Number(rating))) return '#94a3b8';
    const value = Number(rating);
    return value >= 2400 ? '#e05260' : value >= 2100 ? '#ed9b40' : value >= 1900 ? '#a16cce' : value >= 1600 ? '#5478d8' : value >= 1400 ? '#3aadc0' : value >= 1200 ? '#4ca67b' : '#94a3b8';
  }
  function ratingBars(bars) {
    if (!bars.length) return '<div class="empty-chart">No accepted problems yet. Your rating distribution will appear here.</div>';
    const max = Math.max(1, ...bars.map(x => number(x.count))), width = Math.max(620, bars.length * 48 + 80), baseline = 214;
    const step = (width - 76) / bars.length;
    const ticks = [...new Set([0, .25, .5, .75, 1].map(x => Math.round(x * max)))];
    return `<div class="chart-scroll"><svg class="vertical-chart" viewBox="0 0 ${width} 265" style="min-width:${width}px" role="img" aria-label="Vertical bar chart: problem rating versus distinct solved questions"><text x="8" y="16" class="axis-label">Solved</text>${ticks.map(value => { const y = baseline - value / max * 178; return `<line x1="48" x2="${width - 12}" y1="${y}" y2="${y}" class="grid-line"/><text x="36" y="${y + 4}" text-anchor="end">${value}</text>`; }).join('')}${bars.map((bucket, i) => { const height = number(bucket.count) / max * 178, barWidth = Math.min(44, step * .64), x = 48 + i * step + (step - barWidth) / 2; return `<rect class="rating-bar" x="${x}" y="${baseline - height}" width="${barWidth}" height="${height}" rx="4" fill="${ratingColor(bucket.rating)}"><title>${escape(bucket.rating)}: ${escape(bucket.count)} distinct solved questions</title></rect><text x="${x + barWidth / 2}" y="${baseline - height - 7}" text-anchor="middle" class="bar-count">${escape(bucket.count)}</text><text x="${x + barWidth / 2}" y="235" text-anchor="middle">${escape(bucket.rating)}</text>`; }).join('')}<text x="${width / 2}" y="258" text-anchor="middle" class="axis-label">Problem rating</text></svg></div>`;
  }
  function topicPie(topics) {
    const ranked = topics.filter(x => number(x.solved) > 0).sort((a, b) => b.solved - a.solved);
    if (!ranked.length) return '<div class="empty-chart">No solved-topic data yet.</div>';
    const slices = ranked.slice(0, 7).map(x => ({ tag: x.tag, count: number(x.solved) }));
    if (ranked.length > 7) slices.push({ tag: 'Other topics', count: ranked.slice(7).reduce((sum, x) => sum + number(x.solved), 0) });
    const total = slices.reduce((sum, x) => sum + x.count, 0), colors = ['#5268ca', '#40a8a1', '#e6ad51', '#a879c8', '#65a6dd', '#e17f90', '#8bab69', '#a1acbc'];
    let angle = -Math.PI / 2;
    const wedges = slices.map((slice, i) => {
      const next = angle + slice.count / total * Math.PI * 2;
      const point = a => `${(100 + 84 * Math.cos(a)).toFixed(3)} ${(100 + 84 * Math.sin(a)).toFixed(3)}`;
      const shape = slices.length === 1 ? `<circle cx="100" cy="100" r="84" fill="${colors[i]}"/>` : `<path d="M 100 100 L ${point(angle)} A 84 84 0 ${next - angle > Math.PI ? 1 : 0} 1 ${point(next)} Z" fill="${colors[i]}" stroke="white" stroke-width="2"><title>${escape(slice.tag)}: ${slice.count}</title></path>`;
      angle = next; return shape;
    }).join('');
    return `<div class="pie-layout"><svg class="pie-chart" viewBox="0 0 200 200" role="img" aria-label="Topic-wise solved questions; share of solved-topic assignments">${wedges}</svg><div class="pie-legend">${slices.map((slice, i) => `<div><span class="legend-dot" style="background:${colors[i]}"></span><span>${escape(slice.tag)}</span><strong>${slice.count}</strong><small>${(100 * slice.count / total).toFixed(1)}%</small></div>`).join('')}</div></div><p class="small muted">A solved problem can have several tags. Slices show shares of solved-topic assignments, not mutually exclusive problem categories.</p>`;
  }
  function renderAnalytics() {
    const p = state.analytics, s = p.summary, version = generation;
    const bars = [...p.solved_by_rating, ...(p.unrated_solved ? [{ rating: 'Unrated', count: p.unrated_solved }] : [])];
    updateTabs();
    root.querySelector('.pane-Overview').innerHTML = `<div class="overview-hero"><div><p class="eyebrow">${ownProfile() ? 'YOUR PROGRAMMING WORKSPACE' : 'PUBLIC PROFILE SNAPSHOT'}</p><h2>${escape(s.handle)}</h2><span class="rank-label">${escape(s.rank)}</span></div><div class="hero-rating"><span>Current rating</span><strong style="color:${ratingColor(s.rating)}">${escape(s.rating ?? 'Unrated')}</strong><small>Personal best ${escape(s.max_rating ?? '?')}</small></div></div>
      <div class="metrics">${metric(p.history.complete ? 'Unique solved' : 'Observed solved', s.unique_solved)}${metric(p.history.truncated ? 'Observed submissions' : 'Submissions', s.total_submissions)}${metric('Acceptance rate', s.acceptance_rate === null ? 'No judged history' : s.acceptance_rate + '%')}${metric('Rated contests', s.rated_contests)}${metric('Highest rank', s.max_rank)}${metric('Pending submissions', s.pending_submissions)}</div>
      ${!p.history.complete ? `<p class="notice">${escape(p.history.note)}</p>` : ''}
      <div class="chart-grid"><section class="chart-card distribution-card"><div class="chart-heading"><div><h3>Distinct problems solved by rating</h3><p>Difficulty on the horizontal axis / unique solved questions on the vertical axis</p></div><span class="chart-badge">${escape(s.unique_solved)} solved</span></div>${ratingBars(bars)}</section>
      <section class="chart-card"><div class="chart-heading"><div><h3>Topic-wise questions</h3><p>Solved problem coverage</p></div></div>${topicPie(p.topics)}</section>
      <section class="chart-card"><div class="chart-heading"><div><h3>Rating trajectory</h3><p>Actual history and regression estimate</p></div></div>${ratingChart(p.rating)}</section></div>
      <details class="topic-details"><summary>Explore topic performance details <span>${p.topics.length} topics</span></summary><p class="small muted">Distinct judged problems per tag. One problem can contribute to multiple topics.</p><div class="scroll"><table><thead><tr><th>Topic</th><th>Attempted</th><th>Solved</th><th>Solve rate</th></tr></thead><tbody>${p.topics.map(t => `<tr><td>${escape(t.tag)}</td><td>${escape(t.attempted)}</td><td>${escape(t.solved)}</td><td>${escape(t.solve_rate)}%</td></tr>`).join('') || '<tr><td colspan="4">No judged topic history.</td></tr>'}</tbody></table></div></details><p class="strong-topics">Strongest supported topics <strong>${escape(p.strong_topics.map(t => t.tag).join(', ') || 'More evidence needed')}</strong></p>`;
    if (!ownProfile()) { root.querySelector('.pane-Weaknesses').innerHTML = ''; root.querySelector('.pane-Practice').innerHTML = ''; selectTab('Overview'); return; }
    root.querySelector('.pane-Weaknesses').innerHTML = `<h2>Submission-based evidence</h2><p class="muted small">${escape(s.pending_submissions)} pending submission(s), excluded from final-verdict percentages.</p><div class="scroll"><table><thead><tr><th>Verdict</th><th>Count</th><th>Share of judged</th></tr></thead><tbody>${p.verdicts.map(v => `<tr><td>${escape(v.verdict.replaceAll('_', ' '))}</td><td>${escape(v.count)}</td><td>${escape(v.percentage)}%</td></tr>`).join('') || '<tr><td colspan="3">No final verdicts.</td></tr>'}</tbody></table></div>
      <h3>Topics needing practice</h3><p class="small muted">${escape(p.methodology.weakness_score)}</p>${p.weak_topics.map(t => `<article><strong>${escape(t.tag)} · score ${escape(t.weakness_score)}</strong><p>${escape(t.evidence)}</p><p class="small">Average attempts per solved problem: ${escape(t.average_attempts_per_solved ?? '—')}; typical attempted rating: ${escape(t.typical_rating ?? 'unrated')}.</p></article>`).join('') || '<p>No topic meets the weakness evidence threshold yet.</p>'}
      <h3>Mistake patterns</h3>${list(p.patterns, 'No repeated patterns meet the evidence thresholds.')}<p class="small muted">Verdicts do not prove a particular coding bug.</p><h3>Recommended focus</h3>${p.focus_topics.map(t => `<article><strong>${escape(t.tag)} · ${escape(t.difficulty_min)}–${escape(t.difficulty_max)}</strong><p>${escape(t.reason)}</p></article>`).join('')}`;
    root.querySelector('.pane-Practice').innerHTML = `<h2>Deterministic practice recommendations</h2><p>${escape(p.practice.note || p.practice.error || '')}</p>${p.practice.problems.map(x => `<article><a href="${escape(x.url)}" target="_blank" rel="noopener noreferrer">${escape(x.name)}</a><span class="rating">${escape(x.rating)}</span><p class="small muted">${escape(x.tags.join(', '))}</p><p>${escape(x.reason)}</p></article>`).join('') || '<p>No eligible problems available. Retry public analytics later if Codeforces is unavailable.</p>'}
      <h3>AI improvement plan</h3><p class="muted">Optional. Uses this profile's measured summary only. Requires your connected Django account; up to three attempts per hour.</p><button class="generate-plan" type="button">Generate AI Improvement Plan</button><p class="plan-status" role="status" aria-live="polite"></p><div class="plan-result"></div>`;
    root.querySelector('.generate-plan').disabled = !ownProfile() || state.planBusy;
    root.querySelector('.generate-plan').addEventListener('click', () => {
      if (state.planBusy || !ownProfile()) return;
      const epoch = state.accountEpoch;
      state.planBusy = true; root.querySelector('.generate-plan').disabled = true; root.querySelector('.plan-status').textContent = 'Generating an evidence-based improvement plan...';
      send('GENERATE_PLAN', {}, (reply) => {
        if (!live(version) || !ownProfile() || state.accountEpoch !== epoch) return;
        state.planBusy = false; root.querySelector('.generate-plan').disabled = !ownProfile();
        if (!reply.result?.plan) { root.querySelector('.plan-status').textContent = reply.error || 'Plan unavailable. Retry explicitly when ready.'; return; }
        const plan = reply.result.plan;
        root.querySelector('.plan-result').innerHTML = `<h3>AI-generated advice · not measured statistics</h3><h4>Major areas</h4>${list(plan.major_areas, 'No supported areas.')}<h4>Topics and learning order</h4>${list(plan.learning_order, '')}${list(plan.topics_to_learn, '')}<h4>Practice strategy</h4><p>${escape(plan.practice_strategy)}</p><h4>Supported patterns</h4>${list(plan.supported_patterns, 'No additional patterns.')}<h4>Short-term plan</h4>${list(plan.short_term_plan.map(x => x.day + ': ' + x.task), '')}`;
        root.querySelector('.plan-status').textContent = reply.result.cached ? 'Showing your cached plan.' : 'Plan ready. Adapt the pace to your available time.';
      });
    });
    selectTab(state.tab);
  }
  function noteShell() {
    return `<h2>My personal notes</h2><p class="notes-owner">Connect your Django account to use your notebook. Notes are not associated with the viewed profile's identity.</p><fieldset class="note-controls" disabled><form class="note-filter"><label>Search<input class="note-search" maxlength="200" placeholder="Search title, content, topic"></label><label>Topic<select class="note-topic-filter"><option value="">All topics</option></select></label><button type="submit">Search / filter</button></form><form class="note-form"><label>Title<input class="note-title" required maxlength="200"></label><label>Topic / tag (optional)<input class="note-topic" maxlength="300"></label><label>Content<textarea class="note-content" required maxlength="20000" rows="5"></textarea></label><button class="note-save" type="submit">Save note</button><button class="note-new" type="button">New / cancel edit</button></form><p class="note-status" role="status" aria-live="polite"></p><div class="note-list"></div><button class="note-next" type="button" hidden>Next page</button></fieldset>`;
  }
  function clearNote() { if (!root) return; state.editing = null; root.querySelector('.note-title').value = ''; root.querySelector('.note-content').value = ''; root.querySelector('.note-topic').value = ''; root.querySelector('.note-save').textContent = 'Save note'; }
  function bindNotes(version) {
    root.querySelector('.note-new').addEventListener('click', clearNote);
    root.querySelector('.note-filter').addEventListener('submit', (event) => { event.preventDefault(); state.page = 1; loadNotes(); });
    root.querySelector('.note-next').addEventListener('click', () => { state.page++; loadNotes(); });
    root.querySelector('.note-form').addEventListener('submit', (event) => {
      event.preventDefault(); if (state.noteBusy || !ownProfile()) return;
      if (!root.querySelector('.note-title').value.trim() || !root.querySelector('.note-content').value.trim()) { root.querySelector('.note-status').textContent = 'Title and content are required.'; return; }
      const payload = { title: root.querySelector('.note-title').value, content: root.querySelector('.note-content').value, topic: root.querySelector('.note-topic').value, updated_at: state.editing?.updated_at };
      const epoch = state.accountEpoch;
      state.noteBusy = true; root.querySelector('.note-save').disabled = true; root.querySelector('.note-status').textContent = 'Saving...';
      send('SAVE_NOTE', { payload, id: state.editing?.id }, (reply) => {
        if (!live(version) || !ownProfile() || state.accountEpoch !== epoch) return; state.noteBusy = false; root.querySelector('.note-save').disabled = false;
        if (reply.error) { root.querySelector('.note-status').textContent = reply.error; return; }
        clearNote(); state.page = 1; loadNotes('Saved. ');
      });
    });
  }
  function loadNotes(prefix = '') {
    if (state.noteBusy || !ownProfile()) return;
    const version = generation, epoch = state.accountEpoch; state.noteBusy = true; root.querySelector('.note-status').textContent = 'Loading your notebook...';
    const topic = root.querySelector('.note-topic-filter').value;
    send('GET_NOTES', { query: { q: root.querySelector('.note-search').value || '', topic, page: state.page } }, (reply) => {
      if (!live(version) || !ownProfile() || state.accountEpoch !== epoch) return; state.noteBusy = false;
      if (!reply.result?.results) { root.querySelector('.note-status').textContent = reply.error || 'Notebook unavailable.'; return; }
      state.notesLoaded = true; state.notes = reply.result.results;
      root.querySelector('.note-topic-filter').innerHTML = '<option value="">All topics</option>' + reply.result.topics.map(t => `<option>${escape(t)}</option>`).join(''); root.querySelector('.note-topic-filter').value = topic;
      root.querySelector('.note-list').innerHTML = state.notes.map(note => `<article><h3>${escape(note.title)}</h3><p class="small muted">${escape(note.topic)} · ${escape(note.updated_at)}</p><p class="preserve">${escape(note.content)}</p><button class="edit-note" data-id="${number(note.id)}" type="button">Edit</button><button class="delete-note" data-id="${number(note.id)}" type="button">Delete</button></article>`).join('') || '<p>No matching notes. Create one above.</p>';
      root.querySelector('.note-next').hidden = !reply.result.next_page;
      root.querySelector('.note-status').textContent = prefix + `${reply.result.count} note(s), latest update first.`;
      for (const button of root.querySelectorAll('.edit-note')) button.addEventListener('click', () => {
        if (!ownProfile() || state.accountEpoch !== epoch) return;
        state.editing = state.notes.find(n => n.id === Number(button.dataset.id));
        root.querySelector('.note-title').value = state.editing.title; root.querySelector('.note-content').value = state.editing.content; root.querySelector('.note-topic').value = state.editing.topic; root.querySelector('.note-save').textContent = 'Update note'; root.querySelector('.note-title').focus();
      });
      for (const button of root.querySelectorAll('.delete-note')) button.addEventListener('click', () => {
        if (state.noteBusy || !ownProfile() || !window.confirm('Delete this personal note?')) return;
        const note = state.notes.find(n => n.id === Number(button.dataset.id)); state.noteBusy = true;
        send('DELETE_NOTE', { id: note.id, updated_at: note.updated_at }, (result) => { if (!live(version) || !ownProfile() || state.accountEpoch !== epoch) return; state.noteBusy = false; if (result.error) root.querySelector('.note-status').textContent = result.error; else { if (state.editing?.id === note.id) clearNote(); state.page = 1; loadNotes('Deleted. '); } });
      });
    });
  }
  syncProfile();
  window.addEventListener('popstate', syncProfile);
  window.setInterval(syncProfile, 1000);
  function styles() { return `<style>
    :host{all:initial;display:block;margin:22px 0;font:13px/1.55 Arial,Helvetica,sans-serif;color:#29364b;--accent:#405cb4;--border:#dce3ed}*{box-sizing:border-box}[hidden]{display:none!important}.panel{border:1px solid var(--border);border-radius:12px;background:#fff;box-shadow:0 5px 22px #243d6510;overflow:hidden}header{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:linear-gradient(115deg,#edf2fa,#f7f9fd);border-bottom:1px solid var(--border)}header strong{color:#354e9b;font:bold 15px Verdana,Arial,sans-serif}.viewed{margin-left:14px;color:#67748a;font-size:12px}.account{display:flex;flex-wrap:wrap;align-items:center;gap:9px;padding:12px 18px}.account-label{flex:1;font-size:12px;color:#5f6c82}.account-status{margin:0;padding:0 18px;color:#7a4e19}.own-notice{font-size:12px;color:#627089;margin:0;padding:0 18px 13px}.workspace-badge{display:inline-block;margin-right:6px;border-radius:20px;padding:2px 8px;background:#e8f5ef;color:#247153;font-weight:bold}.panel-content{padding:0 18px 18px}button,input,select,textarea{font:inherit}button{cursor:pointer;border:1px solid #cbd5e4;border-radius:6px;background:white;padding:7px 12px;color:#344c7e;transition:background .15s,box-shadow .15s}button:hover{background:#edf2fb}button:disabled{opacity:.55;cursor:default}a{color:#365aad;text-underline-offset:3px}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:2px solid #536dce;outline-offset:3px}nav{display:flex;gap:6px;flex-wrap:wrap;background:#f1f4f9;border:1px solid #e6ebf3;border-radius:9px;padding:5px;margin-bottom:17px}nav button{border-color:transparent;background:transparent;flex:1;font-weight:bold;padding:9px 15px;color:#66738a}nav button[aria-selected=true]{background:white;color:#3b56ab;border-color:#dfe5f1;box-shadow:0 2px 5px #304c7610}[role=tabpanel]{max-height:780px;overflow:auto;padding:1px 3px 3px 0;scrollbar-width:thin}h2{font:bold 17px Verdana,Arial,sans-serif;color:#314570;margin:12px 0}h3{font-size:14px;color:#334970;margin:18px 0 8px}h4{font-size:13px;margin:15px 0 6px}p{margin:8px 0}.muted,.small{color:#768297}.small{font-size:11px}.notice{border-left:3px solid #d5ab56;background:#fff9ed;padding:10px;border-radius:4px}.overview-hero{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 24px;border:1px solid #dfe6f3;background:linear-gradient(120deg,#edf2fc 0%,#f6f7fd 55%,#eef8f7 100%);border-radius:10px;margin-bottom:14px}.eyebrow{font-size:10px;letter-spacing:1.5px;color:#6b7da5;font-weight:bold;margin:0}.overview-hero h2{font-size:26px;letter-spacing:-.7px;margin:5px 0;overflow-wrap:anywhere}.rank-label{font-size:12px;text-transform:capitalize;color:#62769b}.hero-rating{text-align:right;flex-shrink:0}.hero-rating span,.hero-rating small{display:block;color:#6d7d93;font-size:11px}.hero-rating strong{display:block;font-size:34px;line-height:1.3;letter-spacing:-1px}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:18px}.metric{padding:14px 15px;border:1px solid #e2e8f1;border-radius:8px;background:white;box-shadow:0 2px 6px #243d6505}.metric span{display:block;color:#7d899c;font-size:11px}.metric strong{display:block;font-size:21px;color:#344b79;overflow-wrap:anywhere;margin-top:3px}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.chart-card{min-width:0;border:1px solid #e0e6f0;border-radius:10px;background:#fff;padding:16px}.distribution-card{grid-column:1/-1}.chart-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:15px}.chart-heading h3{font-size:13px;margin:0 0 4px}.chart-heading p{font-size:11px;color:#8591a3;margin:0}.chart-badge{padding:4px 8px;white-space:nowrap;font-size:11px;border-radius:5px;background:#eef2fc;color:#4d65ac}.chart-scroll,.scroll{overflow-x:auto;overscroll-behavior:contain}svg{width:100%;max-height:220px;display:block}svg text{font:10px Arial;fill:#8491a5}.vertical-chart{width:100%;max-height:none}.axis-label{font-weight:bold;fill:#627492}.grid-line{stroke:#e9edf5;stroke-width:1;stroke-dasharray:3 4}.bar-count{fill:#526680;font-weight:bold}.rating-bar{transition:opacity .15s}.rating-bar:hover{opacity:.75}.pie-layout{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:center}.pie-chart{width:180px;height:180px;flex:0 0 180px;filter:drop-shadow(0 3px 4px #3f527214)}.pie-legend{flex:1;min-width:135px}.pie-legend>div{display:grid;grid-template-columns:9px 1fr auto auto;gap:7px;align-items:center;font-size:11px;padding:5px 0;border-bottom:1px solid #f0f3f8}.legend-dot{height:8px;width:8px;border-radius:50%}.pie-legend small{font-size:10px;color:#8a97a9}.pie-legend strong{color:#415479}.empty-chart{padding:35px 15px;text-align:center;border-radius:6px;background:#f8fafd;color:#8793a6}.topic-details{margin-top:14px;border:1px solid #e2e8f1;border-radius:8px;padding:12px}.topic-details summary{cursor:pointer;font-weight:bold;color:#52688e}.topic-details summary span{float:right;font-size:11px;color:#8c98aa;font-weight:normal}.strong-topics{font-size:11px;color:#7c8ba0;padding:5px 3px}.strong-topics strong{display:block;color:#457a73;margin-top:3px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;border-bottom:1px solid #e6ebf3;padding:9px}th{background:#f4f7fb;color:#6d7e97;font-size:11px}tbody tr:nth-child(even){background:#fafbfd}article{border:1px solid #e0e7f1;border-radius:8px;padding:13px 15px;margin:10px 0;background:#fafcfe}article h3{margin-top:0}.rating{float:right;font-weight:bold;background:#edf2fb;color:#516eac;padding:2px 7px;border-radius:5px}label{display:block;margin:10px 0;color:#5d6f88;font-size:12px}input,textarea,select{display:block;width:100%;padding:9px;border:1px solid #ccd6e4;border-radius:5px;margin-top:5px;background:#fff;color:#29364b}textarea{resize:vertical}.note-controls{border:0;margin:0;padding:0;min-width:0}.note-filter{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;align-items:end}.note-filter button{margin-bottom:10px}.note-form{border:1px solid #e0e7f1;border-radius:8px;background:#f7f9fd;padding:14px}.preserve{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:6px 0}.load-status{font-size:11px;color:#8a96a7}.retry{margin-top:8px}.generate-plan,.note-save{background:#405cb4;color:white;border-color:#405cb4}.generate-plan:hover,.note-save:hover{background:#324c9c}@media(max-width:760px){.chart-grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.viewed{display:block;margin-left:0}.overview-hero{padding:18px}.chart-card{padding:12px}.pie-chart{width:170px;height:170px;flex-basis:170px}}@media(max-width:480px){.panel-content{padding:0 10px 12px}header,.account{padding:11px}.own-notice{padding:0 11px 11px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.metric{padding:10px}.overview-hero h2{font-size:21px}.hero-rating strong{font-size:27px}.note-filter{grid-template-columns:1fr}nav button{padding:8px 6px;font-size:12px}.account-label{flex-basis:100%}}
  </style>`; }
})();
