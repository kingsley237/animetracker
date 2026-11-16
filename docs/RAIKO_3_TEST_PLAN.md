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
- [ ] **Spotlight**: your most pressing title on a full backdrop (new episodes first) with what's next, a line of
      synopsis, **✓ Watched …** and **Open details**; progress along the bottom; stat chips under it.
- [ ] **Continue watching**: the rest, art cards with the info underneath; hover shows a ✓ to mark watched.
- [ ] **This week**: 7 day columns (today highlighted) + Later, small posters with the episode and air time.
- [ ] **Ready to watch**: Watchlist movies out in HD.
- [ ] **Search everything** (Ctrl+K from anywhere): your anime, shows and movies grouped by library; Enter opens the
      first; "Find anime on AniList" / "Find movies & shows on TMDB" jump to Discover with the text filled in.
- [ ] Opening any title from Home lands in its own library with the panel open.
- (Statistics / Hall of Fame across types: dropped, as you retired those screens; Home's summary line covers counts.)

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
