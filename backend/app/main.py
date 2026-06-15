from fastapi import FastAPI

app = FastAPI(title="voocab.uz API")


@app.get("/health")
def health():
    return {"status": "ok"}
