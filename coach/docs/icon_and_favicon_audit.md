# Icon & Favicon Audit — CoachHub Hockey

_Audit date: 2026-07-28. Read-only inspection; **no files were modified.**_
_Tools used: ImageMagick `identify`/`file`, Python Pillow 10.2.0, `stat`, `grep`, `find`._
_Paths are relative to the Flask package root `coach/` (repo root is its parent `/home/martin-snajdr/python`)._

---

## A. Executive summary

- **The browser-tab favicon is `coach/static/icon-192.png`** — a **192×192 PNG** referenced by `<link rel="icon" type="image/png">` in every base template, and also served for the legacy `/favicon.ico` URL by a Flask route.
- **There is no `.ico` file anywhere in the repo.** The `/favicon.ico` route (`blueprints/public.py`) returns the PNG `icon-192.png`. There is no `favicon.svg`, no `mask-icon`, no `browserconfig.xml`.
- **The icon looks small in the tab because of excessive transparent padding + a wide/short logo shape**, not caching or the wrong file. The actual visible logo inside `icon-192.png` is only **148×80 px — 32.1 % of the 192×192 canvas** (only **12 % of pixels are non-transparent**), with **56 px of empty transparent space on top and bottom** and a wide 1.85:1 aspect ratio. When the browser shrinks the whole 192-px canvas into a ~16 px tab slot, the already-small, letterboxed wordmark becomes tiny.
- **Contrast risk:** the visible logo is predominantly light gray/white (`~rgb(224,224,224)`) on a transparent background. It reads well on dark browser chrome but may be **low-contrast/near-invisible on a light/white tab bar**.
- **The favicon `<link>` tags carry no `?v=` cache-buster**, and the service worker (`coachhub-v6`) precaches and cache-firsts `/static/icon-192.png` by path. **Replacing the icon while keeping the same filename can therefore be served stale** until the SW `CACHE` constant is bumped and/or a query version is added.
- The PWA manifest is well-formed with four icons (any 192/512 + maskable 192/512). The maskable icons are correct (full-bleed, 100 % occupancy). Sizes are reasonable **except `App_Logo.png` (below), which is a header logo, not a favicon**.
- **Separate finding (not a favicon, but oversized):** `static/App_Logo.png` is **1024×1024, 1.41 MB**, yet displayed at only 44–64 px height in headers. Heavily oversized for its use.

---

## B. The exact currently active browser-tab favicon

| Property | Value |
|---|---|
| **Source file** | `coach/static/icon-192.png` |
| **Generated URL** | `/static/icon-192.png` (via `url_for('static', …)`); also reachable at `/favicon.ico` |
| **Referenced in** | `templates/base.html:23`, `templates/welcome.html:7`, `templates/team_auth.html:7`, `templates/429.html:7` (`<link rel="icon">`); `blueprints/public.py:15` (`/favicon.ico` route) |
| **Format / MIME** | PNG / `image/png` |
| **Declared `sizes`** | none declared on the `<link>` |
| **Actual dimensions** | 192 × 192, 8-bit RGBA, non-interlaced |
| **File size** | 15,767 bytes = **15.4 KB = 0.015 MB** |
| **Selectable for normal tabs?** | **Yes** — it is the only `rel="icon"` link; browsers use it for the tab |
| **Cache busting / versioning** | **None** — no `?v=` query on the link |

**Why this is the active one:** Every page that renders a `<head>` declares exactly one `rel="icon"` pointing at `icon-192.png`. There is no competing `.ico`, `.svg`, or second-size PNG link, so there is no ambiguity — the browser has only this candidate for the tab. (Owner pages are the exception: they declare **no** icon at all — see §7.)

---

## C. All favicon / icon references (full trace)

