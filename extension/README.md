# CP Assistant profile extension

Chrome 114+, Manifest V3. Vanilla JavaScript, isolated Shadow DOM, no external scripts.
Injection matches only `https://codeforces.com/profile/*`; the content script further
validates the exact path and handle. Problem pages and contest pages are unsupported.

## Tabs and automatic behavior

- Overview: public rating/rank summary, vertical bars of distinct solved questions per rating,
  a topic pie chart with counts/percentages, rating history and regression estimates. Pie shares
  represent solved-topic assignments because one problem can have several tags.
- Weaknesses: final verdict counts/percentages, evidence thresholds, explainable topic
  scores, repeated-attempt signals, and focus topics. No inferred coding root causes.
- Practice: 5–10 deterministic candidates where available. Only the explicit AI plan
  button calls Groq; opening or switching tabs never does.
- Notes: the connected Django user's personal notebook, not the viewed handle's notes.
  Create/edit/delete, search, filter by topic, latest-update order, and pagination.

Only Overview is visible on public/other profiles. Weaknesses, Practice and Notes appear
only when the connected Django account's saved Codeforces handle matches the viewed profile,
case-insensitively. Without a saved handle, the panel offers profile settings. This controls
presentation; private notebook APIs still enforce Django ownership independently.

Public analytics load automatically once per profile. Tab switches reuse the bundle.
Profile navigation resets analytics and discards old in-flight results. Preferred
collapse state is saved locally. Disconnect/account changes clear personal UI data, and late
notebook/AI responses are discarded after a profile or account change. Keyboard tabs support arrows, Home, and End.

## Setup

1. Start the Django application and apply migrations.
2. Load this directory unpacked in Chrome Developer mode.
3. Set `EXTENSION_ALLOWED_ORIGIN=chrome-extension://<actual-id>` in the backend's local
   environment (no angle brackets), or add the ID to `EXTENSION_ALLOWED_IDS`. Restart Django.
4. Open extension Options; set the backend URL and grant host access when requested.
5. Visit a Codeforces profile. No account is needed for Overview. Save your own Codeforces
   handle on the Django profile settings page to enable your personal tabs after connecting.
6. Click Connect Account. Login/register on the Django website, then review and approve
   the consent page. This identifies the extension ID and requested permissions.
7. The worker verifies state and the exact chromiumapp callback, exchanges a single-use
   code with PKCE S256, then stores authorization in trusted-context-only local storage.

Only `storage` and `identity` are requested. There is no cookies, tabs, or identity.email
permission. No client secret is embedded. Default loopback backend host access and
optional HTTPS host permission support development and an explicitly chosen production backend.

## Connection lifecycle

The service worker holds all token-bearing operations. Content messages are accepted only
from this extension's profile content script in the top frame, or its popup/options.
There is no generic privileged fetch bridge. A viewed handle is never authentication.

Access credentials last 10 minutes. Refresh rotates on each renewal and server-side reuse
revokes the grant family. Authorization lasts at most 30 days. Local authorization is
bound to the configured backend origin, restores on restart, and is cleared on revocation
or backend change. Tokens never enter Codeforces DOM, content-script messages, or logs.
Changing backend clears local authorization; use the old website to revoke an old grant.
Website session logout is separate from extension disconnect/revocation.

Use Disconnect in the popup/panel, or revoke from the website's Extension Connections page.
If a network failure prevents confirming remote revocation, local credentials are still
removed; revoke through the website when it is reachable again.

## Manual Chrome verification

See the complete checklist in [the report](../PROFILE_ASSISTANT_REPORT.md). Restart Django
after environment changes; reload the unpacked extension and existing Codeforces tabs.
Opening a profile can call Codeforces through Django but must never call Groq. Generating
an actual AI plan spends provider credits; obtain approval before that live test.

```powershell
node --test extension/tests/extension.test.cjs
```

These tests mock Chrome/DOM/network APIs. Passing them is not proof of a real Chrome
authorization popup, callback, browser restart, layout, or provider inference.
