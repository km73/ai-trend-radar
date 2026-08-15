# DESIGN·TANG — Design System Specification

Intelligence-grade, Material-3-architected dark/light design system for enterprise
decision software (Palantir AIP / Linear / Vercel lineage). This document is the
full reference; `tokens.css` is the drop-in implementation; `AGENTS.md` is the
short rule sheet; `palantir-design-system.html` is the living, interactive demo.

---

## 1. Principles
1. **Concept-first, not page-first** — model object / relation / action / permission, then UI.
2. **Density with legibility** — pack information; keep a 4px rhythm and clear type hierarchy.
3. **Colour = meaning** — status and object type carry colour; chrome stays desaturated.
4. **Motion is purposeful** — spring physics for layout, choreographed transitions, never decorative; always reducible.
5. **Tokens are the contract** — components never hardcode values; theming + diagram retheming depend on it.
6. **Accessible by default** — focus, contrast, ARIA, reduced-motion, keyboard are baseline, not extras.

---

## 2. Colour tokens

### Surfaces & foreground
| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#08080a` | `#eceef1` | app background |
| `--surf-lowest` | `#060608` | `#ffffff` | recessed |
| `--surf-low` | `#0d0d10` | `#f3f4f6` | subtle fill |
| `--surface` | `#111114` | `#ffffff` | default card |
| `--surf-high` | `#1a1a1f` | `#e8eaed` | raised |
| `--surf-highest` | `#222229` | `#e0e3e7` | highest |
| `--fg` | `#f2f2f0` | `#15161a` | primary text |
| `--fg-dim` | `#9a9aa0` | `#474952` | secondary text |
| `--fg-mute` | `#82828c` | `#6a6c76` | tertiary/label text (AA-tuned) |
| `--line` / `--line-strong` | rgba white .10/.22 | rgba ink .12/.22 | hairlines |
| `--outline` / `--outline-variant` | `#5b5b63` / `#2c2c33` | `#8b8d96` / `#c7c9d0` | borders |

### M3 roles (each has `-on-*`, `-container`, `-on-container`)
| Role | Dark base | Light base | Meaning |
|---|---|---|---|
| `--primary` | `#4c7dff` | `#2f55c8` | brand, primary action, selection |
| `--secondary` | `#3fb6a8` | `#0f6d62` | success / positive (`--ok`) |
| `--tertiary` | `#d99a3c` | `#7c5410` | warning (`--warn`) |
| `--error` | `#e5614c` | `#b3261e` | error / destructive (`--crit`) |
| `--ai` / `--ai-on` | `#7b68ee` / `#b8a9ff` | `#6a4fe0` / `#5a45c0` | **AI reasoning only** |

Dark containers: primary `#18294f`/on `#c9d6ff`; secondary `#0f3b35`/`#b8e8e0`;
tertiary `#46330f`/`#f3d9a6`; error `#4a1810`/`#f6cabf`.
Light containers: primary `#dde3ff`/`#0a1b4d`; secondary `#bdeee6`/`#00201c`;
tertiary `#ffdfae`/`#281800`; error `#f9dedc`/`#410e0b`.
Aliases: `--accent=--primary`, `--ok=--secondary`, `--warn=--tertiary`, `--crit=--error`.

### Diagram tokens (theme-flippable — use inside SVG `fill`/`stroke`)
`--d-stroke` `#3a3a40`→`#c8c9cf` · `--d-node` `#0f0f12`→`#ffffff` · `--d-node2` `#16161a`→`#f3f4f6`.

---

## 3. Type scale (15 steps · classes `.t-*`)
Sans = **Archivo** (prose, headings). Mono = **JetBrains Mono** (data, ids, labels, code).

| Class | Size | Weight | Notes |
|---|---|---|---|
| `t-display-l/m/s` | clamp 2.6–3.5 / 2.1–2.8 / 2.25rem | 800/700/700 | hero |
| `t-headline-l/m/s` | 2 / 1.75 / 1.5rem | 700/600/600 | section titles |
| `t-title-l/m/s` | 1.375 / 1 / .875rem | 600 | card/panel titles |
| `t-body-l/m/s` | 1 / .875 / .75rem | 400 | prose (auto `--fg-dim`/`--fg-mute`) |
| `t-label-l/m/s` | .78 / .7 / .64rem | 500 mono | UPPERCASE, letter-spaced eyebrows |