| # | Reference | File:line | Target file | URL | MIME | `sizes` | Tab-eligible? | Versioned? |
|---|---|---|---|---|---|---|---|---|
| 1 | `<link rel="icon" type="image/png">` | `templates/base.html:23` | `icon-192.png` | `/static/icon-192.png` | image/png | — | ✅ yes | ❌ no |
| 2 | `<link rel="apple-touch-icon">` | `templates/base.html:31` | `icon-192.png` | `/static/icon-192.png` | (png) | — | iOS home screen only | ❌ no |
| 3 | `<link rel="manifest">` | `templates/base.html:25` | `manifest.webmanifest` | `/static/manifest.webmanifest` | — | — | (PWA install icons) | ❌ no |
| 4 | `<meta name="theme-color">` | `templates/base.html:26`, `static/offline.html:6` | — | — | — | `#0e1116` | chrome color | — |
| 5 | `<link rel="icon">` | `templates/welcome.html:7` | `icon-192.png` | `/static/icon-192.png` | image/png | — | ✅ yes | ❌ no |
| 6 | `<link rel="icon">` | `templates/team_auth.html:7` | `icon-192.png` | `/static/icon-192.png` | image/png | — | ✅ yes | ❌ no |
| 7 | `<link rel="icon">` | `templates/429.html:7` | `icon-192.png` | `/static/icon-192.png` | image/png | — | ✅ yes | ❌ no |
| 8 | `/favicon.ico` Flask route | `blueprints/public.py:13-20` | **serves `icon-192.png`** | `/favicon.ico` | image/png (despite `.ico` URL) | — | ✅ legacy fallback | ❌ no |
| 9 | apple meta tags | `base.html:27-30` | — | — | — | — | iOS PWA chrome | — |
| — | `owner_base.html` | `templates/owner_base.html` | **none** | — | — | — | ⚠️ no icon declared | — |

Notes:
- No `rel="shortcut icon"`, no `rel="mask-icon"` (Safari pinned-tab), no `favicon.svg`, no `browserconfig.xml` (no Windows tile config) exist in the project.
- The `/favicon.ico` route returns a **PNG payload under an `.ico` URL**. Modern browsers accept this (they sniff content), but it is technically a MIME/extension mismatch and cannot carry multiple embedded sizes the way a real `.ico` could.

---

## D. All PWA / manifest icons

**Active manifest:** `coach/static/manifest.webmanifest` (linked from `base.html:25`; `start_url:/app`, `scope:/`, `display:standalone`, `theme_color`/`background_color` `#0e1116`).

| Icon | Declared size | Actual size | Match? | Format | Bytes | KB | MB | `purpose` | Content bbox | Padding | Used for |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `icon-192.png` | 192×192 | 192×192 | ✅ | PNG RGBA | 15,767 | 15.4 | 0.015 | `any` | 148×80 (**32.1 %**) | 22/56/22/56 px (L/T/R/B) | tab favicon, apple-touch, install icon |
| `icon-512.png` | 512×512 | 512×512 | ✅ | PNG RGBA | 79,042 | 77.2 | 0.075 | `any` | 388×206 (**30.5 %**) | 62/154/62/152 px | install icon, splash |
| `icon-maskable-192.png` | 192×192 | 192×192 | ✅ | PNG RGBA | 7,728 | 7.5 | 0.007 | `maskable` | 192×192 (**100 %**, full-bleed) | 0 | Android adaptive/home-screen |
| `icon-maskable-512.png` | 512×512 | 512×512 | ✅ | PNG RGBA | 36,313 | 35.5 | 0.035 | `maskable` | 512×512 (**100 %**, full-bleed) | 0 | Android adaptive, splash |

- **All declared sizes match actual pixel dimensions.** No `monochrome` purpose icons are declared.
- The **`any` icons are the same padded, transparent-background wordmark** as the tab favicon (30–32 % occupancy). The **maskable icons are correctly full-bleed** with an opaque (black) background — appropriate for Android's mask/safe-zone.
- File sizes are all reasonable for their pixel dimensions.

---

## E. Relevant logo / icon asset inventory

All raster; no SVG assets exist in the project. `.venv/...werkzeug` PNGs are third-party debug assets and excluded.

