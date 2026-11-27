# Raikō Themes — scope for approval

Themes that change **everything you see and feel**, not just colours: palette, fonts, shapes, motion,
backgrounds, ornaments on real UI elements (bats around the Settings button), a mascot, animated emoji,
copy, celebrations, and a Home spotlight that *becomes* the event. Two kinds:

- **Permanent themes** — you pick one; it stays.
- **Event & seasonal themes** — switch on by themselves on the day (Christmas, Halloween, a new anime
  season, the finale of a big series…), with a one-tap way back on first launch.

Everything is built on what Raikō already is (PyQt6 widgets, one stylesheet, custom-painted cards) —
no web view, no heavy engine, no new runtime dependency.

---

## 1. Principles

1. **Whole-app, not a skin.** One theme = a complete set of design tokens + assets + behaviour, applied to
   every screen, dialog, toast, the splash and the share cards.
2. **Delight, never in the way.** Decorations sit *around* content, never on it; nothing ever blocks a click.
3. **Your choice wins.** Events auto-apply (as you asked), but switching back is one tap, every event can be
   turned off individually, and there's a master "never auto-apply" switch.
4. **Respectful of people and machines.** Reduced motion, contrast, photosensitivity, battery, culture and
   region are handled by design (§9).
5. **Data, not code.** A theme is a folder of JSON + images/fonts — safe to add, impossible to run code from.

---

## 2. What exists today (audit, 2026-11-27)

| Where colour/style lives | Count |
|---|---|
| `resources/themes/dark.qss` | 2,177 lines, 323 selectors |
| Inline `setStyleSheet(...)` in Python | 146 calls |
| Hex colours inside Python paint code / styles | **594 literals, 204 distinct** (many near-duplicates: 3 purples, 4 golds…) |
| Custom-painted components (`paintEvent`) | 16 files (cards, spotlight, Hall posters, toasts, gallery…) |
| Hard-coded fonts | Segoe UI in 5 places |
| Animations/timers already in use | 114 (`QPropertyAnimation`, opacity effects, timers) |

**Consequence:** theming needs a **token foundation first** (Phase 0). Today a theme could only recolour
the stylesheet; painted cards, the spotlight, Hall posters and toasts would keep their old colours.

### Capabilities confirmed on this machine
- `QMovie` plays **animated WebP and GIF** natively → animated emoji, mascots, ornaments without new libraries.
- SVG rendering (QtSvg), audio (QtMultimedia) available.
- Windows "Animation effects" setting readable (`SPI_GETCLIENTAREAANIMATION`) → honour it.

---

## 3. The theme model — seven layers

| Layer | What it controls | Examples |
|---|---|---|
| **1. Colour tokens** | ~30 semantic tokens (not raw hex): `bg`, `surface`, `surface-2`, `border`, `text`, `text-muted`, `accent`, `accent-miroku`, `accent-kinema-movie`, `accent-kinema-tv`, `gold`, `success`, `warning`, `danger`, `on-accent`, `glow`, chart ramps… | Halloween: pumpkin accent, violet surfaces; Christmas: pine + cranberry + gold |
| **2. Typography** | Display font (titles, greeting, spotlight), body font, numeral font, letter-spacing for kickers | Halloween display "Creepster"-style; New Year: elegant serif display; body stays readable (Segoe UI / Inter) |
| **3. Shape & depth** | Corner radius scale, border weight, shadow/glow style, card frame style | Winter: frosted borders; Retro: hard 2px borders, no radius |
| **4. Motion** | Durations/easings, ambient effects (snow, petals, bats, fireflies, confetti), hover micro-motions | Snow drifts behind content; petals fall when you open a panel |
| **5. Surfaces & art** | Background texture/gradient, sidebar art, spotlight frame, empty-state illustrations, splash art, share-card frames | Christmas: soft bokeh lights behind the sidebar |
| **6. Ornaments & mascot** | Small decorations **anchored to real elements** + the Raikō mascot's outfit and reactions | Bats circling the Settings button, a Santa hat on the logo, a pumpkin on the Hall of Fame star, the mascot waving in empty states |
| **7. Voice & behaviour** | Greeting copy, toast icons & lines, celebration moments, Home spotlight takeover, picks for the day | "Happy Halloween, Kingsley 🎃", "Episode 7 watched — spooky good", confetti when you finish a series on New Year's Eve |

