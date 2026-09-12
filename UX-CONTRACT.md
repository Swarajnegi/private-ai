# JARVIS frontend interaction contract

The hearth API and persisted conversations are the source of truth. The UI is a client, not another memory store. This contract records existing behavior retained by the September 2026 redesign. No conversation deletion or editing endpoint is invented.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | Native select and datalist in serve/ui/index.html | Model/reasoning/tools request fields in hearth.py | Platform-owned popup geometry is accepted; no custom listbox | Configure via keyboard; default and explicit model |
| Form | serve/ui/app.js connect and submit | Hearth token verification and /v1/ask | Connection form and message composer; native novalidate, visible errors, duplicate-submit guard | Wrong token, valid token, busy recovery, restored draft |
| Scrollbar | serve/ui/app.css global rules | DESIGN.md and runtime tokens | Conversation, sidebar, dialog, code/table overflow | Desktop, narrow viewport, long answer, forced-colors fallback |
| Toast | app.js toast and #toast | Action outcomes | Nonblocking feedback for copy, export, busy navigation | Keyboard activation and announced status |
| Conversation navigation | app.js openSession/newSession | /v1/sessions and /v1/sessions/{id} | Latest activity first; timestamp preferred over copied file mtime | Fixture ordering plus backend T32 |
| Response display | app.js renderMessage/renderMarkdown | Full saved content and final SSE answer | Formatted, raw, clipboard, Markdown download; never truncate answer | Long Unicode response and final marker after reload |
| Core motion | serve/ui/core.js | Busy state, visibility, reduced-motion preference | Hero and compact thinking renderer | Pause/play, new conversation mount, responsive canvas |

Search filters loaded metadata locally, has an explicit clear control, and returns focus after clearing. Session loads discard stale results; in-flight asks prevent navigation and duplicate sends. API errors remain visible and preserve the question draft. A failed health probe during a pending request must not falsely report a disconnected hearth.

Connection credentials are masked with a reveal control and kept only in session storage. The native dialog provides modal focus containment and Escape. Token validation uses aria-invalid and its existing error description. Export/copy preserve the source verbatim; Markdown allows only sanitized tags and safe link schemes.

The desktop rail becomes a mobile drawer. The system inspector is optional and begins below the header. Each scroll region owns its content without clipping answers. There is no fake voice button, destructive action, or made-up model response.

## Verification entry points

- `python -m jarvis_core.serve.hearth` with `PYTHONPATH=js-development`: backend offline smoke tests.
- `node scripts/verify_hearth_ui.cjs`: isolated browser regression with fake data, no model calls.
- `JARVIS_UI_FIXTURE_PORT=8766 node scripts/verify_hearth_ui.cjs`: same disposable fixture for computer-use browser verification when standalone browser launch is restricted.
- Strict premium audit is supplementary: its HTML-only action detector cannot resolve listeners assigned by the external app.js. Actual controls must be exercised in a browser; false static findings must not be hidden with dummy handlers.