| Path | Format | W×H | Bytes | KB | MB | Transparency | Referenced where | Notes |
|---|---|---|---|---|---|---|---|---|
| `static/icon-192.png` | PNG RGBA | 192×192 | 15,767 | 15.4 | 0.015 | yes (88 % transparent) | tab favicon, manifest, apple-touch, `/favicon.ico` | **active favicon** |
| `static/icon-512.png` | PNG RGBA | 512×512 | 79,042 | 77.2 | 0.075 | yes | manifest, SW precache | large install icon |
| `static/icon-maskable-192.png` | PNG RGBA | 192×192 | 7,728 | 7.5 | 0.007 | opaque bg | manifest | maskable |
| `static/icon-maskable-512.png` | PNG RGBA | 512×512 | 36,313 | 35.5 | 0.035 | opaque bg | manifest | maskable |
| `static/App_Logo.png` | PNG RGBA | 1024×1024 | 1,474,734 | 1440.2 | **1.406** | yes | `base.html:56`, `welcome.html:18,95`, `team_auth.html:29` header brand | **⚠️ oversized:** displayed at 44–64 px (CSS `max-height:64px`), 1.4 MB source |
| `static/logo.png` | PNG RGBA | 717×549 | 157,225 | 153.5 | 0.150 | yes | **not referenced anywhere** (grep clean) | appears orphaned |

Other `static/*.png` (`branka`, `formace`, `rink`, `kalendar`, `soupiska`, `home_page`, `toolbar_priklad`, `treninkova_jednotka`, `tvorba_cviceni`, `ukazka_stranka`, `message_board`, `nastaveni`) are **welcome/help-page screenshots**, not icons — out of scope. `static/uploads/*` are per-team club logos (user uploads), never used as favicons.

---

## F. Actual vs declared dimensions

Every icon's **actual pixel size equals its declared `sizes`/filename** (192→192, 512→512). No mismatches.
The meaningful gap is **declared canvas vs. visible content**: the `any` icons declare 192/512 but fill only ~30–32 % of that canvas with visible pixels.

---

## G. File sizes (bytes / KB / MB)

| File | Bytes | KB | MB |
|---|---|---|---|
| icon-192.png | 15,767 | 15.4 | 0.015 |
| icon-512.png | 79,042 | 77.2 | 0.075 |
| icon-maskable-192.png | 7,728 | 7.5 | 0.007 |
| icon-maskable-512.png | 36,313 | 35.5 | 0.035 |
| logo.png | 157,225 | 153.5 | 0.150 |
| App_Logo.png | 1,474,734 | 1,440.2 | 1.406 |

---

## H. ICO embedded sizes

**Not applicable — no `.ico` file exists in the repository.** The `/favicon.ico` URL is a Flask route (`blueprints/public.py:15`) that streams the PNG `icon-192.png`. Consequently:
- embedded image count: **N/A (single PNG, one 192×192 image)**
- there is no multi-resolution `.ico` (no 16/32/48 variants baked in)
- suitability: a modern browser accepts the PNG, but there is **no small-size (16/32) rendition tuned for the tab** — the browser must downscale 192→16 itself.

---

## I. Visible-content bounding box & transparent-padding analysis

Measured with Pillow (`alpha.getbbox()` + per-pixel alpha>10 count):

| File | Canvas | Content bbox | Occupancy (bbox) | Visible px | Pad L | Pad T | Pad R | Pad B |
|---|---|---|---|---|---|---|---|---|
| **icon-192.png (tab favicon)** | 192×192 | **148×80** | **32.1 %** | **12.0 %** | 22 | **56** | 22 | **56** |
| icon-512.png | 512×512 | 388×206 | 30.5 % | 11.0 % | 62 | 154 | 62 | 152 |
| icon-maskable-192.png | 192×192 | 192×192 | 100 % | 100 % | 0 | 0 | 0 | 0 |
| icon-maskable-512.png | 512×512 | 512×512 | 100 % | 100 % | 0 | 0 | 0 | 0 |

