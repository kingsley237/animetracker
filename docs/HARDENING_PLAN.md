# Raikō — fixes after 3.0 (the broad risk-hardening release was dropped on 2026-11-17)

The release after 3.0 addresses risks across the whole app (anime side included) before any new
features (Trakt sync comes after this, as its own version). Items are added here as they're found;
each gets tested by you before shipping.

## Queued

- [x] **Welcome tour scrolls each target into view.** (done on develop, awaiting your test) Replaying the tour (Settings → About) after
      scrolling down Home leaves the highlighted element off-screen — e.g. step 2 spotlights the search
      bar while the page is scrolled down, so neither the search bar nor part of the step card is
      visible. Fix: before spotlighting, scroll the page's scroll area so the target is visible (top of
      the page for header items), keep the step card fully inside the window, and re-measure after the
      scroll settles. Test: scroll Home to the bottom → Settings → About → Replay the welcome tour →
      every step shows its target and the whole card.

- [x] **Spotlight "For you" picks rotate.** (done on develop, awaiting your test) Today the spotlight always shows the same top 6 picks
      (the list is deterministic and only changes when the library changes). Fix: keep the whole pool
      (~27 across anime, movies and TV), show a fresh mix of 6 every few hours and on each start,
      always mixing the three libraries, and rest picks you've recently seen. Library news (new
      episode, out in HD…) still comes first; only the For you part rotates. Test: restart / wait a few
      hours → different picks, still a mix of anime, movies and TV.

- [x] **Search suggests as you type ("vin" → Vinland Saga).** AniList's search only matches nearly
      complete words ("vin"/"vinl"/"frie" return nothing; "vinla" finds Vinland Saga). Fix: suggestions
      as you type from (1) your library (partial titles), (2) a local catalogue of the most popular anime
      (a few thousand titles, refreshed weekly in the background), (3) AniList / TMDB results as they
      arrive; grouped in a dropdown (In your library · Anime · Movies · TV). Applies to Discover, Add and
      Ctrl+K. TMDB does answer partial words but ranks them poorly ("oppen" → Oppenheimer 3rd, "dex" →
      Dexter 4th, "sev" → no Severance): re-rank by how well the title's start matches + popularity.
      Test: type "vin", "frie", "dex", "sev", "oppen" in each Discover → the right title first, instantly.

## Proposed feature (own release, after hardening): notifications when Raikō is closed

- [x] Opt-in in Settings ("Notify me even when Raikō is closed", every 1/3/6 h + at log-in). Raikō
      registers a Windows scheduled task that starts it invisibly (`Raiko.exe --check`), runs the usual
      checks (new episodes, out in HD, new season, premiere dates, trailers), shows native Windows
      notifications for anything new, then exits (~10–20 s). Nothing runs between checks (no tray icon).
      Missed checks run on wake. Clicking a notification opens that title. Never repeats an alert; respects
      Windows Focus / Do Not Disturb; skips if Raikō is already open. Turning it off removes the task.
- [x] Bonus while Raikō is open or minimized: a red count badge on its taskbar button for new episodes /
      HD releases etc. (a badge can't exist on a closed app's icon in Windows — the notifications above
      cover the closed case).
