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
- [ ] **Kinema · Movies & TV**: Movies, Discover (TV joins in phase 3).
- [ ] **Personal**: Hall of Fame, Statistics.
- [ ] Add button changes per section (indigo sparkle / amber film frame); Ctrl+N works.

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

## TV shows (phase 3) 🕒
- [ ] Seasons & episodes, progress (S02E05), per-season ratings, new episode/season alerts, panels per status.
- [ ] Kinema Discover gains TV lists; TV add button (sky-blue screen).

## One app (phase 4) 🕒
- [ ] Up Next home across anime, TV and movies; unified search; stats & Hall of Fame across types.

## Rebrand to Raikō (phase 5) 🕒
- [ ] New logo system (Raikō + Miroku + Kinema marks), icons/.ico, splash, sidebar, About, window titles,
      install folder/shortcut/exe/zip names, README, release naming.
- [ ] **Premium card redesign** for anime, TV and movies — every piece of information each card shows
      today stays (better represented, never removed). See "Card information inventory" below.
- [ ] **New onboarding** for first-time users covering Miroku + Kinema.

## Polish & release (phase 6) 🕒
- [ ] Visual pass, performance, full tests, upgrade check on a copy of your real library, v3.0.0.

## After 3.0 🕒
- [ ] Release addressing all risks (anime side included).
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