A theme can override any subset; anything it doesn't set falls back to the base theme. This keeps event
packs small and guarantees nothing is ever unstyled.

---

## 4. Permanent themes (launch set)

| Theme | Mood | Notes |
|---|---|---|
| **Raikō Night** (default) | today's look, refined into tokens | the baseline everything inherits from |
| **Midnight Ink** | true-black OLED, neon hairlines | low-glare, battery-friendly on OLED |
| **Sakura Dawn** | first **light** theme — warm paper, blush pink, ink text | full light-mode pass of every screen |
| **Neo-Tokyo** | cyber-neon, scan-line texture, mono numerals | subtle animated sign flicker (respects reduced motion) |
| **Studio Watercolor** | soft hand-painted textures, rounded serif display | original art, no studio IP |
| **Retro VHS** | CRT glow, chunky borders, pixel numerals | tracking-line hover effect |
| **Zen Mono** | greyscale + one accent you pick | minimal, distraction-free |
| **High Contrast** | WCAG AAA text, thick focus rings, no textures | accessibility theme, always available |

Plus **Accent picker** on any permanent theme (8 curated accents + custom, contrast-checked live).

---

## 5. Event & seasonal themes

### 5.1 Calendar events (several variants each — you can pick)
| Event | Window | Variants (examples) |
|---|---|---|
| **Christmas** | Dec 20 – Dec 26 (peak 24–25) | *Cozy Cabin* (warm wood, firelight), *Snowfall Night* (deep blue, snow), *Candy Cane* (playful red/white), *Golden Eve* (elegant gold) |
| **New Year** | Dec 31 – Jan 2 | *Midnight Countdown* (live countdown in the greeting, fireworks at 00:00), *Hatsuhinode* (first sunrise, Japanese new year) |
| **Halloween** | Oct 25 – Oct 31 | *Haunted Night* (bats around Settings, fog), *Pumpkin Patch* (cute), *Yokai* (Japanese folklore spirits) |
| **Valentine's** | Feb 13 – Feb 14 | *Rose*, *Pastel Hearts* |
| **Lunar New Year** | computed date, 3 days | *Lantern Festival* |
| **Hanami / Spring** | Mar 20 – Apr 10 | *Sakura Season* (petals drift) |
| **Tanabata** | Jul 7 | *Star Festival* (wishes on bamboo — write a watch-wish) |
| **Summer Matsuri** | Aug 1 – Aug 20 | *Fireworks & Fireflies* |
| **Autumn** | Oct 1 – Oct 24 | *Momiji* (maple leaves) |
| **Raikō's birthday** | app anniversary | confetti, mascot party hat, your year in numbers |

Region-aware: events tied to a country (e.g. Thanksgiving) only appear where they make sense (uses your
Raikō region); every event is individually switchable (§6.4).

### 5.2 Anime-world events (data-driven, short — usually one day)
| Event | Trigger (automatic, from AniList / your library) | What it looks like |
|---|---|---|
| **Season Premiere Week** | first days of Jan / Apr / Jul / Oct | spotlight becomes "This season's most anticipated" with the top upcoming shows; palette from the #1 show's key art |
| **Farewell to a legend** | a very popular, long-running series airs its **final episode** (popularity + length thresholds), or a show in **your Hall of Fame** finishes | one-day commemorative theme coloured from its art, its opening ready to play, "Thank you, *Bleach*" slide with your stats with it and a link to rank its songs |
| **Big premiere day** | a show with exceptional anticipation premieres | the show's colours, countdown during the day, "Watch it tonight" slide |
| **Your milestones** | your 1,000th episode, 100th movie, 5 years of tracking… | personal celebration: confetti, badge, share card |

Dynamic palettes come from the show's own artwork (dominant colours + AniList's cover colour), turned into a
full token set and **contrast-checked automatically** before use.

