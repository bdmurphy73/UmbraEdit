"""
UmbraStore - REST API server
============================

FastAPI application implementing the UmbraStore HTTP API.
Endpoints for projects, files, revisions, changes, and health.
"""  # noqa

from __future__ import annotations

import hashlib
import os

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.requests import Request

from umbrastore import __version__
from umbrastore.auth import verifyToken
from umbrastore.blobs import BlobStore
from umbrastore.database import Database, connect, initDatabase, ulid

# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str


class FilePutResponse(BaseModel):
    rev: str
    sha256: str
    cursor: str


class HealthResponse(BaseModel):
    ok: bool
    version: str


class ChangeItem(BaseModel):
    seq: int
    at: str
    op: str
    path: str
    rev: str | None = None
    sha256: str | None = None
    deviceId: str | None = None
    actorId: str | None = None


class ChangesResponse(BaseModel):
    items: list[ChangeItem]
    next: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="UmbraStore", version=__version__)


@app.exception_handler(HTTPException)
async def httpExceptionHandler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return HTTPException details in the standard error format.

    Error body: {"error": {"code", "message", "details"}}
    """
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "invalidRequest",
                "message": str(exc.detail),
                "details": None,
            }
        },
    )


# Global state set at startup
_db: Database | None = None
_blobs: BlobStore | None = None
_dataDir: Path | None = None


def getDb() -> Database:
    if _db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialised",
        )
    return _db


def getBlobs() -> BlobStore:
    if _blobs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blob store not initialised",
        )
    return _blobs


def getAuthToken(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Extract and validate Bearer token from Authorization header."""
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="unauthorized",
                    message="Missing Authorization header",
                    details=None,
                )
            ).model_dump(),
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="unauthorized",
                    message="Invalid Authorization header format",
                    details=None,
                )
            ).model_dump(),
        )
    return parts[1]


def verifyAuth(token: str = Depends(getAuthToken)) -> None:
    """Verify the bearer token against all known accounts."""
    db = getDb()
    # Look up the account by trying all accounts (tokens are not reversible)
    # For efficiency we could index by token hash prefix, but for now
    # iterate accounts.
    cur = db.connection.execute("SELECT id, tokenHash FROM account")
    for row in cur.fetchall():
        if verifyToken(token, row["tokenHash"]):
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ErrorResponse(
            error=ErrorDetail(
                code="unauthorized",
                message="Invalid token",
                details=None,
            )
        ).model_dump(),
    )


def utcNowIso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def cursorForSeq(seq: int) -> str:
    """Format a cursor as ev-<12 digits>."""
    return f"ev-{seq:012d}"


def seqFromCursor(cursor: str | None) -> int | None:
    """Parse a cursor ev-<12 digits> into a seq integer."""
    if cursor is None:
        return None
    if not cursor.startswith("ev-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="invalidRequest",
                    message="Invalid cursor format",
                    details=None,
                )
            ).model_dump(),
        )
    try:
        return int(cursor[3:])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="invalidRequest",
                    message="Invalid cursor value",
                    details=None,
                )
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------


@app.on_event("startup")
def _startup() -> None:
    global _db, _blobs, _dataDir
    dataDir = Path(os.environ.get("UMBRASTORE_DATA_DIR", "./data"))
    _dataDir = dataDir
    initDatabase(dataDir)
    conn = connect(dataDir)
    _db = Database(conn)
    _blobs = BlobStore(dataDir)


@app.on_event("shutdown")
def _shutdown() -> None:
    if _db is not None:
        _db.close()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, version=__version__)


@app.post("/v1/projects", response_model=ProjectResponse, status_code=201)
def createProject(
    body: ProjectCreate,
    _auth: None = Depends(verifyAuth),
) -> ProjectResponse:
    db = getDb()
    projectId = ulid()
    now = utcNowIso()
    db.createProject(projectId, body.name, now)
    db.commit()
    return ProjectResponse(id=projectId)


