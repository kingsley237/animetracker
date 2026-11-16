# Raikō — risk-hardening release (after 3.0.0)

The release after 3.0 addresses risks across the whole app (anime side included) before any new
features (Trakt sync comes after this, as its own version). Items are added here as they're found;
each gets tested by you before shipping.

## Queued

- [ ] **Welcome tour scrolls each target into view.** Replaying the tour (Settings → About) after
      scrolling down Home leaves the highlighted element off-screen — e.g. step 2 spotlights the search
      bar while the page is scrolled down, so neither the search bar nor part of the step card is
      visible. Fix: before spotlighting, scroll the page's scroll area so the target is visible (top of
      the page for header items), keep the step card fully inside the window, and re-measure after the
      scroll settles. Test: scroll Home to the bottom → Settings → About → Replay the welcome tour →
      every step shows its target and the whole card.
