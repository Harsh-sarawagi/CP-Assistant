(function createApiClient() {
  const defaultBackendUrl = 'http://127.0.0.1:8000';

  async function getBackendUrl() {
    const settings = await chrome.storage.local.get({ backendUrl: defaultBackendUrl });
    return settings.backendUrl.replace(/\/$/, '');
  }

  async function getContext(problem) {
    const backendUrl = await getBackendUrl();
    const endpoint = problem
      ? `${backendUrl}/api/extension/context/?${new URLSearchParams({ contest_id: problem.contestId, index: problem.index })}`
      : `${backendUrl}/api/extension/context/`;
    const response = await fetch(endpoint, {
      credentials: 'include',
      headers: { Accept: 'application/json' }
    });

    if (!response.ok && response.status !== 401) {
      throw new Error(`Backend returned HTTP ${response.status}`);
    }

    return response.json();
  }

  globalThis.CPAssistantApi = { defaultBackendUrl, getBackendUrl, getContext };
})();