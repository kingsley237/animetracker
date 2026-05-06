# AnimeTracker — Deployment & Update Guide

Everything you need to go from code to a `.exe` your friends can download,
and how to push updates they are notified about automatically.

---

## Part 1 — Build the executable

### Step 1 — Activate your virtual environment

```powershell
cd "D:\Anime Tracker\animetracker"
.venv\Scripts\activate
```

### Step 2 — Install PyInstaller (one time only)

```powershell
pip install pyinstaller
```

### Step 3 — Run the build script

```powershell
python build_exe.py
```

This takes 1–3 minutes. When done you will see:

```
✅  Build complete!
📦  D:\Anime Tracker\animetracker\dist\AnimeTracker.exe
📏  ~85 MB
```

### Step 4 — Test it

Double-click `dist\AnimeTracker.exe`. It should open the app with no terminal window, no Python required. Your data lives at `C:\Users\YOU\.animetracker\` as always — the exe does not touch it.

---

## Part 2 — Publish to GitHub so friends can download it

### Step 1 — Set your GitHub username in the app

Open `core/updater.py` and change line 22:

```python
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"   # ← change this to your actual username
```

Save, rebuild the exe (`python build_exe.py`).

### Step 2 — Push your code to GitHub

```powershell
git add .
git commit -m "feat: v2.0.0 initial release"
git push origin main
```

### Step 3 — Create a GitHub Release

1. Go to your repo on GitHub
2. Click **Releases** (right sidebar) → **Draft a new release**
3. Click **Choose a tag** → type `v2.0.0` → click **Create new tag**
4. Set title: `AnimeTracker v2.0.0`
5. In the description box, write what's in this release (your friends will see this)
6. Click **Attach binaries** → upload `dist\AnimeTracker.exe`
7. Click **Publish release**

Your friends now go to:
```
https://github.com/YOUR_USERNAME/animetracker/releases/latest
```
and download `AnimeTracker.exe`.

---

## Part 3 — Sending updates (every future version)

### Your workflow when you fix something or add a feature

```powershell
# 1. Make your changes in the code

# 2. Bump the version in two places:
#    - core/updater.py  →  APP_VERSION = "2.1.0"
#    - build_exe.py     →  VERSION = "2.1.0"

# 3. Commit and push
git add .
git commit -m "feat: describe what changed"
git push origin main

# 4. Rebuild the exe
python build_exe.py

# 5. Go to GitHub → Releases → Draft new release
#    Tag: v2.1.0
#    Attach: dist\AnimeTracker.exe
#    Publish
```

### What your friends experience

The next time they open AnimeTracker, within a few seconds a purple banner appears at the top:

```
✦  AnimeTracker v2.1.0 is available — you have v2.0.0    [Download Update]  ✕
```

Clicking **Download Update** opens their browser directly to the new `.exe` on GitHub. They download it, replace their old `AnimeTracker.exe`, and they're on the new version. Their data (`~/.animetracker/`) is never touched.

---

## Part 4 — Sharing with friends

Send them this message:

> Hey! I made an anime tracker app. Download it here:
> https://github.com/YOUR_USERNAME/animetracker/releases/latest
>
> Just download AnimeTracker.exe and double-click it. No install needed.
> When I push updates, the app will tell you automatically.

---

## Part 5 — Making the repo look good for friends

Your `README.md` is already community-facing. Two things to add before sharing:

1. **Screenshots** — take a screenshot of the app running, drag it into the README on GitHub
2. **Release badge** — add this to the top of your README:

```markdown
[![Latest Release](https://img.shields.io/github/v/release/YOUR_USERNAME/animetracker)](https://github.com/YOUR_USERNAME/animetracker/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/YOUR_USERNAME/animetracker/total)](https://github.com/YOUR_USERNAME/animetracker/releases)
```

---

## Troubleshooting

**"Windows protected your PC" warning when running the exe**
→ This is Windows Defender SmartScreen blocking an unsigned exe. Click "More info" → "Run anyway". This happens because the exe isn't code-signed (which costs ~$200/year). Tell your friends to expect this and click through.

**The exe is huge (~80–100 MB)**
→ Normal for PyQt6 apps bundled with PyInstaller. PyQt6 is a large library.

**App says "No update available" even after I published a new release**
→ Make sure you bumped `APP_VERSION` in `core/updater.py` in the OLD version before you built it. The version string in the running exe is what gets compared to GitHub.

**Friends on Mac or Linux**
→ They need to run from source (`python main.py`) for now. PyInstaller builds are platform-specific — a Windows exe doesn't run on Mac. If you want Mac support, build on a Mac. Linux same.