**Interpretation for the tab favicon (`icon-192.png`):**
- The visible logo is a **wide, short wordmark (148×80, aspect ≈ 1.85:1)** centered in a square canvas.
- **~29 % of the height is empty transparent space at both the top and bottom** (56 px each). Left/right padding is milder (22 px each).
- Dominant visible color is **light gray `~rgb(224,224,224)`** (1,986 px) with black accents (`rgb(0,0,0)`, 511 px) — a light/white wordmark. Center pixel alpha 254 → the logo mark itself is opaque, but it sits on a **transparent** field (not a filled tile).
- Net effect: after the browser fits the 192 canvas into a tiny square tab slot and letterboxes the 1.85:1 mark, the logo appears **very small and lightweight**.

---

## J. Service-worker / cache findings

Source: `static/sw.js`.

| Item | Finding |
|---|---|
| Cache name/version | `var CACHE = 'coachhub-v6'` |
| Icons precached | `PRECACHE` includes `/static/icon-192.png`, `/static/icon-512.png`, `/static/manifest.webmanifest` — added on `install` |
| Icon caching strategy | **Cache-first, keyed by path** (query string ignored) for "stable assets (icons, logos, images, fonts, manifest)". CSS/JS use stale-while-revalidate; navigations are network-first (never cached) |
| Old cache cleanup | On `activate`, all caches whose name ≠ `CACHE` are deleted; `skipWaiting()` + `clients.claim()`; `pwa.js` reloads once on `controllerchange` |
| **Can an old favicon stay cached after deploy?** | **Yes.** Because icons are cache-first by path with the query ignored, a **same-filename replacement of `icon-192.png` is served from the old cache until the `CACHE` constant is bumped** (which drops the whole old cache on activate). A `?v=` on the URL would NOT help here — the SW deliberately strips the query for stable assets. |
| Static URL hashing | Favicon/icon `<link>`s have **no `?v=`**; app CSS/JS do use `?v=asset_version` (`context.py` `ASSET_VERSION='v6'`). Icons are excluded from that versioning. |
| Stale risk if filename kept | **High** for installed PWAs until `coachhub-v6` → `-v7` bump. |
| **Safest cache-bust for a favicon update** | **(a)** ship the new icon under a **new filename** (e.g. `icon-192-v7.png`) and update the `<link>`/manifest/route references, **and** **(b)** bump `CACHE` to `coachhub-v7` and update the `PRECACHE` list. New filename defeats both browser HTTP cache and the SW path-keyed cache; the `CACHE` bump purges the stale entry for installed clients. |

---

## K. Why the favicon currently looks small

Ranked by contribution, based on the measurements above:

1. **Excessive internal transparent padding + wide/short shape (primary cause).** The visible mark is only **32 % of the canvas** with **56 px empty top/bottom**, aspect 1.85:1. In a square tab the mark is letterboxed and shrunk well below the tab's already-small display size. This is the dominant factor.
2. **No dedicated small (16/32 px) rendition.** The browser downscales a 192-px image with fine wordmark detail into ~16 px; thin light strokes lose visual weight.
3. **Low-weight / light color.** The mark is light gray on transparent — visually "thin," and potentially **low-contrast on light browser chrome** (fine on dark chrome).
4. **Not** the browser's fixed size alone (that affects every site equally), **not** a wrong-file selection (only one `rel="icon"` exists), and **not** primarily caching (though stale caching is possible on updates — see §J).
5. **SVG viewBox padding — N/A** (no SVG favicon exists).

**Conclusion:** the icon is small because the source PNG wastes ~68 % of its canvas on transparent margins around a wide wordmark, not because of caching or misconfiguration.

---

## L. Recommended options (not implemented)

> None of the following have been applied. Presented for decision only.

