"""POST /sites/probe {url} → sites_probe.probe(url) (owner: unit 1). Reads only; no session needed."""
from fastapi import APIRouter

router = APIRouter()
