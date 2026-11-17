"""Hall of Fame: wings, ranking, Pantheon, migration of the old Hall."""
import random

import pytest

from tests.conftest import add_anime


def _done(db, title, media="anime"):
    return add_anime(db, title, "completed", media_type=media)


def test_old_hall_is_restored_in_order(db):
    from core.hall import Hall
    a, b, c = _done(db, "A"), _done(db, "B"), _done(db, "C")
    conn = db._get_conn()
    conn.execute("CREATE TABLE IF NOT EXISTS hall_of_fame (rank INTEGER PRIMARY KEY, anime_id INTEGER, "
                 "note TEXT, added_at INTEGER, tier TEXT)")
    conn.executemany("INSERT INTO hall_of_fame VALUES (?,?,?,?,?)",
                     [(1, b, "", 1, "S"), (2, c, "", 1, "A"), (3, a, "great", 1, None)])
    conn.commit()
    h = Hall(db)
    assert [(e["lib_id"], e["tier"]) for e in h.entries("anime")] == [(b, "S"), (c, "A"), (a, None)]
    assert h.entry(a)["note"] == "great"
    Hall(db)                                         # second open: no duplicates
    assert h.count("anime") == 3


def test_wings_are_separate_and_ranks_stay_gapless(db):
    from core.hall import Hall
    h = Hall(db)
    an = [_done(db, f"A{i}") for i in range(4)]
    mv = _done(db, "Film", "movie")
    for i, x in enumerate(an):
        h.insert_at(x, i + 1)
    h.insert_at(mv, 1)
    assert [e["lib_id"] for e in h.entries("movie")] == [mv]
    h.insert_at(_done(db, "New"), 2)                # shifts the rest down
    assert [e["rank"] for e in h.entries("anime")] == [1, 2, 3, 4, 5]
    h.move(an[3], 1)
    assert h.entries("anime")[0]["lib_id"] == an[3]
    assert h.movement(an[3]) == 4                    # 5 -> 1
    h.remove(an[0])
    assert [e["rank"] for e in h.entries("anime")] == [1, 2, 3, 4]


def test_pantheon_pins_across_wings(db):
    from core.hall import Hall
    h = Hall(db)
    a, m, t = _done(db, "A"), _done(db, "M", "movie"), _done(db, "T", "tv")
    for x in (a, m, t):
        h.insert_at(x, 1)
    h.auto_pantheon()
    assert [e["lib_id"] if e else None for e in h.pantheon()] == [a, m, t, None]
    h.pin(t, 1)                                       # takes slot 1, A loses it
    assert [e["lib_id"] if e else None for e in h.pantheon()] == [t, m, None, None]


def test_eligibility(db):
    from core.hall import Hall
    h = Hall(db)
    assert h.eligible(db.get_anime_by_id(_done(db, "Done")))
    assert not h.eligible(db.get_anime_by_id(add_anime(db, "Watching", "watching")))
    assert not h.eligible(db.get_anime_by_id(add_anime(db, "Planned", "planned", media_type="movie")))


@pytest.mark.parametrize("n", [0, 1, 2, 7, 10, 33, 100])
def test_insertion_finds_exact_place_in_log_n(n):
    import math
    from core.hall import InsertionSession
    for truth in range(n + 1):
        s = InsertionSession(list(range(n)))
        while not s.done:
            q = s.question()
            if q is None:
                break
            s.answer("new" if truth <= q else "existing")
        assert s.position == truth + 1
        assert s.asked <= max(1, math.ceil(math.log2(n + 1)))


def test_insertion_skip_tie_undo():
    from core.hall import InsertionSession
    s = InsertionSession(list(range(10)))
    first = s.question()
    s.answer("skip")
    assert s.question() != first and s.asked == 0
    s.answer("existing")
    assert s.undo() and s.asked == 0
    q = s.question()
    s.answer("tie")
    assert s.done and s.position == q + 2            # right below the one it tied with
    # skipping everything still ends somewhere sensible
    s = InsertionSession(list(range(5)))
    for _ in range(10):
        if s.question() is None:
            break
        s.answer("skip")
    assert s.done and 1 <= s.position <= 6


