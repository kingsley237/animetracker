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
