const backendUrlInput = document.querySelector('#backend-url');
const saveButton = document.querySelector('#save');
const statusElement = document.querySelector('#status');
chrome.runtime.sendMessage({ type: 'GET_SETTINGS' }, (reply) => {
  if (chrome.runtime.lastError || !reply?.result) { statusElement.textContent = 'Reload the extension and retry.'; return; }
  backendUrlInput.value = reply.result.backendUrl;
  statusElement.textContent = `Extension ID: ${reply.result.clientId}. Allowlist this ID on the Django backend.`;
});
saveButton.addEventListener('click', async () => {
  if (saveButton.disabled) return;
  saveButton.disabled = true;
  try {
    const parsed = new URL(backendUrlInput.value);
    if (parsed.username || parsed.password || (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsed.hostname)))) throw new Error('Use HTTPS, or HTTP on localhost for development.');
    const backendUrl = parsed.origin, origin = backendUrl + '/*';
    if (!await chrome.permissions.contains({ origins: [origin] }) && !await chrome.permissions.request({ origins: [origin] })) throw new Error('Backend host permission is required.');
    const old = await chrome.storage.local.get('backendUrl');
    if (old.backendUrl !== backendUrl) {
      await chrome.storage.local.set({ backendUrl });
      await new Promise((resolve) => chrome.runtime.sendMessage({ type: 'BACKEND_CHANGED' }, () => { void chrome.runtime.lastError; resolve(); }));
    }
    backendUrlInput.value = backendUrl;
    statusElement.textContent = 'Saved. If the backend changed, reconnect your account. Revoke old authorizations on the old website when needed.';
  } catch (error) { statusElement.textContent = error.message || 'Enter a valid backend URL.'; }
  finally { saveButton.disabled = false; }
});