### Option 1 — Keep PNG format, crop internal padding (tightest fix)
- **What:** Re-export `icon-192.png` / `icon-512.png` so the mark fills ~85–90 % of the canvas (trim the 56 px top/bottom margins; keep a small safe margin). Optionally place it on a filled `#0e1116` rounded tile for tab contrast on light chrome.
- **Visual result:** noticeably larger, bolder tab icon; consistent with maskable versions.
- **Compatibility:** universal (same format/links).
- **Effort:** low (image edit only; must re-bump SW `CACHE` + rename to bust cache).
- **Risks:** if kept same filename, stale cache (see §J); wordmark may still be hard to read at 16 px if it stays a full word.
- **Source dims:** design at 512×512, export 192 & 512. **Output size:** 5–40 KB each.

### Option 2 — Replace with a purpose-built 32×32 (and 48×48) PNG favicon
- **What:** Add a small, high-contrast **glyph** (e.g. a monogram/puck mark, not the full wordmark) as `favicon-32.png`/`favicon-48.png`; reference with explicit `sizes="32x32"`.
- **Visual result:** crisp, legible at tab size — best clarity.
- **Compatibility:** universal.
- **Effort:** low–medium (new small asset + link tags).
- **Risks:** two "brands" (glyph vs wordmark) to keep in sync.
- **Source dims:** 48×48 master. **Output size:** 1–5 KB.

### Option 3 — Create a real multi-size `.ico`
- **What:** Build `favicon.ico` embedding 16/32/48 px; serve it from `/favicon.ico` (replace the PNG-streaming route) and/or link it.
- **Visual result:** browser picks the optimal embedded size — sharp at every tab DPI.
- **Compatibility:** universal, incl. legacy.
- **Effort:** medium (generate ICO; adjust `blueprints/public.py`).
- **Risks:** larger single file; still needs the padding fix or it inherits the "small" look.
- **Source dims:** 16/32/48 (optionally 64). **Output size:** 5–25 KB total.

### Option 4 — SVG favicon for modern browsers + ICO/PNG fallback
- **What:** Add `favicon.svg` (`<link rel="icon" type="image/svg+xml">`) plus a PNG/ICO fallback link. Ensure the SVG viewBox is tight and uses a color that works in light **and** dark (or a `<style>` with `prefers-color-scheme`).
- **Visual result:** razor-sharp at any DPI; theme-adaptive possible.
- **Compatibility:** SVG favicons: modern evergreen browsers; fallback covers the rest.
- **Effort:** medium (author clean SVG; verify dark-mode fill).
- **Risks:** an SVG with a light-only fill goes invisible on light chrome — must handle both themes; there is currently **no** SVG in the repo to start from.
- **Source dims:** vector, tight viewBox. **Output size:** 1–8 KB SVG.

### Option 5 — Separate favicon vs. full app-logo assets (recommended structure)
- **What:** Treat the tab favicon (small glyph) and the header/PWA wordmark as **distinct assets**. Use Option 2/3 for the tab; keep the wordmark for headers and manifest `any` icons — but **also shrink `App_Logo.png`** (currently 1024×1024 / 1.41 MB displayed at ≤64 px) to a right-sized export.
- **Visual result:** clear tab icon + crisp header logo + smaller payload.
- **Compatibility:** universal.
- **Effort:** medium (multiple assets + references).
- **Risks:** more assets to version together.
- **Source dims:** favicon 48×48; header logo ~2× its max display (e.g. 256×256 or 512-wide wordmark). **Output size:** favicon 1–5 KB; header logo 20–80 KB (vs current 1.4 MB).

### Option 6 — Add cache-busting / versioning (do alongside any of the above)
- **What:** Give icon files versioned names (`icon-192-v7.png`) or add `?v=asset_version` **and** stop the SW from ignoring the query for icons; bump `CACHE` to `coachhub-v7` and update `PRECACHE`.
- **Visual result:** none directly — ensures the new icon actually reaches users.
- **Compatibility:** universal.
- **Effort:** low.
- **Risks:** forgetting the `CACHE` bump leaves installed PWAs stale (the SW ignores `?v=` for stable assets today — see §J).
- **Source dims:** N/A. **Output size:** N/A.

**Suggested combination:** Option 2 (or 3) for a legible tab glyph + Option 5 to right-size `App_Logo.png` + Option 6 to guarantee the update propagates.

