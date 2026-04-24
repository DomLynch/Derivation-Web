"""HTMX/Jinja server-rendered pages. Chain view is primary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from derivation_web.core.graph import walk_provenance
from derivation_web.db import repo
from derivation_web.db.session import get_session

router = APIRouter(include_in_schema=False)

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html")  # type: ignore[no-any-return]


@router.get("/artifacts/{artifact_id}", response_class=HTMLResponse)
def view_artifact(
    artifact_id: str, request: Request, session: SessionDep
) -> HTMLResponse:
    artifact = repo.get_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(404)
    producing = repo.get_producing_step(session, artifact_id)
    challenges, revisions = repo.get_annotations(session, artifact_id)
    actor = repo.get_actor(session, artifact.actor_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "artifact.html",
        {
            "artifact": artifact,
            "actor": actor,
            "producing": producing,
            "challenges": challenges,
            "revisions": revisions,
        },
    )


@router.get("/artifacts/{artifact_id}/chain", response_class=HTMLResponse)
def view_chain(
    artifact_id: str, request: Request, session: SessionDep
) -> HTMLResponse:
    if repo.get_artifact(session, artifact_id) is None:
        raise HTTPException(404)
    nodes = walk_provenance(
        root_artifact_id=artifact_id,
        get_artifact=lambda aid: repo.get_artifact(session, aid),
        get_producing_step=lambda aid: repo.get_producing_step(session, aid),
    )
    rendered = []
    for node in nodes:
        challenges, revisions = repo.get_annotations(session, node.artifact.id)
        rendered.append(
            {
                "artifact": node.artifact,
                "producing_step": node.producing_step,
                "depth": node.depth,
                "challenges": challenges,
                "revisions": revisions,
            }
        )
    templates = request.app.state.templates
    return templates.TemplateResponse(  # type: ignore[no-any-return]
        request,
        "chain.html",
        {
            "root_id": artifact_id,
            "nodes": rendered,
        },
    )
