"""分来源推荐接口：引证登记/撤销、按入口看板、重算复算与种子扩边。

路由层不做业务判断，全部委托 app.services.reco_source 的领域中心处理。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, ExpandPayload, RecomputePayload
from app.services.reco_source import reco_source_hub

router = APIRouter(prefix="/api/reco_source", tags=["分来源推荐"])


@router.get("/evidence")
def list_evidence(
    attribution: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    rows = reco_source_hub.evidence_rows()
    if attribution:
        rows = [row for row in rows if row.get("归属") == attribution]
    if status:
        rows = [row for row in rows if row.get("状态") == status]
    return {"items": rows, "total": len(rows)}


@router.post("/evidence", response_model=ActionResult)
def register_evidence(payload: EntryPayload) -> ActionResult:
    entry, message, _duplicated = reco_source_hub.register_evidence(payload.values)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/evidence/{code}/revoke", response_model=ActionResult)
def revoke_evidence(code: str) -> ActionResult:
    entry, message = reco_source_hub.revoke_evidence(code)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.get("/board")
def board(entry: str = Query(...)) -> dict[str, Any]:
    try:
        return reco_source_hub.board(entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recompute")
def recompute(payload: RecomputePayload) -> dict[str, Any]:
    try:
        return reco_source_hub.recompute(payload.entry)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/recomputes")
def recompute_logs() -> dict[str, Any]:
    rows = reco_source_hub.recompute_rows()
    return {"items": rows, "total": len(rows)}


@router.post("/expand", response_model=ActionResult)
def expand(payload: ExpandPayload) -> ActionResult:
    todo, message = reco_source_hub.submit_seed(
        seed=payload.seed,
        entry=payload.entry,
        relations=payload.relations,
        operator=payload.operator or "",
    )
    return ActionResult(ok=todo is not None, message=message, entry=todo)


@router.get("/expansions")
def expansions() -> dict[str, Any]:
    rows = reco_source_hub.expansion_todos()
    return {"items": rows, "total": len(rows)}
