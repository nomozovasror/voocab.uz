from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
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
)

app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}
