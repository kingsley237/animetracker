"""Music: likes, rankings, downloads, the Music page."""
from tests.conftest import pump, wait_until


def _song(i, kind="opening", source="Bleach"):
    return {"id": f"vid{i}", "site": "youtube", "kind": kind, "title": f"Song {i}  ·  VIZ",
            "thumb": "", "source": source, "media": "anime", "lib_id": None}


def test_likes_and_rankings(db):
    from core.music_library import MusicLibrary, list_for
    lib = MusicLibrary(db)
    assert lib.toggle_like(_song(1)) and lib.is_liked("vid1")
    lib.like(_song(2, "ending"))
    lib.like(_song(3, "intro", "Arcane"))
    assert {s["id"] for s in lib.liked("op")} == {"vid1", "vid3"}
    assert [s["id"] for s in lib.liked("ending")] == ["vid2"]
    s1 = next(s for s in lib.liked() if s["id"] == "vid1")
    assert s1["song"] == "Song 1" and s1["channel"] == "VIZ"          # display suffix split off
    assert not lib.toggle_like(_song(1)) and not lib.is_liked("vid1")
    assert list_for("intro") == "op" and list_for("soundtrack") == "ost"
    for i in range(4):
        lib.insert_at(_song(10 + i), "op", i + 1)
    lib.insert_at(_song(99), "op", 2)
    assert [s["id"] for s in lib.ranked("op")] == ["vid10", "vid99", "vid11", "vid12", "vid13"]
    lib.move("vid13", "op", 1)
    assert lib.ranked("op")[0]["id"] == "vid13" and lib.rank_of("vid10", "op") == 2
    lib.unrank("vid99", "op")
    assert [s["rank"] for s in lib.ranked("op")] == [1, 2, 3, 4]


def test_download_names_and_record(db, tmp_path, monkeypatch):
    import sys
    import types
    from core import downloader
    from core.music_library import MusicLibrary
    assert downloader.file_stem({"title": "OPENING 1 | BLEACH | Asterisk  ·  VIZ", "source": "Bleach"}) == \
        "OPENING 1 BLEACH Asterisk"
    assert downloader.file_stem({"title": "Asterisk", "source": "Bleach"}) == "Bleach - Asterisk"
    calls = {}

    class FakeYDL:
        def __init__(self, opts):
            calls["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            calls["url"] = url
            out = calls["opts"]["outtmpl"].replace("%(ext)s", "mp3")
            open(out, "wb").write(b"x")
            for h in calls["opts"]["progress_hooks"]:
                h({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
                h({"status": "finished"})
            return {}
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    seen = []
    (tmp_path / "Bleach - Asterisk.mp3").write_bytes(b"old")            # never overwritten
    path = downloader.download({"id": "abc", "title": "Asterisk", "source": "Bleach"}, "audio",
                               lambda f, t: seen.append(f), folder=tmp_path)
    assert path.endswith("Bleach - Asterisk (2).mp3") and calls["url"].endswith("v=abc")
    assert calls["opts"]["postprocessors"][0]["preferredcodec"] == "mp3"
    assert seen[-1] == 1.0
    lib = MusicLibrary(db)
    lib.record_download({"id": "abc", "title": "Asterisk", "source": "Bleach", "kind": "opening"}, "audio", path)
    assert lib.downloads()[0]["path"] == path


def test_hub_like_button_and_download(qapp, db, monkeypatch):
    from core import downloader
    from ui.music_actions import LikeButton, MusicHub
    hub = MusicHub.get()
    hub.db = db
    b = LikeButton()
    b.set_item(_song(5))
    assert not b.isChecked()
    b.click()
    assert hub.is_liked("vid5") and b.isChecked() and "Liked" in b.text()
    other = LikeButton(compact=True)
    other.set_item(_song(5))
    hub.toggle_like(_song(5))                           # liked elsewhere -> both follow
    assert not b.isChecked() and not other.isChecked()
    monkeypatch.setattr(downloader, "download", lambda item, mode, progress=None, folder=None:
                        (progress and progress(0.5, "x")) or "C:/x/Song 5.mp3")
    done = []
    hub.finished.connect(lambda v, m, p: done.append(p))
    hub.download(_song(5), "audio")
    assert wait_until(lambda: done == ["C:/x/Song 5.mp3"])
    from core.music_library import MusicLibrary
    assert MusicLibrary(db).downloads()[0]["mode"] == "audio" and not hub.active
    b.deleteLater()
    other.deleteLater()
    pump(20)


def test_song_rank_dialog_places_by_questions(qapp, db):
    from core.music_library import MusicLibrary
    from ui.music_actions import MusicHub
    from ui.music_rank import SongRankDialog
    MusicHub.get().db = db
    lib = MusicLibrary(db)
    for i in range(6):
        lib.insert_at(_song(20 + i), "ed", i + 1)
    d = SongRankDialog(_song(50, "ending"), "ed")
    while d.pages.currentIndex() == 0:
        q = d.session.question()
        d._answer("new" if d.session.ordered.index(q) >= 2 else "existing")   # truly belongs at #3
    assert d.position == 3 and lib.rank_of("vid50", "ed") == 3
    d._undo()                                             # take it back from the result screen
    assert lib.rank_of("vid50", "ed") == 0
    d.close()


def test_music_page_tabs(qapp, db):
    from core.music_library import MusicLibrary
    from ui.music_actions import MusicHub
    from ui.music_page import MusicPage, _Row
    MusicHub.get().db = db
    lib = MusicLibrary(db)
    page = MusicPage(db)
    page.resize(1200, 900)
    page.show()
    page.load()
    assert not page.findChildren(_Row)                    # empty state
    lib.like(_song(1))
    lib.like(_song(2, "soundtrack"))
    lib.insert_at(_song(1), "op", 1)
    MusicHub.get().likes_changed.emit()
    pump(50)
    assert len(page.findChildren(_Row)) == 2
    page.filter = "soundtrack"
    page.load()
    pump(20)
    assert [r.item["id"] for r in page.findChildren(_Row) if r.isVisible()] == ["vid2"]
    page.set_tab("ranks")
    pump(20)
    assert any(r.item["id"] == "vid1" for r in page.findChildren(_Row))
    page.set_tab("downloads")
    pump(20)
    page.close()
    page.deleteLater()
    pump(20)


def test_gallery_song_bar(qapp, db):
    from ui.music_actions import MusicHub
    from ui.video_gallery import VideoGallery
    MusicHub.get().db = db
    g = VideoGallery()
    g.load([{"id": "t", "site": "youtube", "kind": "promo", "title": "Trailer", "thumb": ""}], "X")
    assert g.song_bar.isHidden()                          # trailers: no song actions
    g._render([_song(1), _song(2)], "X")
    assert not g.song_bar.isHidden() and g.like_btn.item["id"] == "vid1"
    g._choose(1)
    assert g.like_btn.item["id"] == "vid2"
    g.deleteLater()
    pump(20)
