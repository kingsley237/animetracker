"""
Miroku — AniList OAuth2 Authentication + Score Sync
Allows users to log in with their AniList account and submit
their ratings back to AniList transparently.

How AniList scoring works:
- AniList uses a 100-point scale internally
- Community score = average of all authenticated user scores
- We map our 1–6 scale → AniList 1–100 scale
- Users must explicitly opt-in and understand their score
  contributes to the community average

OAuth flow:
1. Open AniList auth URL in browser
2. User logs in and approves
3. AniList redirects to a localhost callback URL with a code
4. We exchange code for access token
5. Store token in QSettings (encrypted on OS keychain ideally)
"""
import webbrowser
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QSettings

# ── AniList OAuth app credentials ─────────────────────────────────────────────
# To use this feature:
# 1. Go to https://anilist.co/settings/developer
# 2. Create a new API client
# 3. Set redirect URI to: http://localhost:7731/callback
# 4. Paste your client ID and secret below
ANILIST_CLIENT_ID     = "16708"   # ← paste your AniList client ID here
ANILIST_CLIENT_SECRET = "gsdICws7RTugTnODKq0AUlEr1p1vqr96brAxgTAi"   # ← paste your AniList client secret here
REDIRECT_URI          = "http://localhost:7731/callback"
AUTH_URL              = "https://anilist.co/api/v2/oauth/authorize"
TOKEN_URL             = "https://anilist.co/api/v2/oauth/token"
GRAPHQL_URL           = "https://graphql.anilist.co"

# Rating scale mapping: our 1–6 → AniList 1–100
SCORE_MAP = {
    1: 10,   # Terrible  → 10
    2: 25,   # Bad       → 25
    3: 45,   # Fair      → 45
    4: 65,   # Good      → 65
    5: 82,   # Great     → 82
    6: 100,  # Masterpiece → 100
}


class AniListAuth(QObject):
    """Handles OAuth login and score submission to AniList."""

    login_success  = pyqtSignal(str)   # username
    login_failed   = pyqtSignal(str)   # error message
    score_synced   = pyqtSignal(int)   # anilist_id synced
    score_failed   = pyqtSignal(str)   # error

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.app_settings import app_settings
        self._settings = app_settings()
        self._token: Optional[str] = self._settings.value("anilist_token", None)
        self._username: Optional[str] = self._settings.value("anilist_username", None)

    # ── Token state ────────────────────────────────────────────────────────────

    def is_logged_in(self) -> bool:
        return bool(self._token)

    def get_username(self) -> Optional[str]:
        return self._username

    def logout(self):
        self._token = None
        self._username = None
        self._settings.remove("anilist_token")
        self._settings.remove("anilist_username")

    # ── OAuth login ────────────────────────────────────────────────────────────

    def start_login(self):
        """
        Open the AniList OAuth page in the browser.
        Start a local HTTP server to catch the callback.
        """
        if not ANILIST_CLIENT_ID:
            self.login_failed.emit(
                "AniList client ID not configured.\n"
                "See core/anilist_auth.py to set up your API credentials."
            )
            return

        auth_url = (
            f"{AUTH_URL}?client_id={ANILIST_CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
        )
        webbrowser.open(auth_url)

        # Start local callback server in background thread
        t = threading.Thread(target=self._wait_for_callback, daemon=True)
        t.start()

    def _wait_for_callback(self):
        """Listen on localhost:7731 for the OAuth callback."""
        received_code = [None]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                if "code" in params:
                    received_code[0] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h2>Miroku: Login successful! You can close this tab.</h2>"
                )

            def log_message(self, format, *args):
                pass   # suppress server logs

        try:
            server = HTTPServer(("localhost", 7731), Handler)
            server.timeout = 120   # wait up to 2 minutes
            server.handle_request()
        except Exception as e:
            self.login_failed.emit(f"Callback server error: {e}")
            return

        if received_code[0]:
            self._exchange_code(received_code[0])
        else:
            self.login_failed.emit("No authorization code received.")

    def _exchange_code(self, code: str):
        """Exchange auth code for access token."""
        try:
            resp = requests.post(TOKEN_URL, json={
                "grant_type":    "authorization_code",
                "client_id":     ANILIST_CLIENT_ID,
                "client_secret": ANILIST_CLIENT_SECRET,
                "redirect_uri":  REDIRECT_URI,
                "code":          code,
            }, timeout=15)
            resp.raise_for_status()
            data  = resp.json()
            token = data.get("access_token")
            if not token:
                self.login_failed.emit("No access token in response.")
                return
            self._token = token
            self._settings.setValue("anilist_token", token)
            # Fetch username
            username = self._fetch_username(token)
            self._username = username
            self._settings.setValue("anilist_username", username)
            self.login_success.emit(username or "AniList User")
        except Exception as e:
            self.login_failed.emit(str(e))

    def _fetch_username(self, token: str) -> Optional[str]:
        try:
            resp = requests.post(GRAPHQL_URL, json={
                "query": "query { Viewer { name } }"
            }, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }, timeout=10)
            data = resp.json()
            return data.get("data", {}).get("Viewer", {}).get("name")
        except Exception:
            return None

    # ── Score submission ────────────────────────────────────────────────────────

    def submit_score(self, anilist_id: int, our_score: int):
        """
        Submit a rating to AniList.
        our_score: 1–6 (our scale)
        Mapped to AniList's 100-point scale.

        Transparency: users are shown exactly what score is being submitted
        before it happens (handled in the UI calling this method).
        """
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
                resp = requests.post(GRAPHQL_URL, json={
                    "query":     mutation,
                    "variables": {"mediaId": anilist_id, "score": float(anilist_score)},
                }, headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type":  "application/json",
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if "errors" in data:
                    self.score_failed.emit(str(data["errors"]))
                else:
                    self.score_synced.emit(anilist_id)
            except Exception as e:
                self.score_failed.emit(str(e))

        import threading
        threading.Thread(target=_submit, daemon=True).start()