# ── Honours ───────────────────────────────────────────────────────────────────

def test_honours_awards_places_and_compaction(db):
    from core.honours import Honours
    h = Honours(db)
    a, b, c = _done(db, "A"), _done(db, "B"), _done(db, "C")
    aid = h.add_category("soundtrack")
    assert h.category(aid)["label"] == "Best soundtrack" and h.category(aid)["kind"] == "title"
    for place, x in enumerate((a, b, c)):
        h.set_entry(aid, place, h.title_entry(x))
    h.set_reason(aid, 0, "goosebumps")
    assert [e["lib_ids"] for e in h.entries(aid)] == [[a], [b], [c]]
    h.swap(aid, 0, 2)
    assert h.entries(aid)[0]["lib_ids"] == [c] and h.entries(aid)[2]["reason"] == "goosebumps"
    h.clear_entry(aid, 0)                              # runners-up move up
    assert [e["lib_ids"] if e else None for e in h.entries(aid)] == [[b], [a], None]
    assert h.count() == 1
    yid = h.add_category("year", "Best of 2024")
    assert h.category(yid)["label"] == "Best of 2024"
    h.move_category(yid, -1)
    assert [x["id"] for x in h.categories()] == [yid, aid]
    h.remove_category(aid)
    assert [x["id"] for x in h.categories()] == [yid]


def test_groups_from_titles_sequels_and_collections(db):
    from core.honours import Honours
    h = Honours(db)
    s1 = add_anime(db, "Shingeki no Kyojin", "completed", anilist_id=10, start_ts=1)
    s2 = add_anime(db, "Shingeki no Kyojin Season 2", "completed", anilist_id=11, start_ts=2)
    s3 = add_anime(db, "Shingeki no Kyojin Season 3", "watching", anilist_id=12, start_ts=3)
    x1 = add_anime(db, "Kizumonogatari I", "completed", anilist_id=20, start_ts=1)
    x2 = add_anime(db, "Owarimonogatari", "completed", anilist_id=21, start_ts=2)   # different name: needs AniList
    tri = h.groups(3)
    assert [p["lib_id"] for p in tri[0]["parts"]] == [s1, s2, s3] and tri[0]["name"] == "Shingeki no Kyojin"
    assert not any({x1, x2} <= {p["lib_id"] for p in g["parts"]} for g in h.groups())
    h._set_meta("anime_sequels", {"20": [21]})
    assert any({x1, x2} == {p["lib_id"] for p in g["parts"]} for g in h.groups(2))
    m1 = add_anime(db, "Dune", "completed", media_type="movie", tmdb_id=438631)
    h._set_meta("movie_collections", {"726871": {"name": "Dune Collection", "parts": [
        {"id": 438631, "title": "Dune", "release_date": "2021-09-15"},
        {"id": 693134, "title": "Dune: Part Two", "release_date": "2024-02-27"}]}})
    duo = [g for g in h.groups(2) if g["media"] == "movie"][0]
    assert duo["name"] == "Dune Collection" and duo["parts"][0]["lib_id"] == m1 and duo["parts"][1]["lib_id"] is None
    e = h.group_entry(duo)
    assert e["kind"] == "group" and e["lib_ids"] == [m1] and "1 watched" in e["sub"]


def test_entry_builders(db, monkeypatch):
    from core.honours import Honours
    h = Honours(db)
    a = add_anime(db, "Show", "completed", characters=[{"name": "Light Yagami", "role": "Main", "image": "x"}])
    assert h.episode_entry(a, 25)["label"] == "Episode 25"
    assert h.character_entry(a, db.get_anime_by_id(a)["characters"][0])["label"] == "Light Yagami"
    m = add_anime(db, "Film", "completed", media_type="movie")
    ch = h.character_entry(m, {"name": "Matt Damon", "role": "Odysseus"})
    assert ch["label"] == "Odysseus" and ch["sub"].startswith("Matt Damon")
    assert h.theme_entry(a, "Unravel")["label"] == "Unravel"
    assert "Studio" in h.studios()