@app.put("/v1/projects/{projectId}/files/{path:path}")
async def putFile(
    projectId: str = PathParam(..., description="Project ID"),
    path: str = PathParam(..., description="File path"),
    request: Request = ...,  # type: ignore[arg-type]
    ifMatch: str | None = Header(default=None, alias="If-Match"),
    xDevice: str | None = Header(default=None, alias="X-Device"),
    xActor: str | None = Header(default=None, alias="X-Actor"),
    _auth: None = Depends(verifyAuth),
) -> FilePutResponse:
    db = getDb()
    blobs = getBlobs()

    # Verify project exists
    project = db.getProject(projectId)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"Project {projectId} not found",
                    details=None,
                )
            ).model_dump(),
        )

    # Read body bytes
    body = await request.body()

    # Compute SHA-256 of the content
    sha256 = hashlib.sha256(body).hexdigest()
    size = len(body)

    # Get current head revision
    fileRow = db.getFile(projectId, path)
    headRev = fileRow["headRev"] if fileRow else None
    deleted = fileRow["deleted"] if fileRow else 0

    # If-Match handling
    if ifMatch is not None:
        # Strip quotes if present
        matchRev = ifMatch.strip('"')
        if headRev is None or matchRev != headRev:
            # headMoved conflict
            headSha = None
            if headRev is not None:
                headRevRow = db.getRevision(headRev)
                if headRevRow is not None:
                    headSha = headRevRow["sha256"]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="headMoved",
                        message="Head revision has moved",
                        details={
                            "headRev": headRev,
                            "headSha256": headSha,
                        },
                    )
                ).model_dump(),
            )

    # Idempotence: if content identical to head, return existing rev
    if headRev is not None:
        headRevRow = db.getRevision(headRev)
        if headRevRow is not None and headRevRow["sha256"] == sha256:
            return FilePutResponse(
                rev=headRev,
                sha256=sha256,
                cursor=cursorForSeq(0),
            )

    # Write blob first (outside transaction)
    blobFile = f"blobs/{sha256[:2]}/{sha256}"
    blobs.store(body)

    now = utcNowIso()
    revisionId = f"rev-{ulid()}"
    parentRev = headRev if headRev else None

    # Transactional: insert revision, update file, create event
    try:
        db.createRevision(
            revisionId=revisionId,
            projectId=projectId,
            path=path,
            parentRev=parentRev,
            sha256=sha256,
            size=size,
            actorId=xActor or "",
            deviceId=xDevice or "",
            at=now,
            blobFile=blobFile,
        )
        db.upsertFile(projectId, path, revisionId, 0)
        db.createEvent(
            projectId=projectId,
            at=now,
            op="put",
            path=path,
            rev=revisionId,
            actorId=xActor,
            deviceId=xDevice,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Get the event seq for cursor
    eventSeq = db.countEvents(projectId)
    # Actually we need the seq of the event we just inserted.
    # Use lastrowid from the event insert.
    # Re-query to be safe:
    cur = db.connection.execute(
        "SELECT seq FROM event WHERE projectId = ? ORDER BY seq DESC LIMIT 1",
        (projectId,),
    )
    row = cur.fetchone()
    lastSeq = row["seq"] if row else 0

    return FilePutResponse(
        rev=revisionId,
        sha256=sha256,
        cursor=cursorForSeq(lastSeq),
    )


@app.get("/v1/projects/{projectId}/files/{path:path}")
def getFile(
    projectId: str = PathParam(...),
    path: str = PathParam(...),
    rev: str | None = Query(default=None, description="Revision ID"),
    _auth: None = Depends(verifyAuth),
) -> Response:
    db = getDb()
    blobs = getBlobs()

    project = db.getProject(projectId)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"Project {projectId} not found",
                    details=None,
                )
            ).model_dump(),
        )

    revision: Any = None
    if rev is not None:
        revision = db.getRevision(rev)
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="notFound",
                        message=f"Revision {rev} not found",
                        details=None,
                    )
                ).model_dump(),
            )
    else:
        fileRow = db.getFile(projectId, path)
        if fileRow is None or fileRow["headRev"] is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="notFound",
                        message=f"File {path} not found in project {projectId}",
                        details=None,
                    )
                ).model_dump(),
            )
        revision = db.getRevision(fileRow["headRev"])
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="notFound",
                        message="Head revision not found",
                        details=None,
                    )
                ).model_dump(),
            )

    blobData = blobs.retrieve(revision["sha256"])
    if blobData is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="internal",
                    message="Blob not found",
                    details=None,
                )
            ).model_dump(),
        )

    return Response(
        content=blobData,
        media_type="application/octet-stream",
        headers={"X-Revision": revision["id"], "X-SHA-256": revision["sha256"]},
    )


