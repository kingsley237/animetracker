# Raikō — risk-hardening release (after 3.0.0)

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