# ── integration ───────────────────────────────────────────────────────────────

def test_for_you_boost_and_data_doctor_tidy(db):
    from core.data_health import Scanner
    from core.hall import Hall, boosts, problems
    h = Hall(db)
    a, b = _done(db, "A"), _done(db, "B")
    h.insert_at(a, 1)
    h.insert_at(b, 2)
    w = boosts(db)
    assert w[a] > w[b] > 3.0                        # above any 6/6 rating (3.0)
    db._get_conn().execute("DELETE FROM anime WHERE id=?", (a,))
    db._get_conn().commit()
    assert problems(db) == {"missing": 1, "gaps": 0}
    issue = next(i for i in Scanner(db).scan(quick=True) if i.issue_id == "hall_tidy")
    issue.fix_fn()
    assert problems(db) == {"missing": 0, "gaps": 0} and h.entries("anime")[0]["rank"] == 1


def test_hall_ui_smoke(qapp, db):
    """Every view, wing, dialog and the share card build without errors."""
    from tests.conftest import pump
    from ui.hall_page import HallPage, PlaqueDialog
    from ui.hall_rank import RankDialog
    from ui.hall_share import render
    from core.honours import Honours
    ids = [_done(db, f"T{i}") for i in range(5)]
    mv = _done(db, "Film", "movie")
    page = HallPage(db)
    page.resize(1400, 1000)
    page.show()
    page.load()
    assert "Induct" in "".join(w.text() for w in page.findChildren(type(page.share_btn)))   # empty wing
    for i, x in enumerate(ids):
        page.hall.insert_at(x, i + 1)
    page.hall.insert_at(mv, 1)
    Honours(db).add_category("trilogy")
    for wing in ("anime", "movie", "tv", "honours"):
        page._set_wing(wing)
        for view in ("showcase", "list", "tiers", "timeline", "numbers"):
            page._set_view(view)
            pump(20)
    assert page.hall.pantheon()[0]["lib_id"] == ids[0]           # auto-pinned #1s
    # re-rank through the dialog: the last one becomes #1
    d = RankDialog(page.hall, ids[4], page)
    while d.pages.currentIndex() == 0:
        d._answer("new")
    assert d.position == 1 and page.hall.entries("anime")[0]["lib_id"] == ids[4]
    d.close()
    p = PlaqueDialog(page.hall, ids[0], page)
    p.note.setPlainText("best ever")
    p._set_tier("S")
    p.done(0)
    assert page.hall.entry(ids[0])["note"] == "best ever" and page.hall.entry(ids[0])["tier"] == "S"
    for m in ("pantheon", "top", "tiers", "honours"):
        assert not render(page.hall, m, "anime", {}).isNull()
    page.close()


def test_detail_panel_hall_button(qapp, db):
    from core.hall import Hall
    from ui.detail_panel import DetailPanel
    a = _done(db, "Done")
    w = add_anime(db, "Watching", "watching")
    panel = DetailPanel(db)
    panel.load_anime(db.get_anime_by_id(w))
    assert panel.hof_btn.isHidden()
    panel.load_anime(db.get_anime_by_id(a))
    assert not panel.hof_btn.isHidden() and "Induct" in panel.hof_btn.text()
    Hall(db).insert_at(a, 1)
    panel.load_anime(db.get_anime_by_id(a))
    assert "#1" in panel.hof_btn.text()
    h = Hall(db)
    h.decline_offer(a)
    assert h.offer_declined(a) and not h.offer_declined(w)


# ── finding things that aren't in the library ─────────────────────────────────

def _movie_hit(i, title):
    return {"media_type": "movie", "provider_id": i, "title": title, "year": 2001, "poster_url": "",
            "score": 80, "overview": "", "raw": {}}


