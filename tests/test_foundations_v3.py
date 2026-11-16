"""Raikō 3.0 foundations: TMDB client, providers, v5 database upgrade."""
import json
import sqlite3
import sys
import types

import pytest

from tests.conftest import add_anime


# ── credentials ───────────────────────────────────────────────────────────────

@pytest.fixture
def no_embedded(monkeypatch):
    monkeypatch.setitem(sys.modules, "core._embedded_secrets", None)   # import fails


def test_credentials_precedence(monkeypatch, tmp_path, no_embedded):
    from core import tmdb
    from core.app_settings import app_settings
    monkeypatch.setattr(tmdb, "_ROOT", tmp_path)
    assert tmdb.get_credentials()["source"] == "" and not tmdb.has_credentials()

    (tmp_path / "secrets.local.json").write_text(json.dumps({"tmdb_read_token": "local.tok.en" * 8}))
    assert tmdb.get_credentials()["source"] == "local"

    emb = types.ModuleType("core._embedded_secrets")
    emb.TMDB_READ_TOKEN, emb.TMDB_API_KEY = "embedded-token", ""
    monkeypatch.setitem(sys.modules, "core._embedded_secrets", emb)
    assert tmdb.get_credentials()["source"] == "embedded"

    app_settings().setValue("tmdb_token_override", "0123456789abcdef0123456789abcdef")
    c = tmdb.get_credentials()
    assert c["source"] == "settings" and c["api_key"] and not c["token"]      # v3 key form


def test_no_key_means_no_request(monkeypatch, tmp_path, no_embedded):
    from core import tmdb
    monkeypatch.setattr(tmdb, "_ROOT", tmp_path)
    assert tmdb.get("/configuration") is None


def test_get_is_cached_and_never_raises(monkeypatch):
    from core import tmdb
    tmdb.clear_cache()
    monkeypatch.setattr(tmdb, "get_credentials", lambda: {"token": "t", "api_key": "", "source": "x"})
    calls = []

    class R:
        status_code = 200
        headers = {}
        def raise_for_status(self): pass
        def json(self): return {"ok": True}

    class S:
        def request(self, *a, **k):
            calls.append(1)
            return R()

    monkeypatch.setattr(tmdb, "_get_session", lambda: S())
    assert tmdb.get("/x") == {"ok": True}
    assert tmdb.get("/x") == {"ok": True} and len(calls) == 1       # second from cache
    tmdb.clear_cache()
    monkeypatch.setattr(tmdb, "_get_session", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tmdb.get("/y", retries=0) is None                         # offline -> None


# ── parsing helpers ───────────────────────────────────────────────────────────

def test_videos_order_and_where_to_watch_and_release_dates():
    from core import tmdb
    d = {
        "videos": {"results": [
            {"site": "YouTube", "key": "clip", "type": "Clip", "name": "A clip", "official": True},
            {"site": "YouTube", "key": "tr", "type": "Trailer", "name": "Trailer", "official": True},
            {"site": "Vimeo", "key": "v", "type": "Trailer"},
        ]},
        "watch/providers": {"results": {"US": {"flatrate": [{"provider_name": "Netflix"}],
                                               "rent": [{"provider_name": "Apple TV"}], "link": "L"}}},
        "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [
            {"type": 3, "release_date": "2024-03-01T00:00:00Z"},
            {"type": 4, "release_date": "2024-04-16T00:00:00Z"}]}]},
    }
    assert [v["id"] for v in tmdb.videos(d)] == ["tr", "clip"]
    w = tmdb.watch_providers(d, "US")
    assert w["stream"] == ["Netflix"] and w["rent"] == ["Apple TV"]
    assert tmdb.watch_providers(d, "FR")["stream"] == []
    assert tmdb.us_release_dates(d, "US") == {"theatrical": "2024-03-01", "digital": "2024-04-16"}


