(() => {
  const form = document.getElementById('review-form');
  let submitting = false;
  function reset() {
    submitting = false;
    document.getElementById('analyzeBtn').disabled = false;
    document.getElementById('btnText').textContent = 'Review my submission';
    document.getElementById('btnSpinner').classList.add('d-none');
    document.getElementById('review-status').textContent = '';
  }
  form?.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    if (!form.checkValidity()) return;
    submitting = true;
    document.getElementById('analyzeBtn').disabled = true;
    document.getElementById('btnText').textContent = 'Reviewing your code...';
    document.getElementById('btnSpinner').classList.remove('d-none');
    document.getElementById('review-status').textContent = 'Fetching the problem and requesting one AI review. Please wait.';
  });
  // Restore controls when returning via the browser back/forward cache.
  window.addEventListener('pageshow', reset);
  const data = document.getElementById('copy-sources');
  if (!data) return;
  const sources = JSON.parse(data.textContent);
  for (const button of document.querySelectorAll('.copy-code')) {
    button.addEventListener('click', async () => {
      const status = document.getElementById('copy-status');
      try {
        await navigator.clipboard.writeText(sources[button.dataset.source]);
        status.textContent = 'Code copied.';
      } catch {
        status.textContent = 'Clipboard unavailable. Select and copy the code directly.';
      }
    });
  }
})();