def test_search_groups_finds_collections_outside_library(db, monkeypatch):
    from core import api, tmdb
    from core.honours import Honours
    mine = add_anime(db, "The Fellowship of the Ring", "completed", media_type="movie", tmdb_id=120)
    monkeypatch.setattr(tmdb, "get", lambda path, params=None, **k:
                        {"results": [{"id": 119, "name": "The Lord of the Rings Collection"}]}
                        if path == "/search/collection" else None)
    monkeypatch.setattr(tmdb, "collection", lambda cid: {"name": "The Lord of the Rings Collection", "parts": [
        {"id": 122, "title": "The Return of the King", "release_date": "2003-12-01"},
        {"id": 120, "title": "The Fellowship of the Ring", "release_date": "2001-12-18"},
        {"id": 121, "title": "The Two Towers", "release_date": "2002-12-18"},
        {"id": 999, "title": "Untitled", "release_date": ""}]})
    monkeypatch.setattr(api, "search_anime", lambda q, page=1, per_page=10: [])
    gs = Honours(db).search_groups("lord of the rings")
    assert len(gs) == 1 and gs[0]["name"] == "The Lord of the Rings Collection"
    parts = gs[0]["parts"]
    assert [p["tmdb_id"] for p in parts] == [120, 121, 122]          # in release order, undated dropped
    assert parts[0]["lib_id"] == mine and parts[1]["lib_id"] is None
    e = Honours(db).group_entry(gs[0])
    assert e["extra"]["parts"][1]["tmdb_id"] == 121


def test_quick_add_movie_as_watched_then_induct(db, monkeypatch):
    from core import providers
    from core.hall import Hall
    from core.quick_add import add_watched, in_library
    monkeypatch.setattr(providers.get_provider("movie"), "details",
                        lambda pid: {"media_type": "movie", "tmdb_id": pid, "romaji_title": "The Two Towers",
                                     "english_title": "The Two Towers", "status": "FINISHED"})
    lib_id = add_watched(db, _movie_hit(121, "The Two Towers"))
    row = db.get_anime_by_id(lib_id)
    assert row["media_type"] == "movie" and row["watch_status"] == "completed"
    assert in_library(db, _movie_hit(121, "x"))["id"] == lib_id
    assert add_watched(db, _movie_hit(121, "again")) == lib_id        # no duplicate
    h = Hall(db)
    assert h.eligible(row)
    h.insert_at(lib_id, 1)
    assert h.entries("movie")[0]["title"] == "The Two Towers"


def test_online_finder_adds_and_emits(qapp, db, monkeypatch):
    from tests.conftest import pump, wait_until
    from PyQt6.QtWidgets import QMessageBox
    from core import quick_add
    from ui.hall_rank import OnlineFinder
    monkeypatch.setattr(quick_add, "search", lambda kind, q, page=1:
                        [_movie_hit(page * 10 + i, f"Film {page}-{i}") for i in range(3)])
    monkeypatch.setattr(quick_add, "add_watched", lambda dbx, hit: 777)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    f = OnlineFinder(db)
    got = []
    f.added.connect(got.append)
    f.set_query("movie", "f")
    assert not f.hits                                  # one letter: just the hint
    f.set_query("movie", "film")
    assert wait_until(lambda: len(f.hits) == 3)
    f._more()
    assert wait_until(lambda: len(f.hits) == 6)        # Show more appends the next page
    f._pick(4)
    assert wait_until(lambda: got == [777])
    f.deleteLater()
    pump(20)