@app.delete("/v1/projects/{projectId}/files/{path:path}")
def deleteFile(
    projectId: str = PathParam(...),
    path: str = PathParam(...),
    ifMatch: str | None = Header(default=None, alias="If-Match"),
    xDevice: str | None = Header(default=None, alias="X-Device"),
    xActor: str | None = Header(default=None, alias="X-Actor"),
    _auth: None = Depends(verifyAuth),
) -> Response:
    db = getDb()

    project = db.getProject(projectId)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"Project {projectId} not found",
                    details=None,
                )
            ).model_dump(),
        )

    fileRow = db.getFile(projectId, path)
    if fileRow is None or fileRow["headRev"] is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"File {path} not found in project {projectId}",
                    details=None,
                )
            ).model_dump(),
        )

    # If-Match check
    if ifMatch is not None:
        matchRev = ifMatch.strip('"')
        if matchRev != fileRow["headRev"]:
            headSha = None
            headRevRow = db.getRevision(fileRow["headRev"])
            if headRevRow is not None:
                headSha = headRevRow["sha256"]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorResponse(
                    error=ErrorDetail(
                        code="headMoved",
                        message="Head revision has moved",
                        details={
                            "headRev": fileRow["headRev"],
                            "headSha256": headSha,
                        },
                    )
                ).model_dump(),
            )

    now = utcNowIso()
    db.upsertFile(projectId, path, None, 1)
    db.createEvent(
        projectId=projectId,
        at=now,
        op="delete",
        path=path,
        rev=None,
        actorId=xActor,
        deviceId=xDevice,
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/v1/projects/{projectId}/changes", response_model=ChangesResponse)
def getChanges(
    projectId: str = PathParam(...),
    since: str | None = Query(default=None, description="Cursor (ev-<seq>)"),
    limit: int = Query(default=200, ge=1, le=1000),
    _auth: None = Depends(verifyAuth),
) -> ChangesResponse:
    db = getDb()

    project = db.getProject(projectId)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"Project {projectId} not found",
                    details=None,
                )
            ).model_dump(),
        )

    sinceSeq = seqFromCursor(since)
    rows = db.listChanges(projectId, sinceSeq, limit)

    items: list[ChangeItem] = []
    lastSeq = 0
    for row in rows:
        lastSeq = row["seq"]
        # Get SHA-256 for put operations
        sha256 = None
        if row["op"] == "put" and row["rev"] is not None:
            revRow = db.getRevision(row["rev"])
            if revRow is not None:
                sha256 = revRow["sha256"]
        items.append(
            ChangeItem(
                seq=row["seq"],
                at=row["at"],
                op=row["op"],
                path=row["path"],
                rev=row["rev"],
                sha256=sha256,
                deviceId=row["deviceId"],
                actorId=row["actorId"],
            )
        )

    nextCursor: str | None = None
    if items:
        nextCursor = cursorForSeq(lastSeq)

    return ChangesResponse(items=items, next=nextCursor)


@app.get("/v1/projects/{projectId}/revisions")
def getRevisions(
    projectId: str = PathParam(...),
    path: str = Query(..., description="File path"),
    _auth: None = Depends(verifyAuth),
) -> list[dict[str, Any]]:
    db = getDb()

    project = db.getProject(projectId)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorDetail(
                    code="notFound",
                    message=f"Project {projectId} not found",
                    details=None,
                )
            ).model_dump(),
        )

    revisions = db.listRevisions(projectId, path)
    return [
        {
            "id": row["id"],
            "parentRev": row["parentRev"],
            "sha256": row["sha256"],
            "size": row["size"],
            "actorId": row["actorId"],
            "deviceId": row["deviceId"],
            "at": row["at"],
        }
        for row in revisions
    ]
