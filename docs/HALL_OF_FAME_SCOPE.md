# Raikō — Hall of Fame (scope for approval)

Your all-time favourites, ranked honestly, shown off beautifully, and part of everything else in
Raikō. Built to beat what exists today:

| Platform | What they do | What's missing |
|---|---|---|
| AniList / MyAnimeList | a capped "favourites" collection | no honest order, no reasons, no story |
| Letterboxd | **Four Favourites** showcase + manual ranked lists | ranking is manual drag-and-drop; no help deciding |
| Flickchart / Beli | **"this or that?"** head-to-head ranking | apples-vs-oranges comparisons; no showcase or memories |
| TierMaker | tier lists (S/A/B…) | throwaway images, no library behind them |

Raikō combines all four strengths, fixes their weaknesses, and connects it to your real history
(ratings, episodes, rewatches, time spent).

## 1. Structure — three wings, one Hall

- **Wings: Miroku (anime) · Kinema Movies · Kinema TV.** Each wing is its own ranking — comparing a
  48-episode anime to a 2-hour film is exactly the "apples vs oranges" problem users hate in Beli.
  *Decision: yes, Kinema gets a Hall of Fame too — two wings (movies and TV kept apart).*
- **The Pantheon (cross-wing showcase):** your **Top 4 of everything** — four pins chosen from any
  wing, Letterboxd-style, shown at the top of the Hall (and optionally on Home).
- **Unlimited ranked list per wing**, plus **tiers** (S · A · B · C by default, renameable, colours)
  as a second lens on the same list.
- Your existing **10 Hall of Fame rankings are restored** into the Miroku wing in the same order
  (they were kept in the library file when the old screen was retired).

## 2. Ranking engine — honest and quick

- **Induct → place by "this or that?"**: Raikō asks *"Which do you love more?"* showing the new title
  and one already in the Hall, starting from the middle (binary insertion, like Flickchart). Exact
  position in **⌈log₂ n⌉ questions** — 10 titles ≈ 4 questions, 100 ≈ 7.
- **Skip / "too close to call" / undo** on every question (Beli's best escape hatches); a tie
  places them side by side.
- **Drag-and-drop** to fine-tune at any time; **re-rank** a title (asks again).
- **Rank history**: every move is remembered — "▲ 2 since March", the day it entered the Top 10.
- No Elo/Glicko scores: they wobble on small personal lists; insertion is exact and stable.

## 3. Each entry is a plaque

A plaque shows the title's art (accent colour taken from the artwork), rank + tier, and its story:
- **Why it's here** — your note (one line or a paragraph), and your **favourite moment** (a free-text
  quote/scene).
- **Inducted on** date (and anniversary nudges: "1 year in your Hall").
- From your real history: **your rating**, **first watched → finished** dates, **time spent**,
  **rewatches**, **best episode / season** (from your episode & season ratings), community score vs yours.
- Optional **favourite character** (anime: from AniList characters; TV/movies: from the cast).

## 4. Views

- **Showcase** (default): the Pantheon on top, then each wing as a big ranked gallery — #1 large,
  #2–#3 medium, then the grid; rank numbers set in large type.
- **List**: ranked rows with plaques, inline drag handles.
- **Tiers**: TierMaker-style rows (S/A/B/C…), drag between tiers; tiers stay consistent with rank.
- **Timeline**: inductions over the years ("2024: you inducted 3 · Frieren entered at #2").
- **Your canon in numbers**: genres, studios/networks, decades, formats, average length — what your
  Hall says about your taste.

## 5. Moments that make it feel special

- **Induction ceremony**: finish something you rate 6/6 (Masterpiece) and Raikō offers to induct it;
  a short, tasteful animation when it takes its place.
- **"Is it still your #1?"** — an occasional gentle re-check of the top spots (never nagging; off by
  default after the first ask).
- **Share card**: export a beautiful PNG of your Pantheon, a wing's Top 10, or your tier list
  (Letterboxd-style), saved locally — no account or server needed.

## 6. Connected to the rest of Raikō

- Sidebar: **Hall of Fame** under Home (one page, wing tabs).
- Detail panels: "★ #3 in your Hall of Fame" badge + Induct / Re-rank buttons; plaque preview.
- **For you** recommendations weigh Hall of Fame titles most.
- Data Doctor checks the Hall (ranks without gaps, titles still in the library).
- Later (with Trakt / AniList account sync): optional sync of the Pantheon to AniList favourites.

## 7. Data

- `hall_of_fame` (existing) gains: `wing`, `tier`, `inducted_at`, `note`, `moment`, `character`,
  `pinned` (Pantheon slot 1–4); new `hof_history` (title, from rank, to rank, when).
- Eligible: anime/TV **Completed** (TV also with ≥1 finished season), movies **Watched**. Removing a
  title from the library asks whether to keep its plaque.

## 8. Build plan (one release, tested by you before shipping)

1. Data + migration (restore your 10) · 2. Ranking engine (this-or-that, skip/tie/undo, drag) ·
3. Hall page (Showcase, List, Tiers, Timeline, Numbers) · 4. Plaques + panel integration ·
5. Induction ceremony + share card · 6. Tests, screenshots, checklist.

## Decisions for you
1. Wings: **separate Miroku / Movies / TV + cross-wing Pantheon (recommended)** — or one mixed list?
2. Ranking: **this-or-that + drag (recommended)** — or drag-only?
3. Pantheon on Home: **yes, small strip under the spotlight** — or Hall page only?