def test_discover_show_more_loads_next_page(qapp, db, monkeypatch):
    from tests.conftest import pump, wait_until
    from core import kinema_discover as kd
    from ui.kinema_add_dialog import MovieBrowser
    calls = []

    def load(source, db=None, kind="movie", page=1):
        calls.append(page)
        return [] if page > 2 else [_movie_hit(page * 100 + i, f"P{page} {i}") for i in range(20)]
    monkeypatch.setattr(kd, "load_source", load)
    monkeypatch.setattr(kd, "genres", lambda kind="movie": [])
    b = MovieBrowser(db, kind="movie", start_source="trending")
    b.show()
    assert wait_until(lambda: len(b._tiles) == 20)
    assert b.more_btn.isVisible()
    b._more()
    assert wait_until(lambda: len(b._tiles) == 40) and calls[-1] == 2
    b._more()
    assert wait_until(lambda: b.more_btn.isHidden()) and "everything" in b.status.text()
    b.close()
    b.deleteLater()
    pump(50)


def test_full_cast_for_character_awards(qapp, db, monkeypatch):
    from tests.conftest import pump, wait_until
    from core import api, tmdb
    from core.honours import Honours
    from ui.hall_honours import _CharPicker

    def post(q, v, timeout=10, retries=3):
        page = v["page"]
        edges = [{"role": "BACKGROUND", "node": {"name": {"full": f"C{page}-{i}"}, "image": {"large": ""}}}
                 for i in range(25)]
        return {"Media": {"characters": {"pageInfo": {"hasNextPage": page < 3}, "edges": edges}}}
    monkeypatch.setattr(api, "_post", post)
    a = add_anime(db, "Big Cast", "completed", anilist_id=5,
                  characters=[{"name": "C1-0", "role": "Background", "image": ""}])
    h = Honours(db)
    assert len(h.all_characters(a)) == 75                       # every page, not just the top few
    monkeypatch.setattr(tmdb, "get", lambda path, params=None, **k: {"cast": [
        {"name": "Actor", "roles": [{"character": "The Villain"}], "profile_path": None}]}
        if "aggregate_credits" in path else None)
    t = add_anime(db, "Show", "completed", media_type="tv", tmdb_id=9)
    assert h.all_characters(t) == [{"name": "Actor", "role": "The Villain", "image": ""}]
    p = _CharPicker(h, a, "anime", db.get_anime_by_id(a)["characters"])
    assert wait_until(lambda: len(p.chars) == 75)
    assert not p.more.isHidden()                                # 48 shown, Show more for the rest
    p._more()
    assert p.more.isHidden()
    p.filter.setText("c2-1")
    assert len(p._matches()) == 11                              # C2-1, C2-10..C2-19
    p.deleteLater()
    pump(20)


def test_character_order_and_role_filter(qapp, db, monkeypatch):
    from tests.conftest import pump, wait_until
    from core import api
    from core.honours import Honours
    from ui.hall_honours import _CharPicker
    sorts = []

    def post(q, v, timeout=10, retries=3):
        sorts.append(q.split("sort:")[1].split(")")[0].strip())
        edges = [{"role": r, "node": {"name": {"full": n}, "image": {"large": ""}}}
                 for n, r in (("Aizen", "SUPPORTING"), ("Ichigo", "MAIN"), ("Extra", "BACKGROUND"))]
        return {"Media": {"characters": {"pageInfo": {"hasNextPage": False}, "edges": edges}}}
    monkeypatch.setattr(api, "_post", post)
    a = add_anime(db, "Bleach", "completed", anilist_id=269)
    h = Honours(db)
    assert [c["name"] for c in h.character_page(a, 1)[0]] == ["Aizen", "Ichigo", "Extra"]
    assert sorts[-1] == "[FAVOURITES_DESC]"                       # villains etc.: most-loved first
    h.character_page(a, 1, order="role")
    assert sorts[-1] == "[ROLE, FAVOURITES_DESC]"                 # protagonist: main characters first
    p = _CharPicker(h, a, "anime", [])
    assert wait_until(lambda: len(p.chars) == 3)
    p._set_role("Main")
    assert [c["name"] for c in p._matches()] == ["Ichigo"]
    p._set_role("")
    assert len(p._matches()) == 3
    p.deleteLater()
    pump(20)
