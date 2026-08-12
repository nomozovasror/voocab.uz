from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.audio import router as audio_router
from app.api.auth import router as auth_router
from app.api.listening import router as listening_router
from app.api.materials import MATERIAL_VERSION_HEADER
from app.api.materials import router as materials_router
from app.api.studio import router as studio_router
from app.core.config import settings

app = FastAPI(title="voocab.uz API")

# The frontend (voocab.uz) and API (api.voocab.uz) are separate origins, so the
# browser needs CORS to send/receive the session cookies. allow_credentials is
# required for cookies; origins come from config (never "*", which is invalid
# alongside credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # `allow_headers` covers what the browser may SEND; a response header the
    # frontend needs to READ has to be named here as well, or the browser
    # hands JavaScript a null for it and the editor silently loses track of
    # the material version it is meant to be checking against.
    expose_headers=[MATERIAL_VERSION_HEADER],
)

app.include_router(auth_router)
app.include_router(materials_router)
app.include_router(audio_router)
app.include_router(listening_router)
app.include_router(studio_router)

# In dev (no R2), serve uploaded media off local disk. In prod the R2 public
# base URL fronts the bucket, so no local mount is needed.
if not settings.use_r2:
    media_root = Path(settings.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.media_url_prefix,
        StaticFiles(directory=media_root),
        name="media",
    )


@app.get("/health")
def health():
    return {"status": "ok"}
