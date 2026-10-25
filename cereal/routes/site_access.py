"""Get a site's content (owner: unit 4). All need a session and the site must be the user's.
POST /sites/{id}/open → site_access.open_free; POST /sites/{id}/buy {speculos_decision?, request_id?} → site_access.buy;
GET /sites/{id}/content → site_access.content.
"""
from fastapi import APIRouter

router = APIRouter()