---

## Verification / limitations

- All dimensions, byte sizes, bounding boxes, and colors were measured directly from the files with Pillow 10.2.0 and `stat`; `file`/`identify` confirmed formats. Nothing here is inferred from filenames alone.
- No `.ico`/`.svg` favicon exists, so ICO-embedded-size and SVG-viewBox analyses are reported as N/A with the reason stated.
- **No files were edited, resized, renamed, moved, or deleted. No templates, manifest, service worker, or routes were changed. Nothing was committed or pushed.**

---

# M. Implementation (2026-07-28)

The audit recommendations were implemented as a production-safe change limited to favicons, icon delivery, PWA references, the service-worker cache version, and `App_Logo.png` optimization. **No database, migration, header/nav markup, or unrelated image was touched. Nothing was committed or pushed.**

## M.1 Selected favicon symbol — and why

**Chosen symbol:** the **tactics-board "card"** from the existing CoachHub identity — a navy-outlined rounded clipboard holding three red X's, a player dot, and a play arrow. It was extracted at the highest available resolution from `App_Logo.png` (which, it turned out, has a **transparent** background — the gray seen in image viewers is the viewer compositing, not baked in). Card source region ≈ 208×288 px.

**Delivered form:** the card centered on a **rounded navy tile** (`#203548` — the card's own border color, sampled from the art, not invented), filling ~94% of the canvas.

**Why it beats the old wide wordmark:**
- The old favicon was the **wide "Coach Hub" wordmark** (148×80 content in a 192 canvas → **32% occupancy**, ~12% non-transparent), letterboxed to near-invisibility in a square tab.
- The card is **compact and square-friendly**, so it fills the tab; the new icons reach **89–100% occupancy**.
- **High contrast on both light and dark chrome** is guaranteed by the opaque navy tile (the transparent and white-tile variants vanished into matching chrome in side-by-side tests; the dark tile disappeared on dark chrome — navy won).
- **Recognizable at 16/32 px:** the white card face + red X's read even at 16 px; fine details degrade gracefully.
- It is **existing branding** — no new logo was designed.

## M.2 Files created

| File | Format | Dimensions | Size | Occupancy (bbox) | Purpose |
|---|---|---|---|---|---|
| `static/favicon-16.png` | PNG RGBA | 16×16 | 697 B (0.68 KB) | 100% | tab favicon (small) |
| `static/favicon-32.png` | PNG RGBA | 32×32 | 1,944 B (1.90 KB) | 100% | tab favicon (primary) |
| `static/favicon-48.png` | PNG (palette+α) | 48×48 | 1,686 B (1.65 KB) | 92% | tab favicon / ICO source |
| `static/favicon-192.png` | PNG (palette+α) | 192×192 | 4,711 B (4.60 KB) | 90% | apple-touch-icon, PWA `any`, offline logo |
| `static/favicon-512.png` | PNG (palette+α) | 512×512 | 17,294 B (16.89 KB) | 89% | PWA `any`, splash |
| `static/favicon.ico` | ICO (multi) | 16+32+48 | 5,873 B (5.74 KB) | — | `/favicon.ico` legacy |
| `templates/_favicon.html` | Jinja partial | — | — | — | shared favicon `<link>` set |
| `tests/test_favicon.py` | tests | — | — | — | 12 focused assertions |

All PNGs were size-optimized with Pillow (`FASTOCTREE` alpha-preserving quantization for the ≥48 px sizes: e.g. favicon-512 **167 KB → 17 KB**, ‑90%). The `.ico` embeds **16×16, 32×32, 48×48** (verified from its byte header).

## M.3 Files modified

| File | Change |
|---|---|
| `templates/base.html` | `rel=icon`→ `{% include '_favicon.html' %}`; removed duplicate `apple-touch-icon` (now in partial); manifest/theme-color/apple-meta kept |
| `templates/owner_base.html` | **added** favicon include — owner tabs no longer rely only on the `/favicon.ico` fallback |
| `templates/team_auth.html`, `welcome.html`, `429.html` | old single `rel=icon` → favicon include |
| `blueprints/public.py` | `/favicon.ico` now serves **`favicon.ico`** with `mimetype='image/x-icon'` (previously streamed a PNG) |
| `static/manifest.webmanifest` | `any` icons → `favicon-192.png` / `favicon-512.png`; **maskable icons retained** (valid full-bleed) |
| `static/sw.js` | `CACHE 'coachhub-v6' → 'coachhub-v7'`; `PRECACHE` now lists `favicon.ico`, `favicon-32.png`, `favicon-192.png` (+ offline, manifest); old-cache purge on `activate` unchanged; navigation still network-first |
| `static/offline.html` | offline logo `icon-192.png` → `favicon-192.png` (now precached) |
| `tests/test_pwa_update.py`, `tests/test_pwa_install.py` | cache-version assertions updated v6 → v7 |

`icon-192.png` / `icon-512.png` were left on disk (unused, harmless) rather than deleted. New filenames (`favicon-*`) were used deliberately because the service worker keys stable assets **by path, ignoring the query string** — a same-name swap would be served stale.

## M.4 `App_Logo.png` optimization

| | Before | After |
|---|---|---|
| Dimensions | 1024×1024 | **256×256** |
| File size | 1,474,734 B (1.406 MB) | **5,526 B (5.4 KB)** |
| Reduction | — | **‑99.6%** |

Displayed at ≤64 px everywhere (`.header-top .brand img` 64, `.lp-nav-brand`/`.auth-logo` 44, `.lp-footer-brand` 38) — 256 px gives ≥4× DPI headroom. Content, aspect ratio, and transparency preserved (same 4 references: `base.html`, `welcome.html`×2, `team_auth.html`). Filename kept because all references use it and cache invalidation is handled (SW `v7` purge + Flask static ETag revalidation). `logo.png` was left unchanged (not referenced anywhere).

## M.5 Expected browser-tab appearance

- **Tab / bookmarks:** a small rounded **navy square with a white play-card and red X's** — clearly visible on both light and dark browser chrome, ~3× the effective size of the old wordmark.
- **Installed PWA / Android home screen:** `any` = the new card; maskable = existing full-bleed brand icon.
- **iOS home screen:** `favicon-192.png` (card) via `apple-touch-icon`.

## M.6 Service-worker cache change

`coachhub-v6 → coachhub-v7`. On the next visit the new worker installs, `activate` deletes the `-v6` cache (removing any stale `icon-192.png`), precaches the new favicon set, and `clients.claim()` + the existing one-time reload apply it. Navigations remain network-first; authenticated HTML is still never cached.

## M.7 Testing

- Full suite: **437 passed** (`python -m pytest coach/tests/ -q`).
- Focused: `tests/test_favicon.py` (12 assertions) + updated PWA cache tests — all green.
- `node --check` OK for `sw.js`, `app.js`, `pwa.js`; manifest JSON valid; `coach.app` imports; `dev.db` untouched (mtime predates session).

## M.8 Manual verification (PythonAnywhere)

1. Upload changed files (or `git pull`) to the app directory.
2. **Web** tab → **Reload** the app.
3. Open the site → DevTools (F12).
4. **Application → Service Workers →** *Unregister* the old worker.
5. **Application → Storage →** *Clear site data*.
6. Close **all** CoachHub tabs.
7. Reopen the site (hard-reload: Ctrl/Cmd+Shift+R).
8. Verify the **welcome** tab icon = navy card.
9. Verify the **authenticated app** tab icon = navy card.
10. Verify the **Owner** (`/owner/...`) tab icon = navy card (previously none).
11. Reinstall / reopen the **PWA**; check the home-screen icon.
12. Repeat in **light and dark** browser themes; confirm contrast both ways.

Direct URL checks: `/favicon.ico` (should download an ICO, `Content-Type: image/x-icon`), `/static/favicon-32.png`, `/static/manifest.webmanifest`.
