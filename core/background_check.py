"""
Raikō - notifications while the app is closed.

Windows starts `Raiko.exe --check` on a schedule (an opt-in Windows scheduled
task: every few hours, at log-in, and once after a missed run when the PC
wakes). The check runs the same refreshes the app does, then shows a native
Windows notification for each NEW event and exits - nothing keeps running
in between (no tray icon, no background process).

    episode aired · new TV episodes · out in HD / HD date · in cinemas ·
    new season / premiere date · new trailer · a Plan to Watch show started

Each event notifies once. When the feature is switched on, everything
already known is marked as seen, so you never get a flood.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from xml.sax.saxutils import escape

AUMID = "Raiko.App"
PROTOCOL = "raiko"
TASK = "Raiko - new episodes check"     # top level + ASCII: no admin rights needed

# alerts worth a Windows notification (others stay in-app)
OS_KINDS = ["episode_aired", "tv_new_episodes", "movie_digital", "movie_digital_date",
            "movie_theaters", "new_season", "tv_new_season", "tv_premiere_date",
            "upcoming_trailer", "planned_started"]


def _settings():
    from core.app_settings import app_settings
    return app_settings()


def enabled() -> bool:
    return bool(_settings().value("os_notify_enabled", False, type=bool))


def interval_hours() -> int:
    try:
        return int(_settings().value("os_notify_hours", 3))
    except (TypeError, ValueError):
        return 3


# ── what has already been shown ───────────────────────────────────────────────

def _seen() -> Dict[str, float]:
    try:
        return json.loads(_settings().value("os_notified", "{}") or "{}")
    except (TypeError, ValueError):
        return {}


def _save_seen(seen: Dict[str, float]):
    cutoff = time.time() - 120 * 86400
    _settings().setValue("os_notified", json.dumps({k: v for k, v in seen.items() if v > cutoff}))


def mark_all_seen(db):
    """Baseline: everything active right now counts as already notified."""
    seen = _seen()
    for kind in OS_KINDS:
        for n in db.get_active_notifications(kind):
            seen[n["fingerprint"]] = time.time()
    _save_seen(seen)


def pending(db) -> List[Dict]:
    seen = _seen()
    out = []
    for kind in OS_KINDS:
        for n in db.get_active_notifications(kind):
            if n.get("fingerprint") not in seen:
                out.append(n)
    out.sort(key=lambda n: n.get("first_seen") or 0)
    return out


# ── the check itself ──────────────────────────────────────────────────────────

def apply_airing(db, results: Dict[int, Optional[Dict]]):
    """Store fresh airing data (same as the app's Refresh Airing)."""
    for anilist_id, media in (results or {}).items():
        if not media:
            continue
        anime = db.get_anime_by_anilist_id(anilist_id)
        if not anime:
            continue
        nae = media.get("nextAiringEpisode") or {}
        db.update_anime(anime["id"], {
            "status": media.get("status", anime["status"]),
            "total_episodes": media.get("episodes") or anime.get("total_episodes"),
            "average_score": media.get("averageScore"),
            "next_episode_at": nae.get("airingAt"),
            "next_episode_num": nae.get("episode"),
        })


def run_check(db) -> List[Dict]:
    """Refresh everything that can raise an alert. Returns new alerts."""
    from core.api import refresh_airing_data
    from core.kinema_sync import KinemaSync
    from core.metadata_sync import MetadataSync
    from core.notification_service import NotificationService

    steps = []
    ids = [a["anilist_id"] for a in db.get_all_anime(watch_status="watching") if a.get("anilist_id")]
    if ids:
        steps.append(lambda: apply_airing(db, refresh_airing_data(ids)))
    # Plan to Watch only (trailers, dates); promo-video lists are left to the app
    steps += [lambda: MetadataSync(db).sync(statuses=("planned",), videos=False),
              lambda: NotificationService(db).scan(),
              lambda: KinemaSync(db).sync_movies(),
              lambda: KinemaSync(db).sync_tv()]
    st = _settings()
    if time.time() - float(st.value("os_last_sequel_scan", 0) or 0) > 20 * 3600:
        def sequels():
            NotificationService(db).scan_sequels(
                include_dropped=st.value("new_season_include_dropped", True, type=bool))
            st.setValue("os_last_sequel_scan", time.time())
        steps.append(sequels)
    for step in steps:
        try:
            step()
        except Exception:
            pass                      # offline / a service down: try again next time
    return pending(db)


# ── Windows toasts ────────────────────────────────────────────────────────────

def _icon() -> Optional[Path]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    for p in (base / "resources" / "raiko_icon_256.png",
              Path(__file__).resolve().parents[1] / "resources" / "raiko_icon_256.png"):
        if p.exists():
            return p
    return None


def launch_command() -> List[str]:
    """How Windows should start Raikō (installed exe, or from source)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else sys.executable),
            str(Path(__file__).resolve().parents[1] / "main.py")]


def register():
    """Register Raikō as a notification sender (name + icon) and the raiko://
    link that opens a title when a notification is clicked. Per-user only."""
    if sys.platform != "win32":
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{AUMID}") as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "Raikō")
        icon = _icon()
        if icon:
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, str(icon))
    cmd = " ".join(f'"{c}"' for c in launch_command()) + ' "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Raikō")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL}\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def _toast_xml(title: str, body: str, launch: str) -> str:
    return (f'<toast activationType="protocol" launch="{escape(launch)}"><visual><binding template="ToastGeneric">'
            f'<text>{escape(title)}</text><text>{escape(body)}</text></binding></visual></toast>')


def show(items: List[Dict]) -> int:
    """Show Windows notifications (at most 4 single ones + one summary)."""
    if sys.platform != "win32" or not items:
        return 0
    xmls = []
    for n in items[:4]:
        launch = f"{PROTOCOL}://open/{n.get('anime_id') or 0}"
        xmls.append(_toast_xml(n.get("title") or "Raikō", n.get("message") or "", launch))
    if len(items) > 4:
        xmls.append(_toast_xml(f"{len(items) - 4} more updates", "Open Raikō to see everything new.",
                               f"{PROTOCOL}://open/0"))
    ps = ["[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null",
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null",
          f"$n = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{AUMID}')"]
    for x in xmls:
        ps += ["$x = New-Object Windows.Data.Xml.Dom.XmlDocument",
               "$x.LoadXml(@'\n" + x + "\n'@)",
               "$n.Show([Windows.UI.Notifications.ToastNotification]::new($x))"]
    import base64
    encoded = base64.b64encode("\n".join(ps).encode("utf-16-le")).decode("ascii")   # keeps ō, —, accents
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return 0
    return len(xmls)


def notify_new(db) -> int:
    items = pending(db)
    shown = show(items)
    if shown:
        seen = _seen()
        for n in items:
            seen[n["fingerprint"]] = time.time()
        _save_seen(seen)
    return shown


# ── the scheduled task ────────────────────────────────────────────────────────

def _task_xml(hours: int) -> str:
    cmd = launch_command()
    exe, args = cmd[0], " ".join(f'"{c}"' for c in cmd[1:]) + " --check"
    start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 300))
    import os
    dom, name = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    user = escape(dom + "\\" + name if dom else name)      # DOMAIN\user: the task is yours only
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Raikō: checks for new episodes, HD releases and seasons, shows a notification, then exits.</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger><StartBoundary>{start}</StartBoundary><Enabled>true</Enabled>
      <Repetition><Interval>PT{hours}H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>PT2M</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(exe)}</Command><Arguments>{escape(args)}</Arguments></Exec></Actions>
</Task>"""


def _schtasks(*args) -> bool:
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def _create_task(hours: int) -> bool:
    import tempfile
    xml_path = Path(tempfile.gettempdir()) / "raiko_task.xml"
    xml_path.write_text(_task_xml(hours), encoding="utf-16")
    ok = _schtasks("/Create", "/TN", TASK, "/XML", str(xml_path), "/F")
    try:
        xml_path.unlink()
    except OSError:
        pass
    return ok


def enable(db, hours: int = 3) -> bool:
    """Switch closed-app notifications on: register, baseline, schedule."""
    if sys.platform != "win32":
        return False
    register()
    mark_all_seen(db)
    ok = _create_task(hours)
    st = _settings()
    st.setValue("os_notify_enabled", ok)
    st.setValue("os_notify_hours", hours)
    return ok


def refresh_registration():
    """On app start (when on): point the task and the raiko:// link at the Raikō
    that's actually installed/running - e.g. after an update or a move."""
    if sys.platform != "win32" or not enabled():
        return
    try:
        register()
        _create_task(interval_hours())
    except Exception:
        pass


def disable() -> bool:
    _settings().setValue("os_notify_enabled", False)
    return _schtasks("/Delete", "/TN", TASK, "/F")


def task_exists() -> bool:
    return _schtasks("/Query", "/TN", TASK)


def test_toast() -> int:
    register()
    return show([{"title": "Raikō notifications are on",
                  "message": "You'll hear about new episodes and HD releases even when Raikō is closed.",
                  "anime_id": 0}])
