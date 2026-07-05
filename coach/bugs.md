# CoachHub Hockey — Bug Tracker

Status legend: OPEN → IN PROGRESS → READY FOR VERIFY → COMPLETE
(COMPLETE = fix implemented, tested, and browser-verified.)

---

## BUG-1 — Selected player is not assigned to an empty lineup slot (mobile Formace)

- **Severity:** HIGH
- **Area:** Mobile Formations / Lines editor (`static/lines_mobile.js`)
- **Status:** COMPLETE
- **Symptom:** On a phone, tapping an empty slot opens the player picker; tapping a
  player closes the sheet but the player is NOT placed in the slot.
- **Root cause:** `assign()` placed the player by calling `activeSlot.click()` to
  reuse lines.js tap-to-assign. The mobile controller's own capture-phase document
  click listener intercepted that synthetic slot click first, called
  `e.stopPropagation()` + `openPicker(slot)`, so lines.js `placeInto` never ran and
  the picker just re-opened (then `closePicker()` closed it). Net: no assignment.
- **Fix:** added a `placing` guard flag set around the programmatic `target.click()`
  in `assign()`; the capture-phase interceptor early-returns while `placing` is
  true, so the placement click reaches lines.js `placeInto`. (`static/lines_mobile.js`)
- **Verification (headless browser, DB-safe temp DB):**
  - Before: pick player → `hidden.value=""`, `fill=false` (not assigned).
  - After: pick player → `hidden.value="1"`, `fill=true`, name shown in the slot,
    sheet closes (`display:none`, `visibility:hidden`), validation updates
    (`2. lajna je neúplná (1/5)`).
- **Remaining verify step:** confirm on a real phone (touch) that tap-to-assign,
  clear-slot, and save all behave.

---

## BUG-2 — Team search does not filter the team selector (mobile login)

- **Severity:** HIGH
- **Area:** Team key login (`templates/team_auth.html`, `static/app.js`)
- **Status:** COMPLETE
- **Symptom:** On a phone, typing in "Najdi svůj tým" does not narrow the "Tým"
  dropdown; all teams remain listed in the native picker.
- **Root cause:** the filter set `option.hidden = true` on non-matching `<option>`
  elements. Desktop browsers honor `<option hidden>` (repro confirmed: only the
  matching option had `hidden=false`), but native `<select>` pickers on mobile
  (iOS/Android) IGNORE `hidden`, so the dropdown stayed unfiltered on phones.
- **Fix:** filter by removing/re-adding option elements in the DOM (native pickers
  respect DOM presence) instead of toggling `hidden`; the full option list is
  cached once, matching options are re-appended in original order, the placeholder
  is always kept, and the current selection is preserved when still present.
  (`static/app.js`)
- **Verification (headless browser, DB-safe temp DB, 5 teams):**
  - `q="spar"` → DOM options = 2 (`Vyber tým…`, `HC Sparta`).
  - `q="hc"`  → DOM options = 5 (4 HC teams, `TMP One` excluded).
  - `q=""`    → DOM options = 6 (all restored, original order).
- **Remaining verify step:** confirm on a real iOS/Android device that the native
  `<select>` picker now shows only the matching teams.

---

## BUG-3 — Low-contrast mobile input text (light text on white fields)

Covers these reported symptoms (same root cause, shared fix):

- Search text not visible — Docházka (`.tam-search`, `.pam-sheet-search`)
- Search text not visible — Hráči (`.plm-search`)
- New player name field text not visible — Hráči / Nový hráč (`.plm-fld input`)
- Search text not visible — Soupiska (`.rom-search`)

- **Severity:** MEDIUM (usability)
- **Area:** `static/mobile.css` (mobile input styling)
- **Status:** COMPLETE
- **Root cause:** these inputs set `background: var(--field-bg)` (= `#ffffff`, white)
  but `color: var(--text)` (= `#eef4fb`, near-white) → white text on white field.
- **Fix:** change `color: var(--text)` → `color: var(--field-text, var(--text))`
  (`#111418` dark) on the affected input rules; add autofill handling for the name
  field. Placeholder inherits dark-at-reduced-opacity (readable); caret follows the
  dark color (visible). Scoped to mobile (`@media <=768px`); desktop untouched.

---

## BUG-4 — Import-attendance upload form text not visible (Nastavení → Import docházky)

