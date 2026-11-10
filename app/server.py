"""Print Studio local server: the UI's API, live updates, and the project files."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pipeline import JOBS, Studio

STATIC = Path(__file__).resolve().parent / "static"
clients: set[asyncio.Queue] = set()
loop: asyncio.AbstractEventLoop | None = None


def notify(job):
    if loop is None:
        return
    data = json.dumps(job)
    for q in list(clients):
        loop.call_soon_threadsafe(q.put_nowait, data)


studio = Studio(notify)


@asynccontextmanager
async def lifespan(_app):
    global loop
    loop = asyncio.get_running_loop()
    studio.start()
    yield
    studio.worker.stop()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def no_stale_ui(request, call_next):
    """The app's own page and scripts must always be the current version after an update (a cached
    index.html with a fresh app.js broke the editor once); job files are versioned by URL instead."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/jobs")
def jobs():
    return studio.list_jobs()


@app.get("/api/jobs/{jid}")
def job(jid: str):
    try:
        return studio.load(jid)
    except FileNotFoundError:
        raise HTTPException(404, "No such project")


@app.post("/api/jobs/idea")
def from_idea(idea: str = Form(...)):
    if not idea.strip():
        raise HTTPException(400, "Write what you want to make.")
    return studio.create_from_idea(idea)


@app.post("/api/jobs/photos")
async def from_photos(photos: list[UploadFile] = File(...)):
    if len(photos) not in (1, 4):
        raise HTTPException(400, "Add 1 photo, or 4 photos (front, right, back, left).")
    files = [(p.filename or "photo.png", await p.read()) for p in photos]
    return studio.create_from_photos(files)


@app.post("/api/jobs/file")
async def from_file(files: list[UploadFile] = File(...)):
    if not files or len(files) > 20:
        raise HTTPException(400, "Add one 3D file (with its .mtl and texture for an OBJ), or a .zip.")
    data = [(f.filename or "model", await f.read()) for f in files]
    return studio.create_from_file(data)


@app.post("/api/convert")
async def convert(files: list[UploadFile] = File(...)):
    if not files or len(files) > 60:
        raise HTTPException(400, "Add up to 60 mesh files (STL, 3MF, OBJ, GLB, PLY, OFF), or a .zip.")
    data = [(f.filename or "model", await f.read()) for f in files]
    try:
        return studio.create_conversion(data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/edit/{jid}")
async def edit(jid: str, payload: dict):
    try:
        return await asyncio.to_thread(studio.edit, jid, payload)
    except FileNotFoundError:
        raise HTTPException(404, "No such project")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/jobs/{jid}/{action}")
async def act(jid: str, action: str, payload: dict | None = None):
    try:
        return await asyncio.to_thread(studio.act, jid, action, payload or {})
    except FileNotFoundError:
        raise HTTPException(404, "No such project")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/estimate/{jid}")
async def estimate(jid: str, payload: dict):
    r = await asyncio.to_thread(studio.estimate, jid, payload.get("palette", []))
    if r is None:
        raise HTTPException(404, "Not measured yet")
    return r


@app.get("/api/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    clients.add(q)

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            clients.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


app.mount("/jobs", StaticFiles(directory=JOBS), name="jobs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
