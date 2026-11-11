"""
UmbraEdit - Local HTTP API
==========================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""  # noqa

from __future__ import annotations

import hashlib
import json
import logging

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_ERROR = 1

logger = logging.getLogger(__name__)

API_VERSION = "v1"
DEFAULT_PORT = 47321
TOKEN_FILE = Path.home() / ".umbraedit" / "api-token"


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_token() -> str | None:
    """Load the bearer token from the token file."""
    if not TOKEN_FILE.is_file():
        return None
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        return token or None
    except Exception:
        return None


def _check_token(headers: dict[str, str]) -> tuple[bool, dict[str, Any] | None]:
    """Check the bearer token from request headers.

    Returns (authorized, error_response).
    """
    token = _load_token()
    if token is None:
        # No token configured - allow all (dev mode)
        return True, None

    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False, {
            "error": {
                "code": "unauthorized",
                "message": "Missing or invalid Authorization header",
                "details": {},
            }
        }

    provided = auth[7:].strip()
    if provided != token:
        return False, {
            "error": {
                "code": "unauthorized",
                "message": "Invalid bearer token",
                "details": {},
            }
        }

    return True, None


def _json_response(handler: BaseHTTPRequestHandler, code: int, data: Any) -> None:
    """Send a JSON response."""
    body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    encoded = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _error_response(
    handler: BaseHTTPRequestHandler,
    code: int,
    error_code: str,
    message: str,
    details: dict | None = None,
) -> None:
    """Send an error response."""
    _json_response(
        handler,
        code,
        {
            "error": {
                "code": error_code,
                "message": message,
                "details": details or {},
            }
        },
    )


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    """Read the request body."""
    length = int(headers_get(handler, "Content-Length", 0))
    if length > 0:
        return handler.rfile.read(length)
    return b""


def headers_get(handler: BaseHTTPRequestHandler, key: str, default: Any = None) -> Any:
    """Get a header value case-insensitively."""
    for k, v in handler.headers.items():
        if k.lower() == key.lower():
            return v
    return default


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local API."""

    def __init__(self, *args: Any, project: Any = None, **kwargs: Any) -> None:
        self._project = project
        super().__init__(*args, **kwargs)

    def log_message(self, format_string: str, *args: Any) -> None:
        """Suppress default logging."""
        logger.debug("%s - %s", self.address_string(), format_string % args)

    def _check_auth(self) -> bool:
        """Check authentication. Returns True if authorized, sends error response if not."""
        authorized, error = _check_token(dict(self.headers))
        if not authorized:
            assert error is not None
            _error_response(self, 401, error["error"]["code"], error["error"]["message"], error["error"]["details"])
            return False
        return True

    def _get_path_parts(self) -> list[str]:
        """Get path parts."""
        path = self.path.split("?")[0]
        return [p for p in path.split("/") if p]

    def _query_param(self, name: str) -> str | None:
        """Get a query parameter."""
        if "?" not in self.path:
            return None
        query = self.path.split("?", 1)[1]
        for param in query.split("&"):
            if "=" in param:
                k, v = param.split("=", 1)
                if k == name:
                    return v
        return None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if not self._check_auth():
            return

        parts = self._get_path_parts()

        if len(parts) >= 2 and parts[0] == "v1":
            if parts[1] == "documents" and len(parts) == 2:
                self._get_documents()
            elif parts[1] == "documents" and len(parts) == 3:
                self._get_document(parts[2])
            elif parts[1] == "characters" and len(parts) == 2:
                self._get_characters()
            elif parts[1] == "utterances" and len(parts) == 2:
                self._get_utterances()
            elif parts[1] == "gates" and len(parts) == 2:
                self._get_gates()
            elif parts[1] == "changes" and len(parts) == 2:
                self._get_changes()
            else:
                _error_response(self, 404, "notFound", "Route not found")
        else:
            _error_response(self, 404, "notFound", "Route not found")

    def do_PUT(self) -> None:
        """Handle PUT requests."""
        if not self._check_auth():
            return

        parts = self._get_path_parts()

        if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "documents":
            self._put_document(parts[2])
        elif len(parts) >= 3 and parts[0] == "v1" and parts[1] == "paragraphs" and parts[2] == "meta":
            self._put_paragraphs_meta()
        else:
            _error_response(self, 404, "notFound", "Route not found")

    def do_POST(self) -> None:
        """Handle POST requests."""
        if not self._check_auth():
            return

        parts = self._get_path_parts()

        if len(parts) >= 4 and parts[0] == "v1" and parts[1] == "characters" and parts[3] == "aliases":
            self._post_character_aliases(parts[2])
        else:
            _error_response(self, 404, "notFound", "Route not found")

    # --- Route handlers ---

    def _get_documents(self) -> None:
        """GET /v1/documents - list all documents."""
        try:
            docs = [
                {
                    "handle": item.itemHandle,
                    "name": item.itemName,
                    "class": str(item.itemClass),
                }
                for item in self._project.tree
                if item.isFileType()
            ]
            _json_response(self, 200, {"documents": docs})
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _get_document(self, handle: str) -> None:
        """GET /v1/documents/{handle} - get document content."""
        try:
            doc_file = self._project.storage.contentPath / f"{handle}.md"
            if not doc_file.is_file():
                _error_response(self, 404, "notFound", f"Document {handle} not found")
                return

            text = doc_file.read_text(encoding="utf-8")
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

            _json_response(
                self,
                200,
                {
                    "handle": handle,
                    "text": text,
                    "sha256": sha,
                },
            )
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _put_document(self, handle: str) -> None:
        """PUT /v1/documents/{handle} - update document content."""
        try:
            body = _read_body(self)
            data = json.loads(body)

            if_match = headers_get(self, "If-Match")
            if if_match:
                doc_file = self._project.storage.contentPath / f"{handle}.md"
                if doc_file.is_file():
                    current_text = doc_file.read_text(encoding="utf-8")
                    current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                    if if_match.strip('"') != current_sha:
                        _error_response(self, 409, "docChanged", "Document has been modified", {"handle": handle})
                        return

            text = data.get("text", "")
            doc_file = self._project.storage.contentPath / f"{handle}.md"
            doc_file.write_text(text, encoding="utf-8", newline="\n")

            # Create history snapshot
            from umbraedit.umbra.history import HistoryManager

            mgr = HistoryManager(self._project.storage.storagePath, self._project)
            mgr.snapshot(handle, "manual", f"CLI PUT {handle}")

            _json_response(
                self,
                200,
                {
                    "handle": handle,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            )
        except json.JSONDecodeError:
            _error_response(self, 422, "invalidRequest", "Invalid JSON body")
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _get_characters(self) -> None:
        """GET /v1/characters - list all characters."""
        try:
            sheet = self._project.index
            chars = [
                {
                    "tag": entity.tag,
                    "name": entity.tag,
                    "kind": entity.kind,
                }
                for entity in sheet.iterEntities()
                if entity.kind == "character"
            ]
            _json_response(self, 200, {"characters": chars})
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _post_character_aliases(self, tag: str) -> None:
        """POST /v1/characters/{tag}/aliases - add alias."""
        try:
            body = _read_body(self)
            data = json.loads(body)
            alias = data.get("alias", "")

            sheet = self._project.index
            entity = sheet.getEntity(tag)
            if not entity:
                _error_response(self, 404, "notFound", f"Character {tag} not found")
                return

            aliases = list(entity.aliases)
            if alias not in aliases:
                aliases.append(alias)
                entity.aliases = aliases
                sheet.saveSheet()

            _json_response(self, 200, {"tag": tag, "aliases": aliases})
        except json.JSONDecodeError:
            _error_response(self, 422, "invalidRequest", "Invalid JSON body")
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _put_paragraphs_meta(self) -> None:
        """PUT /v1/paragraphs/meta - update paragraph metadata."""
        try:
            body = _read_body(self)
            data = json.loads(body)

            if_match = headers_get(self, "If-Match")
            handle = data.get("handle", "")
            para = data.get("para", 0)

            if if_match:
                doc_file = self._project.storage.contentPath / f"{handle}.md"
                if doc_file.is_file():
                    current_text = doc_file.read_text(encoding="utf-8")
                    current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                    if if_match.strip('"') != current_sha:
                        _error_response(self, 409, "docChanged", "Document has been modified", {"handle": handle})
                        return

            # Apply voice/tone metadata to paragraph
            # This uses the same functions as the GUI
            from umbraedit.umbra.units import UnitKind, iterUnits

            doc_file = self._project.storage.contentPath / f"{handle}.md"
            text = doc_file.read_text(encoding="utf-8")

            units = list(iterUnits(text))
            para_index = 0
            modified = False
            new_lines = []

            for unit in units:
                if unit.kind == UnitKind.PARAGRAPH and para_index == para:
                    # Update voice metadata
                    spk = data.get("spk", "")
                    tone = data.get("tone", "")
                    tone_i = data.get("toneI", 2)
                    lang = data.get("lang", "")

                    # Rebuild the paragraph with voice info
                    new_unit_lines = []
                    for line in unit.lines:
                        if line.strip().startswith("%Voice:"):
                            # Replace existing voice line
                            new_unit_lines.append(f"%Voice: spk={spk} tone={tone}:{tone_i} lang={lang}")
                        else:
                            new_unit_lines.append(line)
                    if not any(ln.strip().startswith("%Voice:") for ln in unit.lines):
                        # Add voice line at start
                        new_unit_lines.insert(0, f"%Voice: spk={spk} tone={tone}:{tone_i} lang={lang}")

                    new_lines.extend(new_unit_lines)
                    modified = True
                else:
                    new_lines.extend(unit.lines)
                para_index += 1  # noqa: SIM113 - only counts paragraph units, not all units

            if modified:
                doc_file.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")

                # Create history snapshot
                from umbraedit.umbra.history import HistoryManager

                mgr = HistoryManager(self._project.storage.storagePath, self._project)
                mgr.snapshot(handle, "meta", f"CLI paragraph meta {handle} para {para}")

            _json_response(
                self,
                200,
                {
                    "handle": handle,
                    "para": para,
                    "updated": modified,
                },
            )
        except json.JSONDecodeError:
            _error_response(self, 422, "invalidRequest", "Invalid JSON body")
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _get_utterances(self) -> None:
        """GET /v1/utterances?handle= - get utterances for a document."""
        try:
            handle = self._query_param("handle")
            if not handle:
                _error_response(self, 422, "invalidRequest", "Missing handle parameter")
                return

            from umbraedit.umbra.utterances import deriveUtterances

            doc_file = self._project.storage.contentPath / f"{handle}.md"
            if not doc_file.is_file():
                _error_response(self, 404, "notFound", f"Document {handle} not found")
                return

            text = doc_file.read_text(encoding="utf-8")
            utts = deriveUtterances(handle=handle, text=text, project=self._project)

            result = [
                {
                    "id": u.id,
                    "handle": u.handle,
                    "para": u.para,
                    "kind": u.kind,
                    "speaker": u.speaker,
                    "text": u.text,
                    "tone": u.tone,
                    "toneI": u.toneI,
                    "lang": u.lang,
                    "skip": u.skip,
                    "attribution": u.attribution,
                    "voice": u.voice,
                }
                for u in utts
            ]

            _json_response(self, 200, {"utterances": result})
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _get_gates(self) -> None:
        """GET /v1/gates?operation= - run gate checks."""
        try:
            operation = self._query_param("operation")
            if not operation:
                _error_response(self, 422, "invalidRequest", "Missing operation parameter")
                return

            from umbraedit.umbra.gates import GateScope, reportToJson, runGates

            scope = GateScope(
                project=self._project,
                edition="",
                options={},
            )
            report = runGates(operation, scope)
            _json_response(self, 200, reportToJson(report))
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))

    def _get_changes(self) -> None:
        """GET /v1/changes?since= - get changes since a timestamp."""
        try:
            since = self._query_param("since")
            from umbraedit.umbra.outbox import Outbox

            device_id, actor_id = "", ""
            Outbox(self._project.storage.storagePath, device_id, actor_id)

            # This is a simplified implementation
            changes = []
            _json_response(self, 200, {"changes": changes, "since": since})
        except Exception as exc:
            _error_response(self, 500, "internalError", str(exc))


def create_server(project: Any, port: int = DEFAULT_PORT) -> HTTPServer:
    """Create an HTTP server for the local API.

    Binds to loopback only (127.0.0.1).
    """

    class Handler(APIHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, project=project, **kwargs)

    return HTTPServer(("127.0.0.1", port), Handler)


def serve(project: Any, port: int = DEFAULT_PORT) -> None:
    """Start the local API server."""
    server = create_server(project, port)
    logger.info("Local API server listening on 127.0.0.1:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_serve(args: Any) -> int:
    """CLI handler for the serve command."""
    project_path = Path(args.project)
    if not project_path.is_dir():
        print(f"Error: project path not found: {project_path}", flush=True)
        return EXIT_ERROR

    from umbraedit.core.project import NWProject

    project = NWProject()
    if not project.openProject(str(project_path)):
        print(f"Error: cannot open project '{project_path}'", flush=True)
        return EXIT_ERROR

    port = args.port or DEFAULT_PORT
    serve(project, port)
    return EXIT_OK
