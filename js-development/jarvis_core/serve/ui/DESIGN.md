# JARVIS desktop workspace

## Scope and appearance

Desktop-only visual rebuild, September 14, 2026. The user explicitly chose localhost only;
do not publish this surface or its conversations to Sites or Railway. The regular bookmark
is http://127.0.0.1:8756/ and requires the local hearth. No new frontend build step or CDN.

The active entry point loads `desktop.css`, `hologram.js`, `app.js` and `desktop.js`.
The former `app.css` and `core.js` are no longer loaded by this entry point.
The existing authenticated conversation/SSE contracts remain in `app.js`.

- Near-black navy surfaces, electric-blue controls and telemetry, white readable text.
- Amber/gold belongs to the core, its ambient illumination and thinking/speaking states.
- Red indicates errors, failed jobs and unavailable connections.
- Segoe UI for reading, Bahnschrift for headings, Cascadia Code/Consolas for small metadata.
- The system panel is an on-demand overlay, not a permanent column squeezing the core.
- No phone-specific redesign. Desktop layouts tested at 1920×900, 1536×864, 1280×720,
  and 1100×700 CSS pixels. Very short viewports can scroll the main content.

## Hologram

The supplied film clip was inspected at multiple timestamps. Its key features are a hollow
amber sphere, broken shell bands, luminous circuit traces, radial fibres and internal rings.
`hologram.js` recreates those features procedurally in WebGL, not as a movie background or a
flat GIF. It is an interpretation, not the original film's VFX asset or an exact reconstruction.

Every core instance shares the same deterministic geometry and shaders. Idle motion breathes
and rotates; thinking increases activity; optional browser read-aloud drives speaking and word
energy. The square CSS viewport plus aspect-correct projection prevent an oval globe.
Rendering is capped at 30fps and device pixel ratio 2, pauses when the tab is hidden, supports
reduced motion and an explicit pause control, and handles WebGL context loss/recovery.

`Listen` uses the browser's speech-synthesis voice, not the movie voice. Speech availability
depends on the browser/OS. It is opt-in, stops on new conversation/send, and never alters the
stored answer. Voice errors remain visible; text is always available.

## Truthful system state

Health checks run every five seconds while visible, with at most one outstanding probe.
Each visible waveform represents an actual successful health response; blue is healthy,
amber is busy and red is a failed background job. The panel shows measured HTTP response
latency, not invented CPU load, neural activity or model latency. Failed checks stop adding
beats and explicitly mark telemetry unavailable. An in-flight answer is not declared dead
just because a health check failed. Failed job states include both `error` and `FAILED` forms.

## Interaction and verification

The dark searchable model dialog uses the existing model options as its source of truth.
It supports keyboard navigation, selection persistence, focus restoration and Escape.
It does not change provider entitlements, pricing, model caps or backend reasoning behavior.

`node scripts/verify_hearth_ui.cjs` runs an isolated local fixture with Playwright. It makes
no real model calls and writes no JARVIS conversations. Regression coverage includes auth,
complete long Markdown and raw answers, XSS handling, split SSE/Unicode, history ordering,
session continuity, exports, drafts, busy recovery, model selection, desktop geometry,
animation/pause, WebGL recovery, and healthy/degraded/offline/reconnected telemetry.

`node scripts/verify_jarvis_desktop.cjs` additionally reads the real local hearth and a saved
conversation, using the local token without logging it. Screenshots go to ignored
`artifacts/jarvis-ui/` on E:. Playwright must be installed or supplied through `NODE_PATH`.
