"""Database: schema, completion dates, archive, notifications, rewatches, dropped."""
import time

from tests.conftest import DAY, add_anime, watch


def columns(db, table):
    return {r[1] for r in db._get_conn().execute(f"PRAGMA table_info({table})").fetchall()}


def test_fresh_database_has_current_schema(db):
    cols = columns(db, "anime")
    for c in ("completed_at", "archived", "archived_at", "format", "characters",
              "start_exact", "mal_id", "videos", "sequel_info", "meta_synced_at"):
        assert c in cols, c
    tables = {r[0] for r in db._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"anime", "episodes", "ratings", "dropped_anime", "notifications", "rewatches"} <= tables


def test_reopening_database_is_idempotent(tmp_path):
    from core.database import DatabaseManager
    p = tmp_path / "x.db"
    a = DatabaseManager(p); aid = add_anime(a, "Keep me", "completed"); a.close()
    b = DatabaseManager(p)
    assert b.get_anime_by_id(aid)["romaji_title"] == "Keep me"
    b.close()


def test_completed_at_set_on_completion_and_archive_cleared_on_leave(db):
    aid = add_anime(db, ws="watching")
    assert db.get_anime_by_id(aid)["completed_at"] is None
    db.update_anime(aid, {"watch_status": "completed"})
    first = db.get_anime_by_id(aid)["completed_at"]
    assert first
    db.set_archived([aid], True)
    assert db.get_anime_by_id(aid)["archived"] == 1
    db.update_anime(aid, {"watch_status": "watching"})
    assert db.get_anime_by_id(aid)["archived"] == 0


def test_adding_as_completed_records_date(db):
    aid = add_anime(db, ws="completed")
    assert db.get_anime_by_id(aid)["completed_at"]


def test_archive_filters_and_counts(db):
    a = add_anime(db, "A", "completed")
    b = add_anime(db, "B", "completed")
    add_anime(db, "W", "watching")
    assert db.set_archived([a], True) == 1
    assert db.count_archived() == 1
    visible = {x["id"] for x in db.get_all_anime(watch_status="completed", archived=False)}
    archived = {x["id"] for x in db.get_all_anime(watch_status="completed", archived=True)}
    assert visible == {b} and archived == {a}
    # default (None) still returns everything - scans rely on this
    assert {a, b} <= {x["id"] for x in db.get_all_anime(watch_status="completed")}


def test_archive_only_applies_to_completed(db):
    w = add_anime(db, "W", "watching")
    assert db.set_archived([w], True) == 0


def test_auto_archive_by_age(db):
    old = add_anime(db, "Old", "completed")
    new = add_anime(db, "New", "completed")
    db._get_conn().execute("UPDATE anime SET completed_at=? WHERE id=?",
                           (int(time.time()) - 200 * DAY, old))
    db._get_conn().commit()
    assert db.auto_archive_completed(0) == 0          # "Never"
    assert db.auto_archive_completed(182) == 1
    assert db.get_anime_by_id(old)["archived"] == 1
    assert db.get_anime_by_id(new)["archived"] == 0


def test_notifications_dedupe_dismiss_and_filters(db):
    n = {"fingerprint": "fp-1", "kind": "new_season", "title": "t", "message": "m"}
    nid = db.upsert_notification(n)
    assert db.upsert_notification(n) == nid          # same fingerprint -> same row
    db.upsert_notification({"fingerprint": "fp-2", "kind": "episode_aired", "title": "t", "message": "m"})
    kinds = lambda rows: {r["kind"] for r in rows}
    assert kinds(db.get_due_notifications(limit=10, kinds=["new_season"])) == {"new_season"}
    assert kinds(db.get_due_notifications(limit=10, exclude_kinds=["new_season"])) == {"episode_aired"}
    db.dismiss_notification(nid)
    assert db.upsert_notification(n) is None         # dismissed stays dismissed
    assert not db.get_active_notifications("new_season")


def test_remind_later_hides_until_due(db):
    nid = db.upsert_notification({"fingerprint": "x", "kind": "k", "title": "t", "message": "m"})
    db.remind_notification_later(nid, hours=24)
    assert not db.get_due_notifications(limit=10)
    assert db.get_active_notifications("k")          # still active for persistent surfaces


def test_rewatch_lifecycle(db):
    aid = add_anime(db, ws="completed", total_episodes=12)
    r1 = db.start_rewatch(aid)
    assert db.start_rewatch(aid) == r1               # only one active at a time
    db.set_rewatch_progress(r1, 5)
    assert db.get_active_rewatch(aid)["progress"] == 5
    assert db.get_active_rewatch_ids() == [aid]
    db.finish_rewatch(r1, 12)
    assert db.rewatch_count(aid) == 1 and db.get_active_rewatch(aid) is None
    r2 = db.start_rewatch(aid)
    assert db.get_active_rewatch(aid)["number"] == 2
    db.abandon_rewatch(r2)
    assert db.rewatch_count(aid) == 1 and len(db.get_rewatches(aid)) == 1
    # original history untouched by rewatching
    assert db.get_watched_count(aid) == 0


def test_drop_restore_and_reason(db):
    aid = add_anime(db, "Dropme", "watching", anilist_id=999)
    watch(db, aid, 4)
    db.delete_anime(aid, drop=True, reason="too slow")
    rows = db.get_dropped_anime()
    assert len(rows) == 1 and rows[0]["last_episode"] == 4 and rows[0]["drop_reason"] == "too slow"
    db.update_drop_reason(rows[0]["id"], "  changed  ")
    assert db.get_dropped_anime()[0]["drop_reason"] == "changed"
    new_id = db.restore_dropped(rows[0]["id"])
    assert new_id and not db.get_dropped_anime()
    assert db.get_anime_by_id(new_id)["anilist_id"] == 999