### 5.3 Priority when events overlap
Your manual pick of a permanent theme < calendar season (e.g. Autumn) < major holiday (Halloween) <
anime "Farewell"/premiere (one day) < personal milestone (moment only, not a full theme).
Only one *theme* is active at a time; milestones are celebrations on top.

---

## 6. UX flows

### 6.1 An event begins (no approval needed)
1. On launch on the event day, the theme is already applied — the app opens *dressed up*.
2. A **themed welcome banner** at the top of Home (not a dialog):
   > 🎃 **Raikō dressed up for Halloween.** &nbsp; [**Keep it**] [**Switch back**] [Try the other Halloween looks]
3. **Keep it** → banner thanks you and fades. **Switch back** → your previous theme returns instantly,
   with "You can turn Halloween back on in Settings → Appearance → Event themes."
4. **If you close the banner (✕) without choosing:** the theme stays, and a coach mark appears once —
   it **points at the Settings button in the sidebar** and says:
   *"Changed your mind? Settings → Appearance → Event themes lets you switch back or turn off events."*
   (uses the same spotlight system as the welcome tour, so it highlights the exact place).
5. The banner never returns for that event this year. When the event ends, your previous theme comes back
   automatically, with a small "Halloween's over — back to Raikō Night" toast.

### 6.2 Previewing before accepting — the visual walkthrough
From the banner ("Try the other looks") or from Settings → Appearance:
- **Theme gallery**: cards showing a live miniature of Raikō in each theme (rendered from real screens,
  not mock-ups), grouped *Permanent* / *Happening now* / *Coming up*.
- **Preview tour** (one click on a card): Raikō switches to the theme **in preview mode** and a floating
  pill appears — `Previewing Snowfall Night · ‹ › · Apply · Cancel`. A guided **4-stop walkthrough** shows
  it where it matters: **Home spotlight → Library cards → a detail panel → the Settings button's ornament**,
  each stop with a one-line caption. ← / → move between stops; Esc cancels.
- **Cancel** restores everything exactly; **Apply** makes it yours. Preview auto-cancels after 2 minutes
  of no interaction so you can never get "stuck" in a theme.
- "Coming up" events can be previewed too — and turned off before they ever appear.

### 6.3 Settings → Appearance (new page)
- **Theme**: gallery (permanent), accent picker, font size (90–125%).
- **Event themes**: master switch "Dress up Raikō for events" (on), per-category toggles (Holidays,
  Seasons, Anime events, Milestones), per-event toggles with dates and a Preview button, "Ask me first
  instead of switching automatically".
- **Motion**: Ambient effects (on / calm / off), "Follow Windows animation setting" (on), Sounds (off by default).
- **Mascot**: show / hide.

### 6.4 Remembering choices
Per event per year: kept / switched back / disabled. Turning an event off is permanent until turned on.

---

## 7. Every element and what a theme can do to it

(✓ = themed by tokens automatically after Phase 0; ★ = can carry ornaments/art/motion)

