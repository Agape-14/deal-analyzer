from fastapi import Depends, HTTPException

from app.auth import is_analyst, require_auth


async def require_analyst(user: dict = Depends(require_auth)) -> dict:
    """Require the operator role for an analyst-only API route."""
    if not is_analyst(user):
        raise HTTPException(status_code=403, detail="Viewer accounts are read-only")
    return user
