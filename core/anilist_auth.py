"""

Miroku — AniList OAuth2 Authentication + Score Sync

"""

import json

import secrets

import threading

import time

import webbrowser

from http.server import BaseHTTPRequestHandler, HTTPServer

from typing import Optional, Tuple

from urllib.parse import parse_qs, urlencode, urlparse



import requests



from PyQt6.QtCore import QObject, pyqtSignal



# Register this exact redirect URI in your AniList developer app:

#   http://localhost:7731/callback

REDIRECT_URI    = "http://localhost:7731/callback"

CALLBACK_PORT   = 7731

AUTH_URL        = "https://anilist.co/api/v2/oauth/authorize"

TOKEN_URL       = "https://anilist.co/api/v2/oauth/token"

GRAPHQL_URL     = "https://graphql.anilist.co"

LOGIN_TIMEOUT_S = 120



SCORE_MAP = {

    1: 10,

    2: 25,

    3: 45,

    4: 65,

    5: 82,

    6: 100,

}



_auth_instance: Optional["AniListAuth"] = None





def get_client_credentials() -> Tuple[str, str]:

    """Return (client_id, client_secret) from settings or environment."""

    import os

    from core.app_settings import app_settings



    settings = app_settings()

    client_id = (

        str(settings.value("anilist_client_id", "") or "").strip()

        or os.environ.get("ANILIST_CLIENT_ID", "").strip()

    )

    client_secret = (

        str(settings.value("anilist_client_secret", "") or "").strip()

        or os.environ.get("ANILIST_CLIENT_SECRET", "").strip()

    )

    return client_id, client_secret





def save_client_credentials(client_id: str, client_secret: str) -> None:

    from core.app_settings import app_settings



    settings = app_settings()

    settings.setValue("anilist_client_id", (client_id or "").strip())

    settings.setValue("anilist_client_secret", (client_secret or "").strip())





def credentials_configured() -> bool:

    client_id, client_secret = get_client_credentials()

    return bool(client_id and client_secret)





def get_anilist_auth(parent=None) -> "AniListAuth":

    """Shared auth helper so login state is consistent across the app."""

    global _auth_instance

    if _auth_instance is None:

        _auth_instance = AniListAuth(parent)

    elif parent is not None and _auth_instance.parent() is None:

        _auth_instance.setParent(parent)

    return _auth_instance





class _ReuseHTTPServer(HTTPServer):

    allow_reuse_address = True





