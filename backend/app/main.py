from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import http
from .service import compare
from .sources.amazon import UnsupportedProduct

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Scruge product matcher")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CompareRequest(BaseModel):
    url: str
    refresh: bool = False


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/compare")
def compare_endpoint(req: CompareRequest):
    try:
        return compare(req.url, use_cache=not req.refresh)
    except UnsupportedProduct as e:
        raise HTTPException(status_code=422, detail=str(e))
    except http.FetchError as e:
        raise HTTPException(status_code=502, detail=f"Couldn't read the Amazon page: {e}")
