(function detectCodeforcesProblem() {
  if (window.location.hostname !== 'codeforces.com' && window.location.hostname !== 'www.codeforces.com') {
    return;
  }

  const problemPath = /^\/problemset\/problem\/([^/]+)\/([^/]+)\/?$/;
  const match = window.location.pathname.match(problemPath);
  if (!match) {
    return;
  }

  const problem = {
    contestId: match[1],
    index: match[2],
    url: window.location.href
  };

  chrome.runtime.sendMessage({ type: 'CODEFORCES_PROBLEM_DETECTED', problem });
  renderLoadingPanel(problem);
  chrome.runtime.sendMessage({ type: 'GET_PANEL_CONTEXT' }, (panelContext) => {
    if (chrome.runtime.lastError || !panelContext?.context || !panelContext.context.authenticated) {
      renderErrorPanel(problem, 'CP Assistant is unavailable right now.');
      return;
    }
    renderPanel(panelContext.context, panelContext.problem || problem);
  });

  function createPanel() {
    const existingPanel = document.querySelector('#cp-assistant-panel-host');
    if (existingPanel) {
      existingPanel.remove();
    }

    const host = document.createElement('div');
    host.id = 'cp-assistant-panel-host';
    const shadowRoot = host.attachShadow({ mode: 'closed' });
    const statement = document.querySelector('.problem-statement');
    const insertionPoint = statement?.parentElement || document.body;
    insertionPoint.appendChild(host);
    return { host, shadowRoot };
  }

  function renderLoadingPanel(currentProblem) {
    const { shadowRoot } = createPanel();
    shadowRoot.innerHTML = styles() + `
      <section class="panel" aria-label="CP Assistant">
        <header class="header"><strong>CP-ASSISTANT</strong><span>${escapeHtml(currentProblem.contestId)}${escapeHtml(currentProblem.index)}</span><button class="collapse" type="button">Collapse</button></header>
        <div class="body"><p class="loading">Loading your analysis...</p></div>
      </section>`;
    bindCollapse(shadowRoot);
  }

  function renderErrorPanel(currentProblem, message) {
    const { shadowRoot } = createPanel();
    shadowRoot.innerHTML = styles() + `
      <section class="panel" aria-label="CP Assistant">
        <header class="header"><strong>CP-ASSISTANT</strong><span>${escapeHtml(currentProblem.contestId)}${escapeHtml(currentProblem.index)}</span><button class="collapse" type="button">Collapse</button></header>
        <div class="body"><p class="error">${escapeHtml(message)}</p></div>
      </section>`;
    bindCollapse(shadowRoot);
  }

  function renderPanel(context, currentProblem) {
    const { shadowRoot } = createPanel();
    const analysis = context.problem_analysis || {};
    const fit = analysis.fit || {};
    const history = context.problem_history || {};
    const recommendation = context.recommendation;
    const tagPerformance = Object.entries(analysis.tag_performance || {}).slice(0, 3);
    const problemRating = context.problem?.rating;
    const userRating = context.analytics?.current_rating;
    const fitDetails = fitLabel(fit.classification, problemRating, userRating);
    const historyLabel = history.solved ? 'Solved' : history.attempted ? 'Attempted' : 'Not attempted';
    const failedAttempts = (history.verdict_history || []).filter((verdict) => verdict !== 'OK').length;
    const tagMarkup = tagPerformance.length
      ? tagPerformance.map(([tag, data]) => {
        const successRate = Number(data.success_rate) || 0;
        return `<li><div class="tag-row"><span class="tag-pill">${escapeHtml(tag)}</span><span class="tag-counts">${escapeHtml(data.solved)} solved / ${escapeHtml(data.failed)} failed</span><strong>${escapeHtml(successRate)}%</strong></div><div class="progress"><span style="width:${Math.min(100, Math.max(0, successRate))}%"></span></div></li>`;
      }).join('')
      : '<li class="muted">No tag history yet.</li>';
    const recommendationMarkup = recommendation?.problem
      ? `<div class="next-meta"><h3>${escapeHtml(recommendation.problem.name)}</h3><p><strong>${escapeHtml(recommendation.problem.rating)}</strong> <span class="tag-list">${escapeHtml(recommendation.problem.tags.join('  '))}</span></p></div><p class="reason">${escapeHtml(recommendation.reason)}</p><a class="solve" href="${escapeHtml(recommendation.problem.url)}" target="_blank" rel="noopener">Solve Problem &rarr;</a>`
      : '<p class="muted">No suitable next problem found yet.</p>';

    shadowRoot.innerHTML = styles() + `
      <section class="panel" aria-label="CP Assistant">
        <header class="header"><strong>CP-ASSISTANT</strong><span>${escapeHtml(currentProblem.contestId)}${escapeHtml(currentProblem.index)}</span><button class="collapse" type="button">Collapse</button></header>
        <div class="body">
          <section class="summary-card"><h2>YOUR FIT</h2><p class="fit"><span class="dot ${fitDetails.color}"></span>${escapeHtml(fitDetails.label)}</p><div class="rating-grid"><span>Problem rating</span><strong>${escapeHtml(problemRating ?? '—')}</strong><span>Your rating</span><strong>${escapeHtml(userRating ?? '—')}</strong><span>Difference</span><strong>${escapeHtml(fitDetails.difference)}</strong></div><p class="muted">${escapeHtml(fitDetails.explanation)}</p></section>
          <section class="summary-card"><h2>YOUR HISTORY</h2><p>This problem: <strong>${historyLabel}</strong></p><div class="history-counts"><span>Attempts <strong>${escapeHtml(history.attempts ?? 0)}</strong></span><span>Solved <strong>${escapeHtml(history.solved ? 1 : 0)}</strong></span><span>Failed <strong>${escapeHtml(failedAttempts)}</strong></span></div><p class="caption">Tag percentages are your success rates.</p><ul>${tagMarkup}</ul></section>
          <section class="next-card"><h2>NEXT PROBLEM</h2>${recommendationMarkup}</section>
        </div>
      </section>`;
    bindCollapse(shadowRoot);
  }

  function bindCollapse(shadowRoot) {
    const button = shadowRoot.querySelector('.collapse');
    const body = shadowRoot.querySelector('.body');
    button.addEventListener('click', () => {
      const collapsed = body.hidden;
      body.hidden = !collapsed;
      button.textContent = collapsed ? 'Collapse' : 'Expand';
    });
  }

  function fitLabel(classification, problemRating, userRating) {
    const labels = {
      too_easy: ['Good Practice', 'green'],
      good_practice: ['Good Practice', 'green'],
      stretch: ['Stretch Practice', 'yellow'],
      too_hard: ['Challenging Practice', 'red']
    };
    const [label, color] = labels[classification] || labels.good_practice;
    const difference = Number.isFinite(problemRating) && Number.isFinite(userRating)
      ? problemRating - userRating
      : null;
    const differenceLabel = difference === null ? '—' : `${difference > 0 ? '+' : ''}${difference}`;
    const explanation = difference === null
      ? 'Based on your available practice history.'
      : difference === 0
        ? 'This is right around your current rating.'
        : `${Math.abs(difference)} points ${difference > 0 ? 'above' : 'below'} your current rating.`;
    return { label, color, difference: differenceLabel, explanation };
  }

  function styles() {
    return `<style>
      :host { all: initial; display: block; font: 13px/1.45 Arial, sans-serif; }
      .panel { box-sizing: border-box; width: min(100%, 760px); margin: 24px auto; border: 1px solid #c8ccd1; border-radius: 6px; background: #fff; color: #333; box-shadow: 0 3px 8px rgba(0,0,0,.1); }
      .header { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid #d6d9dc; background: #f5f6f7; color: #555; font-size: 12px; }
      .header strong { color: #333; letter-spacing: .05em; } .header span { color: #777; flex: 1; }
      .collapse { border: 0; background: transparent; color: #1769aa; cursor: pointer; font-size: 12px; }
      .body { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 16px; } .body[hidden] { display: none; }
      section { min-width: 0; } .summary-card, .next-card { padding: 15px; border: 1px solid #e1e4e8; border-radius: 5px; background: #fbfbfc; } .next-card { grid-column: 1 / -1; border-color: #c9dced; background: #f7fbff; }
      h2 { margin: 0 0 10px; color: #777; font-size: 11px; letter-spacing: .06em; } h3 { margin: 0 0 5px; color: #1769aa; font-size: 16px; line-height: 1.3; }
      p { margin: 5px 0; } .muted { color: #666; font-size: 12px; } .caption { margin-top: 12px; color: #777; font-size: 11px; } .loading, .error { color: #666; } .error { color: #a94442; }
      .fit { font-size: 15px; font-weight: 700; } .dot { display: inline-block; width: 9px; height: 9px; margin-right: 7px; border-radius: 50%; } .green { background: #3c9a5f; } .yellow { background: #d6a515; } .red { background: #c94c4c; }
      .rating-grid { display: grid; grid-template-columns: 1fr auto; gap: 5px 12px; margin: 12px 0; color: #777; font-size: 12px; } .rating-grid strong { color: #333; }
      .history-counts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; color: #777; font-size: 12px; } .history-counts span { padding: 4px 7px; border: 1px solid #e1e4e8; border-radius: 12px; background: #fff; } .history-counts strong { color: #333; }
      ul { display: grid; gap: 8px; margin: 8px 0 0; padding: 0; list-style: none; } li { min-width: 0; } .tag-row { display: flex; align-items: center; gap: 7px; } .tag-pill { padding: 3px 7px; border-radius: 10px; background: #e7f1fa; color: #1769aa; font-size: 11px; font-weight: 700; } .tag-counts { flex: 1; color: #777; font-size: 11px; } .tag-row strong { color: #333; font-size: 12px; }
      .progress { height: 4px; margin-top: 4px; overflow: hidden; border-radius: 4px; background: #e5e7ea; } .progress span { display: block; height: 100%; border-radius: inherit; background: #5b9bd5; }
      .tag-list { color: #1769aa; font-size: 12px; } .reason { max-width: 620px; color: #555; font-size: 12px; } .solve { display: inline-block; margin-top: 9px; padding: 7px 11px; border-radius: 4px; background: #337ab7; color: #fff; text-decoration: none; font-weight: 700; } .solve:hover { background: #286090; }
      @media (max-width: 700px) { .body { grid-template-columns: 1fr; gap: 10px; } .next-card { grid-column: auto; } }
    </style>`;
  }

  function escapeHtml(value) {
    return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  }
})();