def test_tv_row_mapping():
    from core.providers import tv_row
    r = tv_row({
        "id": 7, "name": "Show", "original_name": "Show", "status": "Returning Series",
        "first_air_date": "2022-02-18", "number_of_episodes": 19, "episode_run_time": [50],
        "vote_average": 8.4, "genres": [{"name": "Drama"}], "networks": [{"name": "Apple TV+"}],
        "next_episode_to_air": {"air_date": "2027-01-10", "episode_number": 3, "season_number": 3},
        "seasons": [{"season_number": 0, "name": "Specials"},
                    {"season_number": 1, "episode_count": 9, "name": "Season 1"}],
        "credits": {"cast": [{"name": "Lead", "character": "Mark"}]},
    })
    assert r["media_type"] == "tv" and r["status"] == "RELEASING" and r["format"] == "TV"
    assert r["average_score"] == 84 and r["duration"] == 50 and r["studios"] == ["Apple TV+"]
    assert [s["season_number"] for s in r["_seasons"]] == [1]      # specials left out
    assert r["next_episode_num"] == 3 and r["next_episode_at"] and r["_next_season"] == 3


def test_movie_row_mapping():
    from core.providers import movie_row
    r = movie_row({"id": 9, "title": "Film", "status": "Post Production", "runtime": 120,
                   "release_date": "2027-05-01", "belongs_to_collection": {"id": 3, "name": "Saga"}})
    assert r["media_type"] == "movie" and r["status"] == "NOT_YET_RELEASED" and r["total_episodes"] == 1
    assert r["_collection"] == {"id": 3, "name": "Saga"} and r["start_exact"] == 1


def test_provider_registry():
    from core.providers import MEDIA_TYPES, get_provider
    assert [get_provider(m).media_type for m in MEDIA_TYPES] == ["anime", "tv", "movie"]


# ── database v5 ───────────────────────────────────────────────────────────────

def test_existing_screens_stay_anime_only(db):
    a = add_anime(db, "Anime", "watching")
    db.add_anime({"romaji_title": "A Show", "watch_status": "watching", "media_type": "tv", "tmdb_id": 1})
    assert [x["id"] for x in db.get_all_anime(watch_status="watching")] == [a]
    assert len(db.get_all_anime(watch_status="watching", media_type=None)) == 2
    assert [x["romaji_title"] for x in db.get_all_anime(media_type="tv")] == ["A Show"]


def test_tmdb_ids_unique_per_media_type(db):
    db.add_anime({"romaji_title": "S", "media_type": "tv", "tmdb_id": 5})
    db.add_anime({"romaji_title": "M", "media_type": "movie", "tmdb_id": 5})   # same id, other type: fine
    with pytest.raises(sqlite3.IntegrityError):
        db._get_conn().execute("INSERT INTO anime (romaji_title, media_type, tmdb_id) VALUES ('S2','tv',5)")


def test_upgrade_from_v4_keeps_data_and_backs_up(tmp_path):
    from core.database import DatabaseManager
    p = tmp_path / "lib" / "anime.db"
    p.parent.mkdir()
    d = DatabaseManager(p)
    aid = add_anime(d, "Old favourite", "completed", anilist_id=42)
    d.set_episode_watched(aid, 1, True)
    c = d._get_conn()
    # make it look like a v2.8 (schema 4) library
    c.executescript("""
        DROP TABLE tv_episodes; DROP TABLE tv_seasons;
        DROP INDEX IF EXISTS idx_anime_tmdb; DROP INDEX IF EXISTS idx_anime_media;
        UPDATE anime SET media_type=NULL; UPDATE schema_version SET version=4;
    """)
    c.commit()
    d.close()

    d2 = DatabaseManager(p)
    c2 = d2._get_conn()
    assert c2.execute("SELECT version FROM schema_version").fetchone()[0] == 5
    row = d2.get_anime_by_id(aid)
    assert row["romaji_title"] == "Old favourite" and row["media_type"] == "anime"
    assert d2.get_watched_count(aid) == 1
    tables = {r[0] for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tv_seasons", "tv_episodes"} <= tables
    backups = list((p.parent / "backups").glob("anime_pre_v5_*.db"))
    assert len(backups) == 1
    d2.close()
    DatabaseManager(p).close()                                     # reopening: no new backup
    assert len(list((p.parent / "backups").glob("anime_pre_v5_*.db"))) == 1


def test_fresh_install_takes_no_backup(tmp_path):
    from core.database import DatabaseManager
    DatabaseManager(tmp_path / "new.db").close()
    assert not (tmp_path / "backups").exists()