Constrain body copy to ~68ch measure. Numeric text → `font-variant-numeric: tabular-nums`.

---

## 4. Shape · spacing · elevation · state
- **Shape:** `--shape-none/xs(4)/sm(8)/md(12)/lg(16)/xl(28)/full(999)`. Cards md, chips/controls sm/xs, pills full.
- **Spacing (4px grid):** `--s1..s9` = 4/8/12/16/24/32/48/64/96px. Layout: `--sidebar 252px`, `--maxw 1180px`, `--grid 64px`.
- **Elevation:** `--elev-0..5` (dark uses stronger shadow; light softer). Prefer elevation only for raised/floating layers.
- **State layer:** add class `.state` → tonal `currentColor` overlay at `--state-hover .08 / -focus .10 / -press .12 / -drag .16`.

---

## 5. Motion

### Easing & duration (M3)
`--ease-standard` `(.2,0,0,1)` · `-decel` · `-accel` · `-emph-decel` `(.05,.7,.1,1)` · `-emph-accel` `(.3,0,.8,.15)`.
Durations `--dur-1..5` = 100/200/300/400/600ms.

### Spring presets (the core borrow) — overshoot beziers ≈ framer springs
| Token | Curve | For |
|---|---|---|
| `--spring-snappy` | `cubic-bezier(.34,1.36,.5,1)` | hover, select, toggles |
| `--spring-gentle` | `cubic-bezier(.22,1,.32,1)` | content + AI reveal, fade-in |
| `--spring-layout` | `cubic-bezier(.33,1.22,.4,1)` | panel slide / resize |
| `--spring-modal`  | `cubic-bezier(.3,1.2,.42,1)` | modal / focus enter |

**Hard rule:** layout/position → spring; **never** `transition: all .3s ease`. Transition named properties only.

### Choreography
- **Stagger** entering children 40–60ms apart (`transition-delay: i*60ms`, reveal on view).
- **Fade-through** panel swaps: old out (`opacity:0; translateY(-6px)`, ~140ms) → swap → new in via `--spring-gentle`.
- **Direction consistency:** forward = L→R / top→bottom; reverse on back.
- **Connector draw:** SVG lines animate `stroke-dashoffset: len → 0`; reset `stroke-dasharray:none` after.

### Reduced motion (REQUIRED)
CSS collapses transition/animation durations under `prefers-reduced-motion`. **JS must also gate** (typewriter → instant, streaming → no stepped delays, SVG draw → final state). See §8.

---

## 6. Components (all in the HTML reference)
- **Buttons:** `.btn` + variant `btn-filled / -tonal / -outlined / -text / -elevated`; add `.state`; ≥34px tall; disabled dims. Icon button `.iconbtn` 42px (needs `aria-label`).
- **Chips** (filter/assist/input, `aria-pressed`), **segmented controls** (`role="group"`), **switches/checkbox/radio**, **text fields** (focus = inset primary ring), **range slider**.
- **Containment:** cards `.ucard`, lists, badges, tags `.otag`.
- **Navigation:** fixed left sidebar (252px, scroll-spy, groups), mobile topbar + drawer.
- **Feedback overlays:** tabs, menus, **dialog** (`.dlg-scrim`/`.dlg`), **snackbar**, **focus-scrim** card.

---

## 7. Interaction prototypes (patterns to reuse)
| # | Pattern | Essence |
|---|---|---|
| Object explorer | entity → fields → relations → actions, fade-through on select |
| Decision workbench | 3-pane (queue / scene-view tabs / detail) + activity log; **draggable relationship graph** |
| Decision loop | clickable OODA+Learn ring, auto-tour |
| AI controlled actor | stepper with **human-confirm gate** before any write-back |
| Governance state machine | suggest→stage→submit→execute, **audit trail**, confirm dialog on execute |
| AI Chain-of-Thought | **signature**: vertical `--ai` timeline, typed streaming steps, type icons, pulse indicator, click-to-expand reasoning, speed control, **focus mode** |
| Talent review (applied) | composes all of the above end-to-end |

