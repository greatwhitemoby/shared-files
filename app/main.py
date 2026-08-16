import hmac
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .storage import LocalStorage, S3Storage

SHARE_PASSWORD = os.environ.get("SHARE_PASSWORD", "")
if not SHARE_PASSWORD:
    raise RuntimeError("SHARE_PASSWORD environment variable must be set")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-secret-change-me")
DATA_DIR = os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "512")) * 1024 * 1024

if os.environ.get("R2_ENDPOINT"):
    storage = S3Storage(
        os.environ["R2_ENDPOINT"],
        os.environ["R2_ACCESS_KEY"],
        os.environ["R2_SECRET_KEY"],
        os.environ["R2_BUCKET"],
        os.environ.get("R2_REGION"),
    )
else:
    storage = LocalStorage(DATA_DIR)

app = FastAPI(title="Shared Files")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False)


def require_auth(request: Request):
    if not request.session.get("auth"):
        raise HTTPException(status_code=401, detail="Not authenticated")


class LoginBody(BaseModel):
    password: str


@app.get("/api/status")
def status(request: Request):
    return {"authed": bool(request.session.get("auth"))}


@app.post("/api/login")
def login(body: LoginBody, request: Request):
    if hmac.compare_digest(body.password.encode(), SHARE_PASSWORD.encode()):
        request.session["auth"] = True
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Wrong password")


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/files")
def list_files(_=Depends(require_auth)):
    return {"files": storage.list_files()}


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), _=Depends(require_auth)):
    name = (file.filename or "file")[:255]
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(status_code=413, detail="File too large")
            tmp.write(chunk)
        tmp.seek(0)
        return storage.save(name, tmp, size)


