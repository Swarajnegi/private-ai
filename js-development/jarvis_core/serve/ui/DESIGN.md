# JARVIS observatory — desktop design and operation

## Scope and direction

Rebuilt September 26, 2026. Localhost only: http://127.0.0.1:8756/. No Sites or Railway deployment.
The Austensor homepage and Quantum/page8 informed the full-screen particle scene, compact
navigation, quiet corner labels and dimensional motion. Original Three.js geometry and shaders
implement the reference direction; no third-party site code or VFX assets are copied.

One persistent amber-gold core lives behind the workspace. Conversation opens beside it;
history, model selection, connection and system activity are on-demand overlays. Black surfaces,
white reading text, electric-blue interaction, amber core/state, red errors. Space Grotesk and
IBM Plex Mono are bundled locally. Main message text is 17px; primary controls are 14px.
Desktop sizes 1920×1080, 1536×864, 1280×720 and 1100×700 are the supported verification targets.

## Source and build

Source: `serve/frontend/`. Generated delivery assets: `serve/ui/index.html` and `serve/ui/assets/`.
From frontend: `npm ci`, then `npm run build`. The generated assets are committed so normal
Git handoff needs no Node installation to open JARVIS. Edit source, never the generated bundle.
No runtime CDN, third-party font request, or cloud frontend service is required.
Superseded app/desktop/core/hologram scripts and styles have been removed.

The hearth serves the assets and existing authenticated API. Frontend `api.ts` owns transport;
`main.ts` owns navigation/conversation state; `scene.ts` owns graphics; `voice.ts` owns browser
audio. The backend remains the authoritative conversation store. The UI imposes no reply-length
truncation or model reasoning caps. User-selected paid models use the existing provider balance.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native select for finite request settings; searchable dialog for models | main.ts; /v1/models | Free/paid groups, filtered empty state | verify_hearth_ui.cjs |
| Form | main.ts native form, application validation | hearth API and session draft | Composer, token connection | browser auth/send/failure checks |
| Scrollbar | style.css global standards properties | shared tokens | Message, dialog and code overflow | desktop geometry checks |
| Toast | main.ts toast() | transient action result | Copy and nonblocking failure | browser action checks |
| CRUD | main.ts session navigation and submit() | /v1/sessions and /v1/ask | New/resume/export; no delete control | full saved and streamed replies |

Both markup and programmatic listeners are in main.ts. The premium static auditor only recognizes
inline button handlers, so it reports externally bound buttons as actionless; these are verified
by browser tests. Do not add empty inline handlers to satisfy a lexical check. Native request
select ownership is deliberate; the model catalog uses a dark searchable dialog.

## Motion and performance

Perspective aspect follows the actual canvas dimensions; the core is never stretched to fill
a panel. Orbit, zoom, keyboard rotation/reset, breathing, listening amplitude, thinking energy
and actual speech amplitude all reuse the same scene. Adaptive quality reduces 50,000 particles
to 32,000 and limits pixel ratio/frame rate when sustained rendering is slow. Hidden tabs pause
rendering; reduced-motion preference and the pause control stop autonomous motion. WebGL failure
leaves the text workspace usable.

## Local voice

Run `powershell -ExecutionPolicy Bypass -File scripts/setup_voice.ps1` once per Windows machine.
The installer uses this repo's E: location for dependencies, models, cache and temporary audio:
`.runtime/voice/` and `.venv-voice/`, both ignored. whisper.cpp base handles transcription;
Piper en_GB-alan-medium handles synthesis. Model/voice license information stays with the download.
No browser SpeechRecognition or cloud speech fallback is used. The normal LLM request still
uses JARVIS's configured model provider, including when its input was spoken.

Click the microphone to start; click again to finish, review the transcript and send.
Hands-free starts only on explicit selection, submits after a pause in speech, reads the answer,
then resumes listening. End voice, navigation away, or hiding the tab stops capture/playback.
Thirty seconds of silence ends hands-free capture. Individual recordings last at most two
minutes; long answers are spoken in consecutive chunks without truncating their stored text.
These are audio transport limits, not model intelligence limits.

Voice workers run one at a time in short-lived subprocesses, with timeouts and temporary-file
cleanup. Low Windows commit memory refuses a new voice worker visibly. Text remains usable.
Microphone permission and the user's physical microphone/speaker quality require a real user
check; automated tests do not pretend to validate that hardware.

## Truthful state and failure handling

Health samples run every five seconds while visible, one request at a time. The pulse encodes
measured hearth HTTP response latency and job status, never invented CPU or neural telemetry.
A failed check clears stale metrics; a failed scheduled job says needs attention. Health failures
do not silently cancel an in-flight answer. The response stream can be disconnected with Stop
waiting; this does not promise cancellation of backend generation. Check history before retrying.

Full Markdown/raw text, split SSE Unicode, draft recovery, model persistence, newest-first history,
export, token authentication and session continuity are preserved. Tokens remain in tab session
storage, never URLs. Untrusted response HTML is sanitized; embedded remote media is disabled.

## Verification

`node scripts/verify_hearth_ui.cjs` uses an isolated HTTP fixture and makes no real model calls
or conversation writes. It covers auth, free/paid picker, history ordering, full long Unicode
replies, raw rendering/XSS, split SSE, busy recovery, desktop bounds, motion control, health
recovery and unavailable local voice. Screenshots: ignored `artifacts/jarvis-ui/`.
Synthetic microphone/audio fixtures also verify transcript review, hands-free submission,
multi-chunk read-aloud, automatic return to listening and explicit stop. Growing multiline
composition is checked against the conversation bounds; exported replies retain their end marker.

`node scripts/verify_jarvis_desktop.cjs` reads the live hearth and a saved conversation using the
local token without logging it. `python -m jarvis_core.serve.hearth` checks ASGI contracts;
`python -m jarvis_core.serve.voice --self-test` checks malformed input and single-worker behavior.
Set PYTHONPATH=js-development for module commands from the repo root.

A synthetic local round trip produced “The local Jarvis voice test is complete.” in 30.4 seconds
on this laptop, including speech generation, resampling and transcription. This establishes
local worker functionality, not a promised interactive latency for every utterance.
