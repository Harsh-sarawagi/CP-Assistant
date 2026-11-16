const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../core/static/core/code-review.js'), 'utf8');

function page({ valid = true, sources = null, clipboardError = false } = {}) {
  const elements = new Map(), events = {}, copied = [];
  const node = id => {
    if (!elements.has(id)) elements.set(id, { disabled: false, textContent: '', dataset: {}, listeners: {}, classes: new Set(),
      classList: { add(k) { node(id).classes.add(k); }, remove(k) { node(id).classes.delete(k); } },
      addEventListener(type, fn) { this.listeners[type] = fn; }, checkValidity: () => valid });
    return elements.get(id);
  };
  const original = node('copy-original'), suggested = node('copy-suggested');
  original.dataset.source = 'original'; suggested.dataset.source = 'suggested';
  if (sources) node('copy-sources').textContent = JSON.stringify(sources);
  vm.runInNewContext(source, {
    document: { getElementById(id) { if (id === 'copy-sources' && !sources) return null; return node(id); }, querySelectorAll: () => [original, suggested] },
    window: { addEventListener(type, fn) { events[type] = fn; } },
    navigator: { clipboard: { async writeText(text) { if (clipboardError) throw Error('Denied'); copied.push(text); } } }
  });
  return { node, events, copied, submit() { const event = { prevented: false, preventDefault() { this.prevented = true; } }; node('review-form').listeners.submit(event); return event; } };
}

test('review form allows one submission and restores controls on browser back navigation', () => {
  const p = page(); assert.equal(p.submit().prevented, false);
  assert.equal(p.node('analyzeBtn').disabled, true); assert.equal(p.submit().prevented, true);
  assert.match(p.node('review-status').textContent, /one AI review/);
  p.events.pageshow(); assert.equal(p.node('analyzeBtn').disabled, false);
  assert.equal(p.submit().prevented, false);
});

test('invalid forms do not enter the loading state', () => {
  const p = page({ valid: false }); p.submit(); assert.equal(p.node('analyzeBtn').disabled, false);
});

test('copying preserves the complete original and suggested source as text', async () => {
  const sources = { original: '  print("<script>")\n', suggested: '</script>\nint main() { return 0; }\n' };
  const p = page({ sources });
  await p.node('copy-original').listeners.click(); await p.node('copy-suggested').listeners.click();
  assert.deepEqual(p.copied, [sources.original, sources.suggested]); assert.equal(p.node('copy-status').textContent, 'Code copied.');
});

test('clipboard permission failure offers manual copying without losing code', async () => {
  const p = page({ sources: { original: 'source', suggested: 'fixed' }, clipboardError: true });
  await p.node('copy-suggested').listeners.click(); assert.match(p.node('copy-status').textContent, /Select and copy/);
});