@app.get("/api/file/{fid}")
def download(fid: str, _=Depends(require_auth)):
    found = storage.open_file(fid)
    if found is None:
        raise HTTPException(status_code=404, detail="File not found")
    meta, stream = found
    filename = quote(meta.get("name", fid))
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.delete("/api/file/{fid}")
def delete(fid: str, _=Depends(require_auth)):
    storage.delete_file(fid)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return HTMLResponse(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shared Files</title>
<style>
  :root { --bg:#0f1117; --card:#171a23; --border:#262b3a; --text:#e6e8ee; --muted:#8b90a0; --accent:#4f8cff; --accent2:#37b66d; --danger:#e5534b; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
  .wrap { max-width:760px; margin:0 auto; padding:40px 20px; }
  h1 { font-size:22px; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 28px; font-size:14px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:24px; }
  .hidden { display:none !important; }
  input[type=password], input[type=file] { width:100%; padding:11px 12px; background:#0d0f15; border:1px solid var(--border); border-radius:8px; color:var(--text); font-size:14px; margin-bottom:14px; }
  input[type=password]:focus { outline:none; border-color:var(--accent); }
  button { cursor:pointer; border:none; border-radius:8px; padding:11px 18px; font-size:14px; font-weight:600; }
  .btn-primary { background:var(--accent); color:#fff; width:100%; }
  .btn-primary:hover { filter:brightness(1.1); }
  .btn-ghost { background:#232839; color:var(--text); }
  .btn-ghost:hover { background:#2c3247; }
  label { display:block; font-size:13px; color:var(--muted); margin-bottom:6px; }
  .dropzone { border:2px dashed var(--border); border-radius:10px; padding:28px; text-align:center; color:var(--muted); cursor:pointer; margin-bottom:16px; font-size:14px; }
  .dropzone.drag { border-color:var(--accent); color:var(--text); }
  .progress { height:8px; background:#0d0f15; border-radius:6px; overflow:hidden; margin:14px 0; display:none; }
  .progress > div { height:100%; width:0; background:var(--accent2); transition:width .2s; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; color:var(--muted); font-weight:500; padding:8px 6px; border-bottom:1px solid var(--border); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  td { padding:12px 6px; border-bottom:1px solid var(--border); }
  tr:last-child td { border-bottom:none; }
  .fname { word-break:break-all; max-width:380px; }
  a.dl { color:var(--accent); text-decoration:none; font-weight:600; }
  a.dl:hover { text-decoration:underline; }
  .meta { color:var(--muted); font-size:12px; white-space:nowrap; }
  .del { background:none; border:none; color:var(--danger); font-size:13px; padding:4px; }
  .err { color:var(--danger); font-size:13px; margin:10px 0; min-height:16px; }
  .empty { color:var(--muted); text-align:center; padding:22px 0; font-size:14px; }
  .topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; }
  .toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:#2c3247; border:1px solid var(--border); padding:10px 16px; border-radius:8px; font-size:14px; opacity:0; transition:opacity .25s; pointer-events:none; }
  .toast.show { opacity:1; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <h1>Shared Files</h1>
      <p class="sub" style="margin:0">Private file share — only people who know the password can access it.</p>
    </div>
    <button class="btn-ghost hidden" id="logoutBtn">Log out</button>
  </div>

  <div id="loginView" class="card hidden">
    <label for="password">Password</label>
    <input type="password" id="password" autocomplete="current-password" placeholder="Enter the shared password" autofocus>
    <button class="btn-primary" id="loginBtn">Sign in</button>
    <div class="err" id="loginErr"></div>
  </div>

  <div id="appView" class="hidden">
    <div class="card">
      <div class="dropzone" id="dropzone">
        Click to choose a file, or drag &amp; drop it here
      </div>
      <input type="file" id="fileInput" class="hidden">
      <div class="progress" id="progress"><div id="progressBar"></div></div>
      <div class="err" id="uploadErr"></div>
    </div>

    <div class="card" style="margin-top:20px">
      <table>
        <thead><tr><th>Name</th><th>Size</th><th>Uploaded</th><th></th></tr></thead>
        <tbody id="fileList"></tbody>
      </table>
      <div class="empty hidden" id="emptyMsg">No files yet. Upload the first one above.</div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const $ = id => document.getElementById(id);
let currentName = '';

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error('unauthorized'); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

function showLogin() {
  $('appView').classList.add('hidden');
  $('loginView').classList.remove('hidden');
  $('logoutBtn').classList.add('hidden');
  $('password').focus();
}
function showApp() {
  $('loginView').classList.add('hidden');
  $('appView').classList.remove('hidden');
  $('logoutBtn').classList.remove('hidden');
  loadFiles();
}
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

$('loginBtn').onclick = async () => {
  $('loginErr').textContent = '';
  try {
    await api('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('password').value }),
    });
    $('password').value = '';
    showApp();
  } catch (e) { $('loginErr').textContent = 'Wrong password'; }
};
$('password').addEventListener('keydown', e => { if (e.key === 'Enter') $('loginBtn').click(); });

$('logoutBtn').onclick = async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch (e) {}
  showLogin();
};

$('dropzone').onclick = () => $('fileInput').click();
$('fileInput').onchange = () => { if ($('fileInput').files[0]) doUpload($('fileInput').files[0]); };
$('dropzone').ondragover = e => { e.preventDefault(); $('dropzone').classList.add('drag'); };
$('dropzone').ondragleave = () => $('dropzone').classList.remove('drag');
$('dropzone').ondrop = e => {
  e.preventDefault();
  $('dropzone').classList.remove('drag');
  const f = e.dataTransfer.files[0];
  if (f) doUpload(f);
};

function doUpload(file) {
  $('uploadErr').textContent = '';
  $('dropzone').textContent = 'Uploading "' + file.name + '"...';
  const fd = new FormData();
  fd.append('file', file);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');
  $('progress').style.display = 'block';
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) $('progressBar').style.width = (e.loaded / e.total * 100) + '%';
  };
  xhr.onload = () => {
    $('progress').style.display = 'none';
    $('dropzone').textContent = 'Click to choose a file, or drag & drop it here';
    if (xhr.status >= 200 && xhr.status < 300) { toast('Uploaded ' + file.name); loadFiles(); }
    else $('uploadErr').textContent = 'Upload failed: ' + xhr.statusText;
  };
  xhr.onerror = () => {
    $('progress').style.display = 'none';
    $('dropzone').textContent = 'Click to choose a file, or drag & drop it here';
    $('uploadErr').textContent = 'Upload failed';
  };
  xhr.send(fd);
}

function fmtSize(n) {
  if (n < 1024) return n + ' B';
  const u = ['KB', 'MB', 'GB', 'TB'];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(1) + ' ' + u[i];
}

async function loadFiles() {
  const { files } = await api('/api/files');
  const tb = $('fileList');
  tb.innerHTML = '';
  $('emptyMsg').classList.toggle('hidden', files.length > 0);
  for (const f of files) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="fname"><a class="dl" href="/api/file/' + f.id + '">' + esc(f.name) + '</a></td>' +
      '<td class="meta">' + fmtSize(f.size) + '</td>' +
      '<td class="meta">' + new Date(f.uploaded_at * 1000).toLocaleString() + '</td>' +
      '<td style="text-align:right"><button class="del" title="Delete">Delete</button></td>';
    tr.querySelector('.del').onclick = async () => {
      if (!confirm('Delete "' + f.name + '"?')) return;
      await api('/api/file/' + f.id, { method: 'DELETE' });
      toast('Deleted ' + f.name);
      loadFiles();
    };
    tb.appendChild(tr);
  }
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

(async () => {
  const { authed } = await api('/api/status');
  if (authed) showApp(); else showLogin();
})();
</script>
</body>
</html>
"""
