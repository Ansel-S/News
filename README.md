# 📡 AllStar Terminal

> Private, tracker-free Finance & Tech news aggregator — iOS 18 liquid glass aesthetic — GitHub Pages hosted.

---

## 🗂 File Structure

```
allstar-terminal/
├── index.html          ← SPA shell (semantic HTML)
├── styles.css          ← iOS 18 glassmorphism theme
├── scripts.js          ← Reader mode + data fetching (vanilla JS)
├── script.py           ← RSS aggregator (Python + feedparser)
├── data.json           ← Generated feed data (auto-updated)
└── .github/
    └── workflows/
        └── update.yml  ← GitHub Actions: refresh every 4 hours
```

---

## 🚀 Deployment (5 minutes)

### 1. Create a new GitHub repository

```bash
git init
git add .
git commit -m "initial: AllStar Terminal"
git remote add origin https://github.com/YOUR_USERNAME/allstar-terminal.git
git push -u origin main
```

### 2. Enable GitHub Pages

Settings → Pages → **Source: Deploy from a branch** → Branch: `main` → Folder: `/ (root)` → Save.

Your terminal will be live at: `https://YOUR_USERNAME.github.io/allstar-terminal/`

### 3. Trigger your first feed update

Actions tab → **🔄 Refresh News Feed** → **Run workflow**.

After ~60 seconds, real articles will appear.

---

## 🐍 Local Development

```bash
pip install feedparser requests
python script.py           # generates data.json
python -m http.server 8080  # serve locally at http://localhost:8080
```

---

## ⚙️ Customization

### Add / remove sources

Edit the `SOURCES` list in `script.py`. Each entry:

| Key           | Description                                         |
|---------------|-----------------------------------------------------|
| `id`          | Unique slug                                         |
| `label`       | Display name on cards                               |
| `icon`        | Emoji icon                                          |
| `url`         | RSS/Atom feed URL                                   |
| `column`      | `"pulse"` \| `"facts"` \| `"geek"`                 |
| `limit`       | Max articles (5–8 recommended)                      |
| `tag`         | Category badge text                                 |

### Change refresh frequency

Edit the `cron` expression in `.github/workflows/update.yml`:

```yaml
- cron: "0 */4 * * *"   # every 4 hours — change as needed
```

### Twitter/X feeds via RSSHub

The configured `rsshub.app` public instance may have rate limits. For guaranteed reliability:

```bash
# Self-host RSSHub via Docker
docker run -d -p 1200:1200 diygod/rsshub
```

Then replace `https://rsshub.app/twitter/user/HANDLE` with `http://localhost:1200/twitter/user/HANDLE` in your `script.py`.

---

## 🔒 Privacy

- **100% static** — no server-side code at runtime
- **Zero tracking** — no analytics, no third-party scripts, no cookies
- **Self-contained** — all data lives in your GitHub repository
- **noindex** — `<meta name="robots" content="noindex, nofollow">` prevents search indexing

---

## 📐 Architecture

```
GitHub Actions (every 4h)
    └── python script.py
            ├── feedparser → fetch 13 RSS sources
            ├── deduplicate by SHA-1(url+title)
            ├── sanitize HTML
            └── write data.json

Browser (static SPA)
    ├── fetch data.json on load
    ├── render glassmorphism cards into 3 columns
    └── Reader Mode → render body_html in modal overlay
```

---

*Built with ♥ and zero trackers.*
