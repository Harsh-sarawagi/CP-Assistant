import '../shared/api.js';

const detectedProblems = new Map();

chrome.runtime.onInstalled.addListener(() => {
  console.log('CP Assistant extension installed.');
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CODEFORCES_PROBLEM_DETECTED' && sender.tab?.id !== undefined) {
    detectedProblems.set(sender.tab.id, message.problem);
    sendResponse({ ok: true });
    return;
  }

  if (message.type === 'GET_DETECTED_PROBLEM') {
    sendResponse({ problem: detectedProblems.get(message.tabId) || null });
    return;
  }

  if (message.type === 'GET_PANEL_CONTEXT' && sender.tab?.id !== undefined) {
    const problem = detectedProblems.get(sender.tab.id) || null;
    if (!problem) {
      sendResponse({ context: null, backendUrl: null, problem: null });
      return;
    }

    CPAssistantApi.getContext(problem)
      .then((context) => CPAssistantApi.getBackendUrl().then((backendUrl) => ({ context, backendUrl, problem })))
      .then((panelContext) => sendResponse(panelContext))
      .catch(() => sendResponse({ context: null, backendUrl: null, problem }));
  }

  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  detectedProblems.delete(tabId);
});