class AniListAuth(QObject):

    """Handles OAuth login and score submission to AniList."""



    login_success = pyqtSignal(str)

    login_failed  = pyqtSignal(str)

    login_status  = pyqtSignal(str)

    session_changed = pyqtSignal()

    score_synced  = pyqtSignal(int)

    score_failed  = pyqtSignal(str)



    def __init__(self, parent=None):

        super().__init__(parent)

        from core.app_settings import app_settings

        self._settings = app_settings()

        self._reload_session()

        self._login_thread: Optional[threading.Thread] = None

        self._login_cancel = threading.Event()

        self._active_server: Optional[HTTPServer] = None

        self._expected_state: Optional[str] = None



    def _reload_session(self) -> None:

        self._token: Optional[str] = self._settings.value("anilist_token", None)

        self._username: Optional[str] = self._settings.value("anilist_username", None)

        self._avatar_url: Optional[str] = self._settings.value("anilist_avatar_url", None)



    def is_logged_in(self) -> bool:

        self._reload_session()

        return bool(self._token)



    def get_username(self) -> Optional[str]:

        self._reload_session()

        return self._username



    def get_avatar_url(self) -> Optional[str]:

        self._reload_session()

        return self._avatar_url or None



    def get_profile_url(self) -> Optional[str]:

        username = self.get_username()

        if not username:

            return None

        from urllib.parse import quote

        return f"https://anilist.co/user/{quote(username)}/"



    def is_login_in_progress(self) -> bool:

        return bool(self._login_thread and self._login_thread.is_alive())



    def logout(self):

        self.cancel_login()

        self._token = None

        self._username = None

        self._avatar_url = None

        self._settings.remove("anilist_token")

        self._settings.remove("anilist_username")

        self._settings.remove("anilist_avatar_url")

        self.session_changed.emit()



    def cancel_login(self):

        self._login_cancel.set()

        srv = self._active_server

        if srv is not None:

            def _shutdown():

                try:

                    srv.shutdown()

                except Exception:

                    pass

            threading.Thread(target=_shutdown, daemon=True).start()



    def _status(self, message: str) -> None:

        self.login_status.emit(message)



    def _fail(self, message: str) -> None:

        self.login_failed.emit(message)



    def _succeed(self, username: str) -> None:

        self.login_success.emit(username)

        self.session_changed.emit()



    def start_login(self):

        client_id, client_secret = get_client_credentials()

        if not client_id or not client_secret:

            self._fail(

                "AniList API credentials are not set. "

                "Enter your Client ID and Secret in Settings first."

            )

            return



        if self.is_login_in_progress():

            self._fail("AniList login is already in progress.")

            return



        self._login_cancel.clear()

        self._expected_state = secrets.token_urlsafe(16)

        self._status("Starting a fresh AniList login…")

        self._login_thread = threading.Thread(

            target=self._run_login_flow,

            args=(client_id, client_secret),

            daemon=True,

        )

        self._login_thread.start()



    def _run_login_flow(self, client_id: str, client_secret: str):

        received_code = [None]

        received_error = [None]

        received_state = [None]

        expected_state = self._expected_state



        class Handler(BaseHTTPRequestHandler):

            def do_GET(self):

                parsed = urlparse(self.path)

                params = parse_qs(parsed.query)



                if "state" in params:

                    received_state[0] = params["state"][0]



                if "code" in params:

                    received_code[0] = params["code"][0]

                    body = (

                        b"<html><body style='font-family:Segoe UI,sans-serif;"

                        b"background:#0f1118;color:#e8e8f0;text-align:center;"

                        b"padding:48px'><h2>Miroku</h2><p>Login successful. "

                        b"You can close this tab and return to the app.</p></body></html>"

                    )

                elif "error" in params:

                    err = params.get("error_description") or params.get("error") or ["unknown"]

                    received_error[0] = err[0] if isinstance(err, list) else str(err)

                    body = (

                        b"<html><body style='font-family:Segoe UI,sans-serif;"

                        b"background:#0f1118;color:#f87171;text-align:center;"

                        b"padding:48px'><h2>Login failed</h2><p>You can close this tab.</p></body></html>"

                    )

                else:

                    body = (

                        b"<html><body style='font-family:Segoe UI,sans-serif;"

                        b"background:#0f1118;color:#9da5c0;text-align:center;"

                        b"padding:48px'><h2>Waiting for AniList...</h2><p>"

                        b"Complete login in AniList, then return here.</p></body></html>"

                    )



                self.send_response(200)

                self.send_header("Content-Type", "text/html; charset=utf-8")

                self.end_headers()

                self.wfile.write(body)



            def log_message(self, format, *args):

                pass



        server = None

        try:

            server = _ReuseHTTPServer(("0.0.0.0", CALLBACK_PORT), Handler)

            server.timeout = 0.5

            self._active_server = server

        except OSError as exc:

            self._fail(

                f"Could not start login callback on port {CALLBACK_PORT}: {exc}. "

                "Close any other app using that port and try again."

            )

            return



        auth_params = {

            "client_id": client_id,

            "redirect_uri": REDIRECT_URI,

            "response_type": "code",

            "state": expected_state or "",

        }

        auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"



        self._status("Opening AniList in your browser…")

        webbrowser.open(auth_url)

        self._status("Waiting for you to approve access in AniList…")



        deadline = time.time() + LOGIN_TIMEOUT_S

        try:

            while time.time() < deadline:

                if self._login_cancel.is_set():

                    self._fail("Login cancelled.")

                    return

                if received_code[0]:

                    if expected_state and received_state[0] != expected_state:

                        self._fail(

                            "Login response did not match this session. "

                            "Click Connect AniList to try again."

                        )

                        return

                    self._status("Approval received. Finishing connection…")

                    break

                if received_error[0]:

                    self._fail(f"AniList denied access: {received_error[0]}")

                    return

                try:

                    server.handle_request()

                except Exception:

                    break

        finally:

            self._active_server = None

            try:

                server.server_close()

            except Exception:

                pass



        if self._login_cancel.is_set():

            self._fail("Login cancelled.")

        elif received_error[0]:

            self._fail(f"AniList denied access: {received_error[0]}")

        elif received_code[0]:

            self._exchange_code(received_code[0], client_id, client_secret)

        else:

            self._fail(

                "Login timed out after 2 minutes. "

                "If you closed the browser, click Connect AniList to try again."

            )



    def _parse_token_error(self, resp: requests.Response) -> str:

        detail = resp.text[:400] if resp.text else resp.reason

        try:

            payload = resp.json()

            if isinstance(payload, dict):

                err = payload.get("error", "")

                msg = payload.get("message") or payload.get("error_description") or detail

                if err == "invalid_client":

                    return (

                        "AniList rejected the Client ID or Secret. "

                        "Create a new app at anilist.co/settings/developer, set the "

                        f"redirect URI to {REDIRECT_URI}, then save the new "

                        "credentials in Settings."

                    )

                return f"{msg} ({err})" if err else str(msg)

        except (json.JSONDecodeError, ValueError):

            pass

        return detail



    def _exchange_code(self, code: str, client_id: str, client_secret: str):

        self._status("Exchanging authorization code for access token…")

        payload = {

            "grant_type": "authorization_code",

            "client_id": client_id,

            "client_secret": client_secret,

            "redirect_uri": REDIRECT_URI,

            "code": code,

        }

        headers = {

            "Content-Type": "application/json",

            "Accept": "application/json",

        }

        try:

            resp = requests.post(TOKEN_URL, json=payload, headers=headers, timeout=15)

            if not resp.ok:

                self._fail(

                    f"Token exchange failed ({resp.status_code}): "

                    f"{self._parse_token_error(resp)}"

                )

                return



            data = resp.json()

            token = data.get("access_token")

            if not token:

                self._fail("No access token in AniList response.")

                return



            self._token = token

            self._settings.setValue("anilist_token", token)

            profile = self._fetch_viewer_profile(token)

            username = profile.get("name")

            avatar_url = profile.get("avatar_url")

            self._username = username

            self._avatar_url = avatar_url

            self._settings.setValue("anilist_username", username or "")

            self._settings.setValue("anilist_avatar_url", avatar_url or "")

            self._succeed(username or "AniList User")

        except Exception as exc:

            self._fail(f"Could not finish login: {exc}")



    def _fetch_viewer_profile(self, token: str) -> dict:

        try:

            resp = requests.post(

                GRAPHQL_URL,

                json={"query": "query { Viewer { name avatar { large medium } } }"},

                headers={

                    "Authorization": f"Bearer {token}",

                    "Content-Type": "application/json",

                },

                timeout=10,

            )

            resp.raise_for_status()

            viewer = resp.json().get("data", {}).get("Viewer") or {}

            avatar = viewer.get("avatar") or {}

            return {

                "name": viewer.get("name"),

                "avatar_url": avatar.get("large") or avatar.get("medium"),

            }

        except Exception:

            return {}



    def submit_score(self, anilist_id: int, our_score: int):

        self._reload_session()

        if not self._token:

            self.score_failed.emit("Not logged in to AniList.")

            return

        if anilist_id <= 0:

            self.score_failed.emit("No AniList ID for this anime.")

            return



        anilist_score = SCORE_MAP.get(our_score, our_score * 16)

        mutation = """

        mutation ($mediaId: Int, $score: Float) {

            SaveMediaListEntry (mediaId: $mediaId, score: $score) {

                id score

            }

        }

        """



        def _submit():

            try:

                resp = requests.post(

                    GRAPHQL_URL,

                    json={

                        "query": mutation,

                        "variables": {"mediaId": anilist_id, "score": float(anilist_score)},

                    },

                    headers={

                        "Authorization": f"Bearer {self._token}",

                        "Content-Type": "application/json",

                    },

                    timeout=15,

                )

                resp.raise_for_status()

                data = resp.json()

                if "errors" in data:

                    self.score_failed.emit(str(data["errors"]))

                else:

                    self.score_synced.emit(anilist_id)

            except Exception as exc:

                self.score_failed.emit(str(exc))



        threading.Thread(target=_submit, daemon=True).start()


