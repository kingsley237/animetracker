# Changelog

All notable changes to AnimeTracker are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [2.0.0] — 2025

### Added
- Full PyQt6 native desktop GUI replacing the terminal interface
- Cover art thumbnails and banner images fetched from AniList
- Live ticking countdown timers per anime card
- SQLite database replacing the old flat JSON file
- Detail panel with synopsis, episode list, per-episode ratings, overall rating
- Hall of Fame — personal ranked list of all-time favourites with notes
- Discover page — seasonal chart, trending, and upcoming anime browser
- Statistics page — watch counts, genre breakdown, score distribution
- Real-time stats strip that updates on every status change
- Smart status logic — finished anime cannot be added to library
- Smart episode logic — cannot rate episodes not yet watched
- Locked episode rows for episodes not yet aired
- Automatic background airing refresh every 10 minutes
- Image cache with auto-purge and configurable size limit
- Auto-backup system keeping last 5 database snapshots
- One-click migration from old `anime_info.json` format
- Full-text search across the library (SQLite FTS5)
- App icon generated at multiple resolutions (ICO + PNG)
- Standalone executable build script (`build_exe.py`)
- About page with author credit (Mello) and logo
- MIT License

### Changed
- Storage: JSON flat file → SQLite with WAL mode and foreign keys
- API: same AniList GraphQL endpoint, now fetches full data (cover, banner, synopsis, studios, trailer)
- Interface: terminal ANSI → native PyQt6 dark-theme GUI

### Removed
- Terminal / CLI interface
- ANSI color codes and ASCII art
- Global mutable state (replaced with Qt signals/slots)

---

## [1.0.0] — 2022

- Initial terminal release (`release_date.py`)
- AniList GraphQL API integration
- Episode tracking (watched, downloaded, ratings 1–6)
- Timezone-aware countdowns
- Seasonal chart browser
- Dropped anime list with undo
- JSON flat file storage (`anime_info.json`)

---

## Future updates

- Check release descriptions on changes/new implementations/fixes etc