---

## 8. Reference snippets

**Spring micro-interaction**
```css
.card{ transition: transform .25s var(--spring-snappy), box-shadow .25s var(--spring-snappy); }
.card:hover{ transform: translateY(-2px); box-shadow: var(--elev-2); }
```

**Fade-through swap**
```js
function fadeSwap(el, render){
  el.style.transition='opacity .14s var(--ease-standard), transform .14s var(--ease-standard)';
  el.style.opacity='0'; el.style.transform='translateY(-6px)';
  setTimeout(()=>{ render(); requestAnimationFrame(()=>{
    el.style.transition='opacity .28s var(--spring-gentle), transform .28s var(--spring-gentle)';
    el.style.opacity='1'; el.style.transform='translateY(0)';
  }); }, 140);
}
```

**Modal focus trap**
```js
function trapFocus(container, e){
  if(e.key!=='Tab') return;
  const sel='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const nodes=[...container.querySelectorAll(sel)].filter(n=>n.offsetParent!==null||n.getClientRects().length);
  if(!nodes.length){ e.preventDefault(); return; }
  const first=nodes[0], last=nodes.at(-1), a=document.activeElement;
  if(e.shiftKey){ if(a===first||!container.contains(a)){ e.preventDefault(); last.focus(); } }
  else { if(a===last||!container.contains(a)){ e.preventDefault(); first.focus(); } }
}
// on open: remember activeElement, focus the primary control; on close: restore it.
// document keydown while open: Esc → close; else trapFocus(card, e).
```

**Tabs — roving tabindex + arrows (WAI-ARIA)**
```js
// markup: role="tablist" on wrapper; role="tab" aria-selected + role="tabpanel" on body.
function selectTab(b, focus){
  tabs.forEach(x=>{ const on=x===b; x.setAttribute('aria-selected', on); x.tabIndex = on?0:-1; });
  if(focus) b.focus(); render();
}
tab.addEventListener('keydown', e=>{
  const n=tabs.length;
  if(e.key==='ArrowRight'||e.key==='ArrowDown'){ e.preventDefault(); selectTab(tabs[(i+1)%n], true); }
  else if(e.key==='ArrowLeft'||e.key==='ArrowUp'){ e.preventDefault(); selectTab(tabs[(i-1+n)%n], true); }
  else if(e.key==='Home'){ e.preventDefault(); selectTab(tabs[0], true); }
  else if(e.key==='End'){ e.preventDefault(); selectTab(tabs[n-1], true); }
});
```

**Draggable SVG node (client→viewBox via CTM)**
```js
function toSvg(svg,x,y){ const p=svg.createSVGPoint(); p.x=x; p.y=y; return p.matrixTransform(svg.getScreenCTM().inverse()); }
// pointerdown on node → svg.setPointerCapture; pointermove → update cx/cy + connected line endpoints (clamped to viewBox).
```

---

## 9. Accessibility baseline (must pass)
- WCAG **AA** text contrast (≥4.5:1); UI borders ≥3:1. Greyscale ramp is pre-tuned.
- `:focus-visible` on everything (`.focus-haloed` on colour, `.focus-inset` in scrollers).
- Modals: `role="dialog" aria-modal`, focus move-in / trap / restore, Esc + backdrop close.
- Tabs: ARIA roles + roving tabindex + arrow keys.
- `prefers-reduced-motion` honoured in CSS **and** JS.
- Skip-to-content link; `<main id="main" tabindex="-1">`; icon buttons `aria-label`; targets ≥34px.
- `color-scheme` per theme; tabular numerals on data.

---

## 10. Constraints
- Self-contained HTML reference: all CSS/JS inline, fonts via `<link>`, SVGs inline, **no `localStorage`** (sandbox-safe).
- Dark is default (`:root`); light is `html[data-theme="light"]`. Convention: dark shows a sun toggle → switches to light.
- CSS `var()` resolves inside inline-SVG presentation attributes and in JS-built style strings — that's what lets the diagrams retheme live.
- Original assets; not affiliated with Google (Material) or Palantir — design language reference only.
