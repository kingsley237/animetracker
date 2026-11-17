"""Search that understands partial words: local catalogue + ranking."""
from tests.conftest import add_anime, pump, wait_until


def _hit(kind, pid, title, pop, **raw):
    return {"media_type": kind, "provider_id": pid, "title": title, "popularity": pop,
            "poster_url": "", "overview": "x", "year": 2020, "raw": raw}


def test_ranking_prefers_title_start_then_word_start_then_popularity():
    from core.catalog import rank
    hits = [_hit("tv", 1, "Dino Dex", 900), _hit("tv", 2, "Dex Hamilton", 5),
            _hit("tv", 3, "Dexter", 400), _hit("tv", 4, "Memoires d'ex", 999)]
    assert [h["provider_id"] for h in rank(hits, "dex")] == [3, 2, 1, 4]


def test_catalogue_partial_words_and_synonyms(monkeypatch):
    import core.catalog as cat
    cat._save("anime", [
        _hit("anime", 10, "Vinland Saga", 900_000, synonyms=[]),
        _hit("anime", 11, "Howl's Moving Castle", 990_000, synonyms=[]),
        _hit("anime", 12, "JUJUTSU KAISEN", 1_000_000, synonyms=["JJK"]),
    ])
    assert [h["provider_id"] for h in cat.search("anime", "vin")] == [10]      # no "Mo-vin-g" noise
    assert [h["provider_id"] for h in cat.search("anime", "jjk")] == [12]      # synonyms count
    assert cat.search("anime", "v") == []                                       # too short


def test_discover_search_shows_catalogue_instantly(qapp, db, monkeypatch):
    import core.catalog as cat
    from core import api, miroku_discover as md
    from ui.kinema_add_dialog import MovieBrowser
    cat._save("anime", [_hit("anime", 10, "Vinland Saga", 900_000, synonyms=[])])
    monkeypatch.setattr(md, "load_source", lambda *a, **k: [])
    monkeypatch.setattr(api, "search_anime", lambda q, page=1, per_page=10: [])   # AniList: nothing for "vin"
    b = MovieBrowser(db, kind="anime")
    b.show()
    pump(100)
    b.search.setText("vin")
    b._search()
    assert [t.hit["title"] for t in b._tiles] == ["Vinland Saga"]               # before the network answers
    pump(300)
    assert [t.hit["title"] for t in b._tiles] == ["Vinland Saga"]


def test_ctrl_k_suggests_titles_not_in_library(db):
    import core.catalog as cat
    from ui.home_page import HomePage
    cat._save("anime", [_hit("anime", 10, "Vinland Saga", 900_000, synonyms=[]),
                        _hit("anime", 11, "Vinland Saga Season 2", 500_000, synonyms=[])])
    add_anime(db, "VINLAND SAGA", "completed", anilist_id=10)
    sugg = HomePage.suggest(db, "vin")
    assert [h["provider_id"] for h in sugg] == [11]                            # the one you don't have
