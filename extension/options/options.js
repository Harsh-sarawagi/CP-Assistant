const backendUrlInput = document.querySelector('#backend-url');
const saveButton = document.querySelector('#save');
const statusElement = document.querySelector('#status');

CPAssistantApi.getBackendUrl().then((backendUrl) => {
  backendUrlInput.value = backendUrl;
});

saveButton.addEventListener('click', async () => {
  try {
    const backendUrl = new URL(backendUrlInput.value).origin;
    const backendOrigin = `${new URL(backendUrl).protocol}//${new URL(backendUrl).host}/*`;
    const hasPermission = await chrome.permissions.contains({ origins: [backendOrigin] });
    if (!hasPermission && !(await chrome.permissions.request({ origins: [backendOrigin] }))) {
      statusElement.textContent = 'Permission is required for this backend URL.';
      return;
    }

    await chrome.storage.local.set({ backendUrl });
    backendUrlInput.value = backendUrl;
    statusElement.textContent = 'Backend URL saved.';
  } catch {
    statusElement.textContent = 'Enter a valid backend URL.';
  }
});