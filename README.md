# Shared Files

A private file share for just the two of you. One shared password unlocks it;
anyone without the password can't see, upload, or download anything.

- **Stack:** Python + FastAPI, single-page web UI
- **Storage:** Cloudflare R2 (free 10 GB) so files survive restarts, with a
  local-disk fallback for development
- **Hosting:** works on Render's free tier (see below)

## How it works

1. You and your partner go to the app's URL.
2. Both sign in with the same shared password.
3. Drag & drop files to upload; click a file to download; Delete to remove.

## Run locally (for testing)

```bash
cd fileshare
pip install -r requirements.txt
export SHARE_PASSWORD="pick-a-strong-password"
export SECRET_KEY="some-long-random-string"
uvicorn app.main:app --port 8000
```

Open http://localhost:8000, sign in with `SHARE_PASSWORD`, done.

Without R2 configured, files are stored on disk in `./data`.

## Deploy for free (persistent files)

Free hosting tiers wipe disk storage on restart, so use Cloudflare R2 (free
10 GB, no egress fees) for the files.

### 1. Create a Cloudflare R2 bucket (5 minutes)

1. Sign up at https://dash.cloudflare.com (free).
2. Go to **R2** (left menu) → **Create bucket** → name it, e.g. `shared-files`.
   Note: enabling R2 may ask for a payment method, but you are not charged
   within the free tier.
3. Go to **R2 → Manage R2 API Tokens → Create API Token**. Enable
   *Object Read & Write*. Copy the **Access Key ID** and **Secret Access Key**.
4. Your R2 endpoint is:
   `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
   (find the Account ID on the R2 overview page).

### 2. Deploy the app to Render (free)

Option A — one-click Blueprint (easiest):

1. Put this folder in a GitHub repo:
   ```bash
   git init && git add -A && git commit -m "Shared files app"
   # push to a new GitHub repo
   ```
2. Go to https://dashboard.render.com → **New + → Blueprint** → select the repo.
   `render.yaml` is picked up automatically.
3. In the **Environment** tab of the created service, set:
   - `SHARE_PASSWORD` — the password you and your partner will use
   - `R2_ENDPOINT`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` from step 1
4. **Manual Deploy → Deploy latest commit**, then click the service URL.

Option B — manual:

1. New + → **Web Service** → connect the repo.
2. Choose **Docker** runtime, free plan.
3. Add the same env vars listed above.
4. Deploy.

### 3. Share it

Give your partner the service URL (something like
`https://shared-files.onrender.com`) and the password. That's it — just the two
of you.

## Notes

- Render's free tier puts the app to sleep after ~15 minutes idle; the first
  request after waking can take 30–60 s. It wakes automatically.
- Change `SHARE_PASSWORD` anytime in Render's Environment tab and redeploy.
- Max upload size is controlled by `MAX_UPLOAD_MB` (default 512).
- Files are stored privately in your R2 bucket; they are never served to the
  public — everything is behind the password.

## Layout

```
app/main.py       FastAPI app: auth, routes, web UI
app/storage.py    storage backends (local disk / S3-compatible R2)
Dockerfile        container image
render.yaml       Render Blueprint config
.env.example      sample environment variables
```
