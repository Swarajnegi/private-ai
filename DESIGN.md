---
version: alpha
colors:
  canvas: "#060911"
  shell: "#090D16"
  surface: "#101724"
  surfaceRaised: "#151F30"
  border: "#222E41"
  text: "#F1F4FA"
  textMuted: "#9AA8BD"
  primary: "#459BFF"
  primaryBright: "#8FC5FF"
  danger: "#FF667C"
typography:
  body:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
    fontSize: "16px"
    lineHeight: "1.65"
  display:
    fontFamily: '"Bahnschrift", "Aptos Display", "Segoe UI", sans-serif'
    fontSize: "32px"
    lineHeight: "1.1"
  mono:
    fontFamily: '"Cascadia Code", "SFMono-Regular", Consolas, monospace'
    fontSize: "12px"
    lineHeight: "1.5"
rounded:
  control: "8px"
  panel: "12px"
  capsule: "999px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "24px"
  xl: "36px"
components:
  commandCard:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "{spacing.lg}"
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "{spacing.md}"
  statusCapsule:
    backgroundColor: "{colors.shell}"
    textColor: "{colors.primaryBright}"
    rounded: "{rounded.capsule}"
    padding: "{spacing.sm}"
---

# JARVIS Interface Design

## Overview

JARVIS is a private cognitive command workspace for one owner-operator. Its North Star is an aerospace mission console translated into a calm contemporary product: information is crisp, controls are restrained, and one animated cognitive core provides identity without competing with the work.

This is a product surface, not a marketing page. The September 13 reference supersedes the September 12 blue particle-cloud direction: the owner supplied a ten-second film clip of JARVIS assembling as a hollow amber circuit sphere, explicitly chose amber/gold, and requested complementary colours throughout the UI. The core now uses original procedural WebGL circuit paths, latitude bands, meridian rails, counter-rotating internal rings and moving signal nodes. The memorable signature is the hologram; restraint wins everywhere else. Three comfortable starter cards remain below its reserved stage. No old marketing slogans, overlapping copy, green dashboard, or decorative scanlines.

The existing CSS custom properties are the runtime source of truth. This file mirrors their accepted semantic values and explains their use; it does not generate CSS.

## Colors

The interface is dark-only: near-black and dark navy surfaces, white primary text, and muted blue-grey metadata. The owner's final September 13 direction keeps electric blue for interface controls, focus, selection, links, status, system pulse and the connection dialog. Amber is reserved for the hologram, brand emblem, favicon and core-caption indicator. The hologram approaches pale gold at its signal peaks. Red remains semantic only: disconnected, failed, denied, or destructive. This supersedes the briefly considered all-amber interface.

No green status styling, multicolour gradients, or decorative glow fields. Glow is limited to the cognitive core, its brand emblem, and active send or thinking states.

## Typography

Segoe UI Variable is the native Windows-first body family; Bahnschrift gives headings a precise engineered character. Both have platform-safe fallbacks and require no third-party font requests. Body baseline is 16px, conversation content 17px with generous line-height, main heading 26–36px. Important actions are 14–16px. Nonessential instrumentation may be 10–12px; never use that scale for answers. Uppercase mono labels are sparse while task labels remain sentence case.

No important content may rely on truncation without a title, export, or full-detail path. Full JARVIS answers remain selectable and uncut.

## Layout

The desktop shell uses a 276px conversation rail, a flexible central workspace, and a hidden-by-default system inspector. A short left-aligned greeting introduces a centered hologram stage; three equal, comfortably sized starter cards span its full width underneath. The core owns its geometry and cannot overlap copy. The composer remains anchored underneath the independent conversation scroller.

At narrower widths the inspector becomes an overlay, then the conversation rail becomes a drawer. The command deck collapses to one column and every action remains visible. Each active panel owns its own scroll; the composer stays stable while long conversations scroll above it.

## Elevation & Depth

Depth comes from border contrast, slight surface luminance changes, and restrained shadows. Static panels do not float gratuitously. Active controls may gain a small blue edge or shadow. Backdrop blur is limited to shell chrome and overlays where content visibly passes behind them.

## Shapes

Panels and substantial controls use 12px radii; compact controls use 8px. Status indicators may use capsules. Circular geometry belongs to the cognitive core, avatars, and the send action only. Avoid rounded cards nested inside rounded cards.

## Components

The command cards use the shared surface, border, and focus tokens above. The first action may carry stronger hierarchy, but all three remain genuine buttons with clear hover, active, focus-visible, and keyboard behavior.

The composer is the primary work control. The system status reports connection state truthfully. The inspector is a dock on wide displays and an explicit overlay below 1500px; it always begins below the top bar and is closed by default.

Motion is state-driven: 1,150 seeded circuit routes assemble over approximately three seconds into a hollow sphere, breathe and rotate, with counter-rotating inner circuits and travelling signals. Landing scroll changes its viewing tilt. A smaller 240-route core accompanies actual pending requests, with faster rotation and signals; the hero disappears during conversations. Both share one renderer. Animation is capped at 30fps, stops in hidden tabs, respects reduced-motion preferences, and has a pause control. Canvas resolution is capped at 2x. Entry transitions use opacity and short vertical translation. WebGL failure shows a static amber fallback; context restoration rebuilds GPU resources. No clip or soundtrack is bundled.

## Do's and Don'ts

- Do make the next action obvious within two seconds.
- Do use blue for interaction, amber for the hologram and its identity accents, and red only for genuine problems.
- Do keep body copy at 16px or larger and telemetry at 11px or larger.
- Do preserve full conversation history and full-length answers.
- Do render the full styled design if opened from disk, with a clear preview-only notice and no API calls.
- Don't use green terminal styling, tiny pseudo-technical labels, or gratuitous scanlines.
- Don't place the cognitive core over text or controls.
- Don't use a centered slogan as the empty-state hierarchy.
- Don't add decorative cards, badges, or glow merely to look futuristic.

## Runtime token mapping

`app.css` is authoritative; this document mirrors it. Canvas maps to `--bg`, shell to `--shell`, surface to `--surface`, surfaceRaised to `--raised`, border to `--line`, text to `--text`, textMuted to `--muted`, primary to `--blue`, primaryBright to `--bright`, danger to `--red`. Display/body/mono map to `--display`, `--body`, and `--mono`. The renderer reads normalized RGB triples `--core-gold` (1 .48 .055) and `--core-hot` (1 .88 .52) directly from the stylesheet. Semantic ownership and recovery behavior live in `UX-CONTRACT.md`.