| Area / element | Tokens | Font | Shape | Ornament/art ★ | Motion ★ | Voice |
|---|---|---|---|---|---|---|
| Window background | ✓ | | | texture, gradient, ambient particles layer | snow / petals / fireflies | |
| **Sidebar** — logo & wordmark | ✓ | display | | hat / crown / wreath on the Aperture mark | logo shimmer at midnight | |
| Sidebar — nav items, active pill | ✓ | ✓ | ✓ | seasonal icon swap (★→🎄 for Hall on Christmas) | active pill glow | |
| Sidebar — **Settings button** | ✓ | | | **bats circling (Halloween)**, holly, snow cap | orbiting / wobble on hover | |
| Sidebar — "Add anime/movie" button | ✓ | ✓ | ✓ | gift-box frame | | label line |
| Status bar (Online / AniList / TMDB) | ✓ | | | tiny lantern dots | | |
| **Home greeting** | ✓ | display | | mascot beside it | typing-in greeting | event greeting + countdown |
| **Home spotlight** | ✓ | display | frame | **event slide takeover** (§8), frame art | parallax layers, ambient | slide copy |
| Home stat chips | ✓ | numerals | ✓ | | count-up on load | |
| Home This week + popover | ✓ | ✓ | ✓ | day-column header ornaments | | |
| Home Ready to watch / Pantheon strip | ✓ | | ✓ | festive poster frames | | |
| Library cards (anime/TV/movie) | ✓ | ✓ | ✓ | corner ornament on hover, frosted/candy borders | hover tilt / sparkle | |
| Filter pills, search bar, sort | ✓ | ✓ | ✓ | | | placeholder text |
| **Detail panel** | ✓ | ✓ | ✓ | banner frame, section dividers | | |
| Status switcher, Hall badge | ✓ | | ✓ | | | |
| Videos & music card, gallery tabs | ✓ | | ✓ | | | |
| Video player chrome | ✓ | | ✓ | | | |
| Episode lists, stars, ratings | ✓ | | | star glyph swap (★→❄ / 🎃) | burst on rate 6/6 | |
| Discover (Miroku / Kinema) | ✓ | ✓ | ✓ | "event picks" chip row | skeleton shimmer in theme colours | |
| Hall of Fame / Pantheon / Honours | ✓ | display | ✓ | laurels → event laurels, plaque frames | induction ceremony particles | |
| Music page / rank duel | ✓ | ✓ | ✓ | | | |
| **Toasts** | ✓ | ✓ | ✓ | themed icon badge / mascot face | | event lines |
| Banners (status, update, notifications) | ✓ | ✓ | ✓ | | | |
| Dialogs, menus, tooltips, scrollbars | ✓ | ✓ | ✓ | | | |
| Splash screen | ✓ | display | | event splash art | | |
| Onboarding / tours | ✓ | ✓ | ✓ | mascot guide | | |
| Empty states & loading skeletons | ✓ | ✓ | | mascot illustrations | idle animations | themed lines |
| Share cards (Hall, Music) | ✓ | display | | **event frames** on exported PNGs | | |
| Taskbar icon / badge | | | | event icon variant (optional) | | |
| Windows notifications (app closed) | | | | | | event emoji in titles |

The full per-file checklist (all 40 UI modules) is produced in Phase 0 as part of the token migration.

---

## 8. The event spotlight on Home

The first spotlight slide becomes **the event**, built in layers so it feels deep and alive without a 3D engine:

1. **Backdrop** — event art (painted, not stock), slow parallax drift (2–3 depth layers).
2. **Hero object** — an animated centerpiece rendered as animated WebP from 3D/Lottie sources:
   a **rotating, twinkling Christmas tree**, a carved **jack-o'-lantern** that flickers, a **firework burst**
   at New Year, a **lantern** for Tanabata. Pre-rendered at 2× for crispness, ~1–2 MB each.
3. **Ambient particles** — snow / bats / petals in front and behind (depth).
4. **Content** — event title in the display font, a line ("Merry Christmas — 4 picks for tonight"),
   and **curated picks** from what fits the event:
   - Christmas → TMDB keyword *christmas* + Christmas-themed anime episodes/films (AniList tags),
     prioritising titles in your Watchlist / Plan to Watch first, then For You-style matches.
   - Halloween → horror/supernatural films + anime (AniList *Horror*, *Supernatural*), your library first.
   - Season Premiere Week → most anticipated airing now (AniList popularity + your genres).
   - Farewell → that series: your stats with it, its OP/ED ready to play, "Rank its songs", "Watch again".
5. **Actions** — Play trailer, Add to Watchlist, Open details (as today).

Picks are fetched once per event and cached; offline, the slide still shows (art + your own library picks).

---

## 9. Motion, performance & accessibility

- **One ambient layer** per window: a single transparent overlay widget draws all particles with QPainter
  (no per-particle widgets). Target ≤ 30 fps, **≤ 3 % CPU**; pauses when the window is minimised/hidden
  or Windows battery saver is on.
- **Reduced motion**: follows Windows *Animation effects* (`SPI_GETCLIENTAREAANIMATION`, refreshed on
  settings change) and the in-app Motion setting → particles stop, ornaments become static, transitions shorten.
