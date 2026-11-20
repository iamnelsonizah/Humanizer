# Deploying Humanizer

Two parts, deployed separately:

| Part | What it is | Where | Folder |
|---|---|---|---|
| API | FastAPI app `humanizer.api:app` (scan, humanize, voice profile) | FastAPI Cloud | repo root |
| Website | Static HTML/CSS/JS, no build step | Vercel | `humanizer/web/static` |

The website calls the API directly from the browser. It does not go through a Vercel proxy, because a rewrite can
take a minute or more and Vercel does not document timeout or streaming limits for external rewrites. So the API
has to allow the website's domain (CORS), and the website has to know the API's URL (`config.js`).

```
browser ── https://humanizer.vercel.app (Vercel: static files)
   │
   └── fetch /api/* ──► https://humanizer.fastapicloud.dev (FastAPI Cloud) ──► Claude API
```

## 0. Before you start

1. **Get a real Anthropic API key.** It starts with `sk-ant-`. Create one at https://console.anthropic.com →
   API Keys. The key in your local `.env` was rejected by Anthropic, so replace it there too.
2. **Put the project in a Git repo** (Vercel deploys best from GitHub):
   ```bash
   git init && git add . && git commit -m "Humanizer web app"
   ```
   `.gitignore` already leaves out `.env` and `.venv/`, so your key is not committed.
3. **Check it locally:**
   ```bash
   .venv/bin/pip install -e '.[dev]'
   .venv/bin/pytest
   .venv/bin/humanize web
   ```
   Then open http://127.0.0.1:8765.

## 1. Deploy the API to FastAPI Cloud

FastAPI Cloud reads `pyproject.toml`. It installs the dependencies listed there (`anthropic`, `fastapi[standard]`)
and starts the app named by:

```toml
[tool.fastapi]
entrypoint = "humanizer.api:app"
```

Uploads follow `.gitignore` and `.fastapicloudignore`. Neither `.env` nor `.venv/` is uploaded.

```bash
# from the repo root (the CLI ships with fastapi[standard], which is already installed in .venv)
.venv/bin/fastapi login
.venv/bin/fastapi deploy
```

The first deploy asks you to pick a team and create the app. Call it `humanizer`. The CLI prints the URL, which
looks like `https://humanizer.fastapicloud.dev`. It also writes a `.fastapicloud/` folder that links this project to
the app; commit it or keep it, and later deploys reuse it.

### Set the API's environment variables

```bash
.venv/bin/fastapi cloud env set --secret ANTHROPIC_API_KEY      # prompts for the value, hidden
.venv/bin/fastapi cloud env set ALLOWED_ORIGINS "https://humanizer.vercel.app"
.venv/bin/fastapi cloud env set RATE_LIMIT_PER_HOUR 20
.venv/bin/fastapi deploy                                         # env changes apply on the next deploy
```

You can also set these in the dashboard: App → Environment Variables → "Save and Redeploy".

| Variable | Needed | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Your Claude key. Mark it **Secret**. |
| `ALLOWED_ORIGINS` | yes | Comma-separated sites allowed to call the API, exactly as the browser shows them, with no trailing slash. Add your custom domain here too, e.g. `https://humanizer.vercel.app,https://humanizer.app`. |
| `ALLOWED_ORIGIN_REGEX` | optional | Lets Vercel preview URLs work, e.g. `https://humanizer-[a-z0-9-]+\.vercel\.app`. |
| `RATE_LIMIT_PER_HOUR` | optional | Rewrites per visitor IP per hour. The default is 20; `0` turns the limit off. |
| `ACCESS_CODE` | optional | Makes the site private. Visitors type the code under **Safeguards**. Use this while testing with a small group. |

> **Cost warning.** Once the site is public, every rewrite runs on your Anthropic bill. A typical essay is 2 to 4
> model calls. Keep `RATE_LIMIT_PER_HOUR` on, set `ACCESS_CODE` until you are ready to open it up, and set a
> monthly spend limit in the Anthropic console. The built-in rate limit is per replica and resets on restart.
> That is fine for launch, but add accounts or a shared store such as Redis before you scale.

### Check the API

```bash
curl https://humanizer.fastapicloud.dev/api/health          # {"ok":true}
curl https://humanizer.fastapicloud.dev/api/meta            # "has_key": true
```

The interactive API docs are at `https://humanizer.fastapicloud.dev/api/docs`. The API URL also serves the full UI,
which is a handy way to test before Vercel is set up.

On the Hobby plan, the API scales to zero when idle, so the first request after a quiet period takes a few
seconds to start.

## 2. Deploy the website to Vercel

### Point the site at the API

Edit `humanizer/web/static/config.js`:

```js
window.HUMANIZER_API = "https://humanizer.fastapicloud.dev";
```

Commit and push. This URL is public anyway, since the browser calls it. It is not a secret. On `localhost` the
setting is ignored, so local development keeps working.

### Option A: Vercel dashboard (recommended)

1. https://vercel.com/new → import your GitHub repo.
2. **Root Directory:** `humanizer/web/static`
3. **Framework Preset:** Other
4. **Build Command:** turn Override on and leave it empty. **Output Directory:** leave the default (`.`).
5. Deploy. Every push to `main` now redeploys the site.

`humanizer/web/static/vercel.json` adds security headers and stops browsers caching stale JS and CSS.

### Option B: Vercel CLI

```bash
npm i -g vercel
vercel login
cd humanizer/web/static
vercel          # first run links the project; answer "Other" / no build command
vercel --prod   # later production deploys
```

### Finish the connection

1. Copy the Vercel production URL (e.g. `https://humanizer.vercel.app`).
2. Make sure it is in `ALLOWED_ORIGINS` on FastAPI Cloud, exactly as shown, then run `fastapi deploy` again.
3. Open the site, click **Or try one: Research abstract**, and press **Humanize**.

## 3. Custom domain (optional)

- **Website:** Vercel → Project → Settings → Domains → add `humanizer.app` (or your domain) and follow the DNS
  instructions.
- **API:** FastAPI Cloud → App → Custom Domains, e.g. `api.humanizer.app` with a CNAME. If your DNS is on
  Cloudflare, set that record to **DNS only**.
- Then update both sides: `config.js` → `https://api.humanizer.app`, and add `https://humanizer.app` to
  `ALLOWED_ORIGINS`. Redeploy both.

## 4. Updating later

| Changed | Do |
|---|---|
| Python code, prompts, detector | `.venv/bin/fastapi deploy` |
| HTML, CSS, JS | `git push` (Vercel redeploys), or `vercel --prod` |
| API URL | edit `config.js`, then push |
| New website domain | add it to `ALLOWED_ORIGINS`, then `fastapi deploy` |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Server unreachable" in the header | Wrong `config.js` URL, or the API is asleep or down. Open `/api/health`. |
| Browser console shows a CORS error | The site's origin is missing from `ALLOWED_ORIGINS`, or has a trailing slash. Fix it and redeploy the API. |
| "No working ANTHROPIC_API_KEY" | The key is missing or invalid on FastAPI Cloud. Set it with `fastapi cloud env set --secret ANTHROPIC_API_KEY`, then redeploy. |
| "Limit reached: N rewrites per hour" | The rate limit is working. Raise `RATE_LIMIT_PER_HOUR` if needed. |
| "This Humanizer needs an access code" | `ACCESS_CODE` is set. Enter it under **Safeguards**. |
| The page shows old styles after a deploy | Hard refresh. `vercel.json` already forces revalidation of the JS and CSS. |
