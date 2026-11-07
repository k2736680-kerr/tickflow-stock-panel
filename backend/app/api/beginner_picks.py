"""Beginner picks HTTP adapter. Heavy logic lives in services.beginner_picks."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.beginner_pick_review import attach_review
from app.services.beginner_picks import build_beginner_picks

router = APIRouter(prefix="/api/beginner", tags=["beginner"])


@router.get("/picks")
def beginner_picks(request: Request) -> dict:
    repo = request.app.state.repo
    data_dir = repo.store.data_dir
    payload = attach_review(repo, data_dir, build_beginner_picks(repo, data_dir))
    try:
        from app.services import remote_store
        remote_store.push_async("beginner_picks", payload)
    except Exception:
        pass
    return payload
