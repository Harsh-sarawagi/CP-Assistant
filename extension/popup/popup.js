const statusElement = document.querySelector('#status');
const hintElement = document.querySelector('#hint');

function showDetectionState(problem) {
	if (!problem) {
		statusElement.textContent = 'No supported problem detected.';
		hintElement.textContent = 'Use a Codeforces problemset URL, not a contest URL.';
		return;
	}

	statusElement.textContent = `Problem ${problem.contestId}${problem.index} detected.`;
	hintElement.textContent = problem.url;
}

chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
	if (!tab?.id) {
		showDetectionState(null);
		return;
	}

	chrome.runtime.sendMessage({ type: 'GET_DETECTED_PROBLEM', tabId: tab.id }, (response) => {
		if (chrome.runtime.lastError) {
			showDetectionState(null);
			return;
		}

		showDetectionState(response?.problem || null);
	});
});
