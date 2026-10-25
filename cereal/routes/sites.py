"""The signed-in user's private site list (owner: unit 2).
GET /sites → [site]; POST /sites {url} → probe + site_registry.add; POST /sites/{id}/remove. All need a session.
"""
from fastapi import APIRouter

router = APIRouter()