- **Photosensitivity**: no flashing faster than 3 Hz, no full-screen flashes (fireworks are soft blooms).
- **Contrast**: every theme (and every dynamic artwork palette) is checked automatically — text ≥ 4.5:1,
  large text/icons ≥ 3:1; a theme that fails can't ship (and a dynamic palette that fails falls back).
- **Never blocking**: ornaments are mouse-transparent; banners are inline, not modal.
- **Culture & region**: holidays are optional and region-aware; copy is warm but neutral.
- **Sound**: off by default; if on, only soft, short cues (e.g. a bell when you finish a series on Christmas).

---

## 10. Assets, fonts & libraries

| Need | Choice | Why |
|---|---|---|
| Animated emoji | **Noto Animated Emoji** (Google), animated WebP via `QMovie` | CC BY 4.0 (attribution in About), plays natively, no new dependency |
| Mascot & ornaments | Original **Raikō mascot** ("Rai", a small spirit of light matching the Aperture logo) with outfits per event; designed as vector + Lottie, **pre-rendered to animated WebP** by a build tool | original IP (no copyrighted characters), crisp, cheap to play |
| Lottie sources | `rlottie-python` **only in a build-time tool** (`tools/render_lottie.py`) | runtime stays dependency-free |
| Fonts | Open-licence (SIL OFL) fonts bundled per theme, loaded with `QFontDatabase.addApplicationFont`, subset to Latin + Japanese kana where needed | legal to bundle, small |
| Hero objects (tree, pumpkin…) | 3D renders / illustrations → animated WebP (2×) | "3D" look without a 3D engine |
| Particles | procedural (QPainter) — snowflakes, petals, leaves, bats as tiny vector sprites | tiny, infinitely varied |
| Palettes from artwork | Pillow quantisation + AniList cover colour → token set + contrast check | already a dependency |

Size budget: base app unchanged; **permanent themes ≤ 1 MB each**, **event packs ≤ 5 MB each**.
Built-in packs ship inside the app; future event packs can arrive with normal updates (and optionally a
downloadable event feed, §11).

---

## 11. Architecture (fits the current app)

- **Design tokens** (`core/theme_tokens.py`): the token names + the base theme's values.
- **ThemeManager** (`ui/theme.py`, app-wide like `MusicHub`): current theme, `token("accent")`,
  `font("display")`, `motion()`; emits `theme_changed`. Painted widgets read tokens in `paintEvent`
  and repaint on change. The stylesheet becomes a **template** (`dark.qss` → `base.qss.tmpl` with
  `{{accent}}` placeholders) rendered per theme.
- **Theme packs** (`resources/themes/packs/<id>/theme.json` + assets): layers from §3, inheritance (`extends`),
  schedule (for events), variants, preview thumbnails.
- **Anchors & ornaments** (`ui/ornaments.py`): named anchor points registered by widgets
  (`settings_button`, `logo`, `hall_star`, `home_greeting`, `spotlight`…). Ornaments attach to anchors,
  follow their geometry (event filter), and are mouse-transparent.
- **Ambient layer** (`ui/ambient.py`): one overlay per window for particles.
- **Event engine** (`core/events.py`): date rules (fixed, ranges, computed — e.g. Lunar New Year),
  region rules, data rules (AniList finales/premieres, your milestones); evaluated at launch and midnight;
  remembers your per-event choices.
- **Event feed (optional, later)**: a JSON file published with releases listing anime events
  (e.g. a big finale date) — **data only**, schema-validated, size-limited, hash-checked; Raikō works fully
  without it.

### Security
Theme packs are **data only** (JSON + WebP/PNG/SVG/TTF): no scripts, no QSS from outside (QSS is generated
from tokens), SVGs sanitised (no scripts/external refs), strict JSON schema, file-type and size limits,
paths can't escape the pack folder. Remote data (if ever enabled) is HTTPS, signed/hash-checked and optional.

---

## 12. Testing & quality gates

