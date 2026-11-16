const statusElement = document.querySelector('#status');
function send(type) {
  return new Promise((resolve) => chrome.runtime.sendMessage({ type }, (reply) => resolve(chrome.runtime.lastError ? { error: 'Reload the extension and retry.' } : reply || {})));
}
function show(reply) {
  const account = reply.result?.authenticated ? reply.result.account : null;
  statusElement.textContent = account ? `Connected as ${account.username}` : reply.error || 'Public analytics available. Connect for notes and AI plans.';
  document.querySelector('#connect').hidden = Boolean(account);
  document.querySelector('#disconnect').hidden = !account;
}
send('GET_SETTINGS').then(({ result }) => {
  if (!result) return;
  document.querySelector('#register').href = result.backendUrl + '/register/';
  document.querySelector('#dashboard').href = result.backendUrl + '/dashboard/';
});
send('AUTH_STATUS').then(show);
for (const [selector, type] of [['#connect', 'CONNECT_ACCOUNT'], ['#disconnect', 'DISCONNECT_ACCOUNT']]) {
  const button = document.querySelector(selector);
  button.addEventListener('click', async () => { if (button.disabled) return; button.disabled = true; statusElement.textContent = 'Working...'; show(await send(type)); button.disabled = false; });
}
document.querySelector('#options').addEventListener('click', () => chrome.runtime.openOptionsPage());
