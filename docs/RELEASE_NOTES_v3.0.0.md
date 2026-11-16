# Raikō 3.0.0 — Miroku is now Raikō

**Everything you watch, in one light.** Your anime tracker grows into one app with two libraries:
**Miroku** for anime (AniList) and **Kinema** for TV shows and movies (TMDB). Your anime library,
ratings, notes and settings carry over automatically, and a safety copy of your library is taken
before anything is upgraded.

## New

### Home
- Opens on **Home**: a spotlight that rotates through news about your library — **NEW EPISODE**
  (one-click ✓ Watched), **OUT IN HD**, **IN CINEMAS**, **NEW SEASON**, **NEW TRAILER**, or
  **NEXT TO AIR** with a live countdown when you're caught up — followed by **FOR YOU** picks
  (clearly marked, with the reason) that open in Discover.
- Stat chips, a **This week** schedule (7 days + later) and **Ready to watch** movies out in HD.
- **Search everything (Ctrl+K)**: anime, shows and movies in one box, with AniList / TMDB fallbacks.

### Kinema — TV shows & movies
- **Movies**: Watchlist and Watched, release timeline (cinemas / digital HD / disc) for your country,
  "Ready to watch" vs "Waiting for HD" shelves, where to stream / rent / buy (JustWatch), trailers,
  cast, franchise, rewatch log. Unreleased films can't be marked watched.
- **TV shows**: seasons and episodes, up next with one-click mark, "watched up to here", per-episode
  and per-season ratings, the panel opens on the season you're on, "Seen earlier seasons" when you
  add a running show.
- **Alerts**: out in HD, HD date announced, new episodes, new season, premiere date, new trailer —
  once each, never repeated, and quiet on the first sync.
- **Discover** for movies and TV: For you (from what you watched and saved), Coming soon, Trending,
  Just out in HD, In cinemas, Top rated, Airing this week, New shows… with genre filters, sorting, and
  a preview showing the **official trailer** and the cast.

### Miroku — anime, redesigned
- Cards and the Watching panel in the new style: up next, progress, next-episode countdown,
  episodes in blocks of 50 for long shows, hover ✓ to mark the next episode.
- **Discover** rebuilt on the same browser: For you, This season, Next season, Trending, Top rated,
  Most popular; add as Plan to Watch, Watching or Finished.

### Look & feel
- New **Raikō** identity: the Aperture mark (three arcs — Miroku indigo, Kinema amber, TV sky —
  around a point of light), new icon, splash, sidebar and library marks.
- Premium cards: hairline borders, glass status pills, colour only where it matters.
- Themed status banners inside the window: no internet, AniList down, **TMDB down** (new check).
- New **onboarding**: "Miroku is now Raikō" welcome, your country for release dates, and a 1-minute
  tour (replay it from Settings → About).

### Reliability
- **Data Doctor** checks anime, movies, TV, the library file and app errors; a background check and
  any unexpected error offer **Open Data Doctor** in one click.
- Unexpected errors are logged to `~/.animetracker/error.log` instead of closing the app.
- Quick links: one-click label presets.

## Changed / removed
- Calendar, Miroku Stream, Hall of Fame and Statistics screens are retired. Hall of Fame-only
  favourites move into **Completed** with every episode marked watched (your rankings stay saved in
  the library file).
- The app, window, installer folder and shortcut are now **Raikō** (`Raiko.exe`); the old Miroku
  Desktop shortcut is replaced.

## Fixed
- Opening a Plan to Watch anime no longer pops a "Trailer available" alert for a trailer you already had.
- A library backup could hang; finished background downloads no longer log errors after closing.

---
TV and movie data from TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.
Where-to-watch data by JustWatch. Anime data from AniList.
