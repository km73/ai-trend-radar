# AGENTS.md — Building UI with the DESIGN·TANG system

> Drop this at your repo root (also works copied to `CLAUDE.md` or `.cursorrules`).
> Pair it with `tokens.css` (import it) and `design-system.md` (full reference).
> Open `palantir-design-system.html` to *see* every pattern working.

You are building an **intelligence-grade enterprise UI** — the visual language of
Palantir AIP / Linear / Vercel: dark-first, dense-but-legible, desaturated
"instrument panel," motion that is purposeful (never decorative). Default theme is
**dark**; a **light** theme ships in parallel. Follow the rules below exactly.

---

## 1. Tokens — never hardcode
- Import `tokens.css`. Reference **every** colour, space, radius, shadow, duration
  and easing as `var(--token)`. Do **not** write raw hex/px in components.
- This is non-negotiable for two reasons: (a) theme switching works only through
  tokens; (b) inline-SVG diagrams retheme only if their `fill`/`stroke` use `var()`.
- Colour = meaning, not decoration. Use the **M3 role** that fits:
  `--primary` (brand/primary action), `--secondary`, `--tertiary`, `--error`,
  each with `-on-*` (text on it) and `-container` / `-on-container` (tonal fill).
  Aliases: `--ok --warn --crit`. Surfaces: `--bg < --surf-low < --surface < --surf-high`.
- `--ai` (purple) is **reserved for AI reasoning/agent UI only** — don't use it as a general accent.

## 2. Motion — spring, choreographed, reducible
- **Layout/position changes use a spring.** NEVER `transition: all .3s ease`.
  Use the spring tokens: `--spring-snappy` (hover/select/toggle),
  `--spring-gentle` (content & AI reveal / fade-in), `--spring-layout` (panel
  slide/resize), `--spring-modal` (modal/focus enter). Transition only the
  properties you mean (e.g. `transition: transform .25s var(--spring-snappy)`).
- **Choreography:** stagger entering children 40–60ms apart; swap panel content
  with **fade-through** (old out `opacity:0; y:-6px` ~140ms → new in via
  `--spring-gentle`); keep forward motion left→right / top→bottom, reverse on back.
- **Honour `prefers-reduced-motion`.** CSS in `tokens.css` already collapses
  transitions/animations. You MUST also gate JS-driven motion:
  ```js
  const REDUCE = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // typewriter → render text instantly; auto-play/streaming → no stepped delays;
  // SVG draw-in (stroke-dashoffset) → set final state immediately.
  ```

## 3. Accessibility — production baseline (ship it)
- **Focus:** every interactive element needs a visible `:focus-visible` ring.
  Use the helper classes from `tokens.css`: `.focus-haloed` for buttons/chips on
  coloured backgrounds (ring + 4px halo); `.focus-inset` for rows/nodes inside
  `overflow:hidden` scrollers (inset ring so it isn't clipped).
- **Contrast:** body/secondary text meets WCAG **AA (≥4.5:1)**; UI borders ≥3:1.
  The `fg → fg-dim → fg-mute` ramp is already AA on every surface — keep text on
  tokens, don't invent lighter greys.
- **Modals/overlays** must: set `role="dialog" aria-modal="true"` (+ label),
  move focus in on open, **trap Tab** inside, restore focus on close, close on Esc
  and backdrop click. (See `trapFocus()` pattern in `design-system.md`.)
- **Tabs** follow WAI-ARIA: `role="tablist"`/`tab`/`tabpanel`, roving `tabindex`
  (only the selected tab is tab-focusable), Arrow/Home/End move + activate.
- **Targets:** interactive controls ≥34px tall. Provide `aria-label` on icon-only buttons.
- Add a **skip-to-content** link; give `<main id="main" tabindex="-1">`.

## 4. Formatting / polish
- Set `color-scheme` per theme (in `tokens.css`) so native scrollbars/controls match.
- Use `font-variant-numeric: tabular-nums` on all numeric/data text (`.mono`,
  tables, KPIs, %, ids, timestamps) so digits align.
- Monospace (`--mono`) for data, ids, code, labels, timestamps; sans (`--sans`) for prose.
- Type via the `.t-*` scale (e.g. `.t-headline-m`, `.t-body-l`, `.t-label-m`). 4px spacing grid.
- Minimal chrome: thin `--line` separators, restrained shadow, generous space over boxes.

## 5. Signature patterns (reference implementations in the HTML)
- **AI Chain-of-Thought timeline** — vertical, left `--ai` rail, typed step
  descriptions streaming one-by-one, type icons, pulsing "thinking" indicator,
  per-step click-to-expand full reasoning. Speed control (slow/normal/fast/instant).
- **Focus mode** — dims+scales the page behind a centred card (`--spring-modal`).
- **Fade-through** content swaps on every detail/tab change.
- **Draggable relationship graph** — pointer-drag SVG nodes (`getScreenCTM`),
  connector lines draw in via `stroke-dashoffset`.
- **State machine / governance** with audit trail; **human-confirm gate** before
  any AI write-back; **object explorer** (entity → fields → relations → actions).

## 6. Definition of done (checklist)
- [ ] No raw hex/px — all via tokens; works in both dark & light.
- [ ] Layout motion uses spring tokens; nothing uses `transition: all ease`.
- [ ] `prefers-reduced-motion` respected in CSS **and** JS.
- [ ] Every control has a visible focus ring; modals trap focus + Esc/restore.
- [ ] Tabs use ARIA + roving tabindex; icon buttons labelled; targets ≥34px.
- [ ] Text ≥AA contrast; numeric text uses tabular figures.
- [ ] No `localStorage`/`sessionStorage` if the artifact runs sandboxed.
