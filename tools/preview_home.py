"""
Preview Raikō on a COPY of your library - your real library and settings
are never touched.

    .venv\Scripts\python.exe tools\preview_home.py            your library as it is today
    .venv\Scripts\python.exe tools\preview_home.py --fresh    pretend new episodes just came out
    .venv\Scripts\python.exe tools\preview_home.py --tour     also show the welcome + tour

--fresh un-ticks the latest watched episode of up to three anime / TV shows
you're watching (in the copy only), so you can see Home on a day an episode
lands: NEW EPISODE spotlight slides, the Continue watching rail with ✓.
"""
import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="simulate freshly aired episodes")
    ap.add_argument("--tour", action="store_true", help="show the welcome + tour")
    args = ap.parse_args()

    real = Path.home() / ".animetracker" / "anime.db"
    tmp = Path(tempfile.mkdtemp(prefix="raiko_preview_"))
    copy = tmp / "anime.db"
    src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)     # read-only
    dst = sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    dst.close()

    # settings go to a throwaway file too
    from PyQt6.QtCore import QSettings
    import core.app_settings as cs
    ini = str(tmp / "settings.ini")
    real_settings = QSettings("Miroku", "Miroku")
    s = QSettings(ini, QSettings.Format.IniFormat)
    for k in real_settings.allKeys():
        s.setValue(k, real_settings.value(k))
    s.setValue("start_page", "home")
    s.setValue("onboarding_v3_seen", not args.tour)
    s.sync()
    cs.app_settings = lambda: QSettings(ini, QSettings.Format.IniFormat)

    from core.database import DatabaseManager
    db = DatabaseManager(copy)
    if args.fresh:
        conn = db._get_conn()
        n = 0
        for r in db.get_all_anime(watch_status="watching", sort_by="recent"):
            last = conn.execute("SELECT MAX(episode_num) FROM episodes WHERE anime_id=? AND watched=1",
                                (r["id"],)).fetchone()[0]
            if last and n < 2:
                conn.execute("UPDATE episodes SET watched=0 WHERE anime_id=? AND episode_num=?", (r["id"], last))
                n += 1
        for r in db.get_all_anime(watch_status="watching", media_type="tv"):
            e = conn.execute("SELECT season_number, episode_number FROM tv_episodes WHERE anime_id=? AND watched=1 "
                             "ORDER BY season_number DESC, episode_number DESC LIMIT 1", (r["id"],)).fetchone()
            if e:
                conn.execute("UPDATE tv_episodes SET watched=0 WHERE anime_id=? AND season_number=? AND episode_number=?",
                             (r["id"], e[0], e[1]))
                break
        conn.commit()

    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except ImportError:
        pass
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationDisplayName("Raikō — preview (a copy of your library)")
    app.setFont(QFont("Segoe UI", 10))
    from ui.main_window import MainWindow
    win = MainWindow(db)
    win.setWindowTitle("Raikō — PREVIEW on a copy of your library")
    win.showMaximized()
    print(f"Preview running on a copy in {tmp}  (your real library is untouched)")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