- **No raw hex left** in `ui/` after Phase 0 (test fails if a new hard-coded colour appears).
- **Contrast test** for every theme × every token pair that's used for text.
- **Screenshot gallery tool** (`tools/theme_gallery.py`): renders Home, Library, a detail panel, Hall,
  Music, Settings, a toast and a dialog **in every theme** → one sheet to review before shipping.
- **Date simulation**: `main.py --date 2026-12-25` (and `--event halloween`) to see any event any day.
- **Performance test**: ambient layer CPU/fps budget on your machine.
- **Your test checklist** per phase, as always — nothing ships without your "ship it".

---

## 13. Build plan (each phase testable on its own)

| Phase | What you get |
|---|---|
| **0. Foundation** | design tokens; every colour/font in all 40 UI modules moved to tokens; stylesheet template; app looks identical (proof: screenshot diff) |
| **1. Permanent themes** | ThemeManager, Appearance settings, theme gallery with live previews, **preview walkthrough**, 8 permanent themes, accent picker, font size |
| **2. Life** | anchors & ornaments, ambient particle layer, mascot (base outfit), reduced-motion handling, animated emoji in toasts/empty states |
| **3. Events** | event engine, themed welcome banner + "switch back" + coach mark to Settings, per-event settings, **Christmas (4 variants), New Year (2), Halloween (3)** packs |
| **4. Spotlight takeover** | event slide with hero object + curated picks; Season Premiere Week; Farewell-to-a-legend; milestones |
| **5. Calendar complete** | Valentine's, Lunar New Year, Hanami, Tanabata, Matsuri, Autumn, Raikō's birthday; event frames on share cards |

Timing note: Phase 0 is the biggest, least visible step — but it's what makes every later theme complete.
Christmas is in under a month (Dec 20): **phases 0–3 can be ready for Christmas** if we start now, with
Halloween-quality polish arriving for the next events.

---

## 14. Decisions for you

1. **Permanent themes** — the 8 in §4, or change the list?
2. **Mascot** — yes to an original Raikō mascot ("Rai", a light spirit) appearing in empty states, toasts and
   events? (can be hidden in Settings either way)
3. **Event behaviour** — auto-apply on the day with the banner + switch-back (as you asked) — confirmed.
   Also show "Coming up" events in Settings so you can preview/disable them early? (recommended)
4. **Anime-world events** — include *Farewell to a legend*, *Season Premiere Week*, *Big premiere day*,
   *your milestones*? (all recommended)
5. **Sound** — off by default, opt-in soft cues? (recommended)
6. **Christmas target** — aim to have phases 0–3 (including the Christmas themes) ready for you to test
   before Dec 20?

---

### Sources consulted
- Google — [Noto Animated Emoji: updates & licensing (CC BY 4.0)](https://developers.googleblog.com/en/updates-to-emoji-new-characters-new-animation-new-color-customization-and-more/), [Noto emoji files](https://googlefonts.github.io/noto-emoji-files/)
- [rlottie-python](https://pypi.org/project/rlottie-python) / [docs](https://rlottie-python.readthedocs.io/en/latest/rlottie_python.html) (build-time Lottie rendering)
- Microsoft — [Client area animation (reduced motion)](https://learn.microsoft.com/en-gb/windows/win32/winauto/client-area-animation); [Chromium's handling](https://chromium.googlesource.com/chromium/src.git/+/HEAD/ui/gfx/animation/animation_win.cc)
- Seasonal-theme UX: [Thinkst — seasonal themes & delight](https://blog.thinkst.com/2022/11/seasonal-themes-delighting-users-small-ux-touches.html), [Emby users on seasonal themes](https://emby.media/community/topic/80755-disable-seasonal-themes-on-everywhere-on-everyone/), [SimplyPrint holiday opt-outs](https://help.simplyprint.io/en/article/holiday-gimmicks-in-simplyprint-1by064u/), [Inclusive design and holiday calendars](https://buttondown.com/inclusive-android-apps/archive/inclusive-android-apps-12-the-problem-of-holidays-assuming-one-calendar/), [Theming your app for the holidays](https://proandroiddev.com/theming-your-app-for-the-holidays-4245f4f46a05)