- **Severity:** MEDIUM
- **Area:** `templates/attendance_import.html` upload form + `static/mobile.css`
- **Status:** COMPLETE
- **Root cause:** the upload form has an inline white background
  (`style="…background:var(--field-bg);"`) but its `<label>` and file input inherit
  the page's light `--text` → invisible on white.
- **Fix:** scoped mobile rule (`main:has(> .aim-bar) form[enctype]`) sets the upload
  form's text to `var(--field-text)`; desktop unchanged (frozen, out of scope).

---

## BUG-5 — Info popup (Nápověda) titles not visible on mobile

- **Severity:** MEDIUM
- **Area:** shared help modal (`.help-dialog`), fixed via `static/mobile.css`
- **Status:** COMPLETE
- **Root cause:** `.help-dialog` sets `color: var(--field-text)` (dark) on a white
  background, but the global rule `h1,h2,h3,…{ color: var(--text) }` (style.css)
  DIRECTLY targets the title `<h3>` and beats the dialog's inherited color (direct
  rule > inheritance) → light title on white dialog.
- **Fix:** scoped mobile rule `.help-dialog h1..h4 { color: var(--field-text) }`
  (higher specificity than the global heading rule), `@media <=768px`. Does not
  use team colors; body text already dark. `help.css`/`style.css` NOT edited.

---

## BUG-6 — Formace color controls not aligned consistently (mobile)

- **Severity:** LOW (visual)
- **Area:** `static/mobile.css` (`.lines-colorpick` under mobile Formace)
- **Status:** COMPLETE
- **Root cause:** `.lines-colorpick` is `display:flex; flex-wrap:wrap` with two
  variable-width `<label>`s ("Podklad" vs "Text") → controls have unequal widths
  and don't align.
- **Fix:** scoped mobile grid (`repeat(auto-fit, minmax(...,1fr))`) so the two
  controls are equal-width, side-by-side when space allows, wrapping to two rows
  with the same start x / equal width at narrow widths. Color behavior unchanged.

---

## BUG-7 — Docházka matrix header cell content clipped (mobile)

- **Severity:** MEDIUM
- **Area:** `static/mobile.css` (`.am-grid --am-hhead`)
- **Status:** COMPLETE
- **Root cause:** `.am-hcell` has `height: var(--am-hhead)` with `overflow:hidden`;
  style.css sets `--am-hhead: 58px` on mobile, too short for the 4 stacked lines
  (kind/date, title, count, progress bar) → count/bar clipped.
- **Fix:** override `--am-hhead` on mobile (`.am-grid`) so the header row is tall
  enough. Uses the grid variable → only the header row grows; player rows
  (`--am-row`) unchanged. `style.css` NOT edited.

---

## BUG-9 — Attendance event cells not aligned with player rows (mobile, Docházka → Tabulka)

- **Severity:** HIGH (data can appear beside the wrong player)
- **Area:** `static/mobile.css` (`.am-grid` matrix row sizing)
- **Status:** COMPLETE
- **Symptom:** On a real phone, the fixed player-name column and the scrollable
  event columns do not share row heights; attendance markers drift down the table
  and can appear next to the wrong player.
- **Root cause:** mobile.css gave the fixed player column a **one-sided**
  `.am-lcell { min-height: 52px }` (to fit the 2-line name + %/position metadata),
  but the scrollable event side (`.am-mrow`/`.am-cell`) kept the shared
  `--am-row` (42px). Both sides read `height: var(--am-row)` from style.css, so the
  left rows rendered 52px and the right rows 42px → 10px cumulative drift per row.
- **Fix:** drive BOTH panes from the single shared `--am-row` variable on mobile
  (`.am-grid { --am-row: 52px }`) and remove the one-sided min-height; center the
  marker in the (now equal-height) event cell. Header keeps its own separate
  `--am-hhead`. Scoped to `@media <=768px`; `style.css` NOT edited.

---

## BUG-8 — Footer links covered by fixed bottom navigation (mobile, all screens)

- **Severity:** MEDIUM
- **Area:** `static/mobile.css` (`.app-footer` spacing)
- **Status:** COMPLETE
- **Root cause:** `.app-footer` is in normal flow after `<main>`, but the `.mnav`
  bottom nav is `position:fixed; bottom:0` and overlays it on mobile.
- **Fix:** one global mobile rule adds `padding-bottom` = mnav height + safe-area to
  `.app-footer`, gated by `body:has(.mnav)` so logged-out pages (no mnav) get no
  extra space. Desktop footer unchanged.

---
