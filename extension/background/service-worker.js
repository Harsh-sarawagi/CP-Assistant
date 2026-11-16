import '../shared/api.js';

function profileHandle(url) {
  try { const parsed = new URL(url); const match = parsed.pathname.match(/^\/profile\/([A-Za-z0-9_.-]{1,24})\/?$/); return parsed.origin === 'https://codeforces.com' && match ? match[1] : null; }
  catch { return null; }
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  const internal = sender.url === chrome.runtime.getURL('popup/popup.html') || sender.url === chrome.runtime.getURL('options/options.html');
  const handle = sender.frameId === 0 ? profileHandle(sender.url) : null;
  if (!internal && !handle) return false;
  const validId = (id) => Number.isSafeInteger(id) && id > 0;
  const handlers = {
    GET_SETTINGS: () => CPAssistantApi.getSettings(),
    SET_COLLAPSED: () => CPAssistantApi.setCollapsed(message.collapsed),
    AUTH_STATUS: () => CPAssistantApi.status(),
    CONNECT_ACCOUNT: () => CPAssistantApi.connect(),
    DISCONNECT_ACCOUNT: () => CPAssistantApi.disconnect(),
    BACKEND_CHANGED: () => internal ? CPAssistantApi.clearConnection() : Promise.reject(new Error('Not allowed.')),
    GET_PROFILE: () => handle ? CPAssistantApi.publicProfile(handle) : Promise.reject(new Error('Open a Codeforces profile.')),
    GENERATE_PLAN: () => handle ? CPAssistantApi.plan(handle) : Promise.reject(new Error('Open a Codeforces profile.')),
    GET_NOTES: () => CPAssistantApi.notes(message.query || {}),
    SAVE_NOTE: () => !message.id || validId(message.id) ? CPAssistantApi.saveNote(message.payload, message.id) : Promise.reject(new Error('Invalid note.')),
    DELETE_NOTE: () => validId(message.id) ? CPAssistantApi.deleteNote(message.id, message.updated_at) : Promise.reject(new Error('Invalid note.'))
  };
  if (!Object.hasOwn(handlers, message.type)) return false;
  Promise.resolve().then(handlers[message.type]).then((result) => sendResponse({ result }))
    .catch((error) => sendResponse({ error: error.message || 'Request failed. Check the backend connection and try again.' }));
  return true;
});
