# Raikō 3.0 — master list & final test plan

Everything requested for 3.0, in one place. Each item gets tested by you on
the finished MVP before anything ships. Status: ✅ built · 🔨 in progress · 🕒 queued.

Run from source: `.venv\Scripts\python.exe main.py` (the Desktop shortcut
still opens the old v2.8 release until 3.0 ships — avoid using it in the
meantime, it doesn't understand movies).

---

## Foundations ✅
- [ ] App looks and behaves like v2.8 for anime.
- [ ] Library upgraded to v5; safety copy `.animetracker\backups\anime_pre_v5_*.db` exists.
- [ ] Settings → TV shows & movies: country (US), own TMDB key (optional), alert choice.
- [ ] Settings → About credits TMDB and JustWatch.

## Sidebar ✅
- [ ] **Miroku · Anime**: Library, Dropped, Discover, Calendar, Miroku Stream.
- [ ] **Kinema · Movies & TV**: Movies, TV shows, Discover.
- [ ] **Personal**: Hall of Fame, Statistics.
- [ ] Add button changes per section (indigo sparkle / amber film frame / sky-blue screen); Ctrl+N works.

## Movies (Kinema) ✅
- [ ] Movies library: All / Watchlist / Watched; stats Watchlist · Watched · Hours watched · This year.
- [ ] Empty Movies library talks about movies.
- [ ] Sort: Top Rated (default), Most Anticipated, Newest, Title, Date Added, Your Rating.
- [ ] Watchlist shelves: **Ready to watch** then **Waiting for HD** (soonest first).
- [ ] Cards: READY TO WATCH / IN CINEMAS (HD date, days left) / COMING SOON / WATCHED (+ your rating).
- [ ] Panel (Watchlist): release timeline (Cinemas / Digital (HD) / Disc), countdown, where to watch,
      trailers (8 + rest in player), facts, cast, franchise with ＋ Add.
- [ ] Panel (Watched): watched date, verdict vs community, Log a rewatch, Hall of Fame, Move to Watchlist.
- [ ] Unreleased films can't be marked watched (dialog + panel); wrongly-marked shows NOT OUT YET + fix.
- [ ] Alerts: one "Out in HD" per film; one "HD date announced"; cinema alerts only if chosen.
- [ ] Watched list = diary timeline with archive.

## Kinema Discover & Add a movie ✅
- [ ] Lists: For you (with "Because you watched…"), Coming soon, Trending, Just out in HD, In cinemas, Top rated.
- [ ] Genre filter + sort (Best match, Popularity, Rating, Release date, Title) on every list.
- [ ] Search overrides the list; clearing returns to it.
- [ ] Same browser in **+ Add a movie** (dialog closes after adding) and **Discover** (stays open).
- [ ] Upcoming films show "Out <date>" in amber; library films show IN LIBRARY.

## Reliability ✅
- [ ] Unexpected errors go to `~\.animetracker\error.log` instead of closing the app.
- [ ] Anime-only alerts wrongly attached to movies are withdrawn automatically.

## TV shows (Kinema) ✅
- [ ] TV shows page: All / Watching / Watchlist / Completed / Dropped; stats Watching · Completed · Watchlist · Episodes seen.
- [ ] Sort: Recently Watched (default), Next Episode, Top Rated, Title, Date Added, Your Rating.
- [ ] Cards: NEW EPISODE / +N NEW (aired this week), N TO WATCH, UP TO DATE, BETWEEN SEASONS, COMING SOON,
      AIRING / ENDED (Watchlist), COMPLETED, DROPPED; "Next S02E05 · 13/19"; next airing date or time left to watch;
      sky-blue progress bar.
- [ ] Add a show (Ctrl+N on TV shows): Add to Watchlist / I'm watching it / I've finished it (marks all aired episodes).
- [ ] Panel: Up next + one-click "Watched S02E05", progress bar, next airing + countdown, Start / Mark completed /
      Drop / Resume / Back to Watching.
- [ ] Seasons: tab per season (✓ when done), rate the season (6 stars), Mark all / Unmark all, episode list with ticks;
      right-click an episode: watched up to here, rate it. Unaired episodes locked with their air date.
- [ ] Watching the last episode of an ended show completes it automatically; first episode moves a Watchlist show to Watching.
- [ ] Completed: verdict vs community + favourite season; where to watch; trailers; facts; cast.
- [ ] Alerts: new episode(s) for shows you watch (one per drop), new season confirmed, premiere date set, new trailer.
      Dropped shows stay quiet; nothing on the first sync.
- [ ] Clicking a movie/TV alert opens that library and the title.
- [ ] Discover: Movies | TV shows switch. TV lists: For you, Airing this week, New shows coming, Trending, Top rated,
      Popular (no talk/news/reality; anime stays in Miroku).

## Miroku in the Kinema style (requested 2026-11-16) ✅
- [ ] Calendar, Miroku Stream, Hall of Fame and Statistics removed everywhere (data kept in the library file).
- [ ] Anime cards read like TV cards: badge, "Next Ep 5 · 4/12", next airing or time left, progress bar —
      all existing card info kept.
- [ ] Anime detail panel in the Kinema layout: up next + one-click mark, progress, next episode countdown,
      status actions, episode list (tick / up to here / rate), verdict, where to watch, trailers, facts, characters.
- [ ] Miroku Discover in the Kinema flow (search, list chips, genre + sort, poster grid, preview + add), anime-themed.
- [ ] Your 11 Hall of Fame-only favourites (Bleach, Death Note, HxH…) now show in Completed, every episode ticked
      (backup `anime_pre_hof_*.db` taken first; rankings kept in the file).
- [ ] Miroku Discover and **Add anime** (Ctrl+N) use the Kinema browser: For you, This season, Next season,
      Trending, Top rated, Most popular; Plan to Watch / I'm watching it (aired) / I've finished it (finished airing).
- [ ] Data Doctor (Settings, or straight from an alert) checks anime, movies, TV, the library file and
      app errors; each issue names its library; pick fixes and apply.
- [ ] A problem found by the background check (25 s after start, then every 6 h) shows ONE pink
      "DATA DOCTOR" alert with **Open Data Doctor**; the same problems never alert twice.
- [ ] Any unexpected error shows "Something went wrong" with **Open Data Doctor** (max once per 10 min);
      the app keeps running and Data Doctor lists the error until you mark it reviewed.

## Fixes batch (2026-11-16) ✅
- [ ] Discover (both): clicking a list / switching Movies|TV / searching shows shimmering placeholders right away.
- [ ] Discover preview: ONE official trailer (click to play in-app) + cast / characters with photos.
- [ ] TV: "Mark completed" only on ended shows; adding a running show offers "Seen earlier seasons"
      (follows the current season); the panel opens on the season you're on; "✓ Mark S1 watched" moves you to S2.
- [ ] Opening a Plan to Watch anime no longer pops "Trailer available"; only genuinely new trailers/dates alert.
- [ ] Status banners: themed cards inside the window, bottom-centre, stacked — No internet (red), AniList down
      (indigo), TMDB down (amber, new), with Check now; status bar shows "TMDB OK".
- [ ] Quick links: one-click label presets (Crunchyroll, Netflix, Telegram channel, Episodes…) also set the platform.

## One app (phase 4) ✅
- [ ] Raikō opens on **Home** (top of the sidebar): greeting + date, "Search everything" pill (Ctrl+K).
- [ ] **Spotlight carousel** (auto every 9 s, pauses on hover, dots + ‹ ›). Library news has SOLID badges:
      NEW EPISODE (✓ Watched), OUT IN HD, IN CINEMAS, NEW SEASON, NEW TRAILER (▶ Play), NEXT TO AIR (countdown).
      Picks have an OUTLINED "FOR YOU" badge + "Because you watched…" and open in Discover ("Preview & add").
      Dots: filled = your library, rings = picked for you.
- [ ] Below the spotlight: stat chips, then **This week**; **Ready to watch** only when a Watchlist movie is out in
      HD. (Continue watching and Picked for you rows removed: the spotlight already covers them.)
- [ ] Preview safely on a copy: `.venv\Scripts\python.exe tools\preview_home.py` (add `--fresh` to fake new
      episodes, `--tour` for the welcome + tour).
- [ ] **Search everything** (Ctrl+K from anywhere): your anime, shows and movies grouped by library; Enter opens the
      first; "Find anime on AniList" / "Find movies & shows on TMDB" jump to Discover with the text filled in.
- [ ] Opening any title from Home lands in its own library with the panel open.
- (Statistics / Hall of Fame across types: dropped, as you retired those screens; Home's summary line covers counts.)

## Rebrand to Raikō (phase 5) ✅
- [ ] **Logo (Aperture)**: three arcs (Miroku indigo, Kinema amber, TV sky) around a point of light — taskbar,
      title bar, sidebar (mark + "Raikō"), Miroku / Kinema marks in the sidebar headers, splash, Settings → About.
- [ ] Window title, splash ("Starting Raikō…", "Everything you watch, in one light"), About copy say Raikō.
- [ ] Build (only when you say ship): Raiko.exe in Programs\Raiko, Raiko-vX-Windows.zip, Desktop shortcut "Raikō"
      replaces the old "Miroku" shortcut; your settings and library carry over untouched.
- [ ] **Premium cards**: hairline borders, red ring only for a new episode, library colour when selected, glass
      status pills, gentle hover lift; hover ✓ marks the next episode watched (anime & TV). All info still there.
- [ ] **Onboarding**: on first start of 3.0 you see "Miroku is now Raikō" (new users: "Welcome to Raikō") with
      Home / Miroku / Kinema tiles and your country; "Take the 1-minute tour" walks 7 steps across the real pages
      (Back / Next / Skip). Settings → About → "Replay the welcome tour".

## Polish & release (phase 6) 🔨
- [x] Upgrade rehearsal on your real v2.8 library (pre-3.0 safety copy): 35 titles kept, 244 ratings kept, 3 dropped
      kept, 11 Hall of Fame favourites moved to Completed, safety copies made, Data Doctor 0 issues, every page and
      panel opened with 0 errors.
- [x] No errors in your error.log from testing; static check clean; Home ready in ~4 s; This week fits 1280×720.
- [ ] Your final test pass of this checklist (run from source, or `tools\preview_home.py`).
- [ ] On "ship it": version 3.0.0 → merge to main → tag v3.0.0 → build (tests must pass) → Raiko-v3.0.0-Windows.zip
      → GitHub release with docs/RELEASE_NOTES_v3.0.0.md → installs to Programs\Raiko + "Raikō" Desktop shortcut.

## 3.1.0 — Hall of Fame & This week popover (built 2026-11-17, awaiting your test) 🧪
- [ ] Hall of Fame (sidebar ★): your 10 old rankings are there in order with their S/A tiers
- [ ] + Induct a title → pick → "Which do you love more?": click / ← →, Too close, Skip, Undo, result screen; Undo there takes it back
- [ ] List view: drag a row → order and ▲▼ update; Tiers view: drag a poster to another tier; Rename tiers…
- [ ] Showcase, Timeline, Numbers look right for Miroku / Movies / TV shows
- [ ] Pantheon: auto-filled with each wing's #1; empty slot → pick; right-click → change slot / unpin
- [ ] Plaque: write why / moment / character, set tier, Re-rank, Pin, Remove; reopen → saved
- [ ] Honours: starter set; choose winners for trilogy/duology (Look online for more), finale (episode), villain (character), opening (song), studio (name), best of a year; runners-up; Make it the winner; reason; rename / move / delete award; custom award
- [ ] Share card: Pantheon / Top 10 / Tier list / Honours → Save PNG… and Copy image
- [ ] Best trilogy: search "lord of the rings" → the 3 films appear → choose → "Add 3 to Kinema as watched" (or Just award it); the films then show in Kinema → Movies
- [ ] Induct a title / any award picker: type a film you haven't added → "Not in Kinema yet?" results → Show more → pick → added to Kinema as watched → continues (ranking / award)
- [ ] Best villain / character / protagonist: the FULL cast loads page by page (anime: most-loved first, protagonist: main first; Main / Supporting / Background chips; movies & TV: billing order); filter box, Show more, "Someone else…"
- [ ] Discover (Miroku and Kinema, each list and a search): Show more at the bottom loads more; at the end it says "That's everything"
- [ ] Detail panel: "★ #N in your … Hall" (menu) on Hall titles, "Induct into Hall of Fame" on finished ones, nothing on others
- [ ] Rate a finished title 6/6 → offer to induct; "Not now" never asks again for it
- [ ] Home: Pantheon strip beside the stats → opens the Hall
- [ ] Toasts: mark an episode watched, rate something, add a title → new solid card bottom-right (no see-through), countdown pauses on hover, click / ✕ dismisses, 3+ stack neatly, move/resize the window → they follow
- [ ] Home → This week: click an anime / TV / movie entry → popover beside it (flips near the right edge); Open details, Trailer; Esc / click outside / scroll / same entry closes it

## Next (after 3.1.0) — status switcher & music (built 2026-11-27, awaiting your test) 🧪
- [ ] Detail panel → STATUS row on every movie / show / anime: current status filled; greyed options say why on hover
- [ ] TV still running (e.g. Vox Machina, caught up) → Finished works; if episodes are left it asks first and marks them; hint "new episodes will bring it back to Watching"
- [ ] TV not premiered yet → only Watchlist; Watching / Finished / Dropped greyed
- [ ] Movie not out yet → Watched greyed ("Not out yet — releases …"); out → Watched / back to Watchlist
- [ ] Anime still airing → Completed greyed ("Still airing…"); not aired yet → only Plan to watch; finished anime → Completed marks all episodes (asks first); Dropped moves it to the Dropped list (asks first)
- [ ] Moving something with watched episodes to Watchlist asks first and keeps your progress
- [ ] Videos & music card: anime → Trailers · Openings · Endings · Soundtrack; TV → Trailers · Intro · Soundtrack; movies → Trailers · Soundtrack; each plays in the in-app player with Up Next; switching back and forth doesn't search again

## Next — Music: like, download, rank (built 2026-11-27, awaiting your test) 🧪
- [ ] Videos & music card: on an Opening / Ending / Intro / Soundtrack a row appears: ♡ Like · ⬇ Download · 🏆 Rank (not on trailers)
- [ ] Player: ♡ Like and ⬇ Download in the bottom bar for songs; they follow Up Next
- [ ] ⬇ → Audio (MP3) / Video (MP4 up to 1080p): toast, progress in Music → Downloads, file lands in your Downloads folder named "<show> - <song>"; Show in folder / Play work
- [ ] Sidebar ♪ Music (or Ctrl+M): Liked — Play all, Shuffle, filter chips, ▶ / ♥ / ⬇ / ⋯ per row, double-click plays; #rank badges on ranked songs
- [ ] Music search box (or "Find a song"): search any anime / show / movie (library first, then online) → its openings / endings / soundtrack → ▶ listen, ♥, Rank it
- [ ] Rankings: Openings & intros / Endings / Soundtracks; + Rank a song → "Which do you love more?" with ▶ Listen on both cards; Too close / Skip / Undo; drag to reorder; ⋯ re-rank / remove
- [ ] Liking / ranking something anywhere updates the Music page and every ♥ button at once

## Next — Themes (phases 0–4 built 2026-11-27, awaiting your test) 🧪
- [ ] Default look unchanged (Raikō Night)
- [ ] Settings → Appearance: click each of the 8 themes (incl. light Sakura Dawn / Studio Watercolor) — whole app recolours live, fonts change; accent swatches; text size 90–125 %
- [ ] Hover a theme → Preview: walkthrough (Home → Library → detail panel → Settings button), ‹ › / ← →, Apply keeps it, Cancel / Esc restores exactly
- [ ] Motion Full / Calm / Off; "Follow Windows" (Settings → Accessibility → Animation effects off = still); Rai toggle
- [ ] Events (run `main.py --date 2026-12-25`, `--date 2026-10-30`, `--date 2026-12-31`, `--date 2026-10-03`):
  - [ ] default theme → full event look; your own theme → decorations only; banner wording matches
  - [ ] Keep it / Switch back / Try the other looks; Nice / Go full / No decorations; ✕ → pointer on the Settings button (once)
  - [ ] greeting ("Merry Christmas"), ornaments (Santa hat, holly, snowcap, bats, pumpkin, lanterns), Rai's outfit, ambient effects in sidebar/header only
  - [ ] Home spotlight starts with the event: animated centrepiece (tree / jack-o'-lantern / fireworks / sparkles) + picks (your Watchlist first), Preview & add / Next pick
  - [ ] Settings → Appearance → Event themes: per-event Automatic / Full / Decorations / Off, look, Preview, "Ask me first", "Bring it back"
  - [ ] after the event (normal date) → "<event> is over — back to <theme>" toast
  - [ ] anime events: `--date 2026-10-03` (Black Clover S2 premiere, on your list) → banner with its characters, "Wear its colours", spotlight with its art, characters orbiting, Trailer; `--date 2026-09-27` (a finale) → "Thank you, …", Rank its songs; Season Premiere Week shows the season's most anticipated
  - [ ] Settings → Event themes: "Big premiere days" / "Farewells" rows (Automatic / Full / Decorations / Off)
  - [ ] `--simulate premiere:"One Piece"` → ticket moment (logo, backdrop, stub, Watch the trailer / Add to my list), sidebar logo with Luffy in the core + "Premiere · ONE PIECE", banner portraits, spotlight with title logo and orbiting characters
  - [ ] `--simulate farewell:Frieren` → rolling end credits, Rank its songs
  - [ ] `--date 2026-10-31 --simulate premiere:"Chainsaw Man"` → Halloween look kept; letter first, then the ticket; banner has two rows; spotlight leads with the premiere
  - [ ] holiday letters: `--date 2026-12-25`, `2026-10-31`, `2027-01-01`; logo wears Santa / witch / party hat; each letter shows once ("Read our note" re-opens)
  - [ ] milestones: your next one (2,500 episodes / 10 movies / 100 series) → toast + short confetti, once

## After 3.0 🕒
- [ ] Release addressing all risks (anime side included). Running list: docs/HARDENING_PLAN.md
- [ ] Trakt sync (separate version).

---

### Card information inventory (must survive the redesign)
- **Anime**: cover, title, status badge (AIRING / FINISHED / UPCOMING / ENDED / PLANNED / +N EPS / N UNWATCHED),
  episodes (watched/aired or watched/total), countdown to next episode, progress bar, score badge, "N behind",
  episode-count badge, new-season ribbon, quick-links button, rewatch badge & progress, sort overlays
  (AniList score / your rating), selection & hover states, accent border by state.
- **Dropped**: faded cover (colour on hover), DROPPED badge, stop point + how long ago, your reason.
- **Movies**: poster, title, runtime · year · seen N×, READY TO WATCH / IN CINEMAS / COMING SOON / WATCHED,
  HD date + days left / out in HD since / in cinemas date, your rating, accent border.
