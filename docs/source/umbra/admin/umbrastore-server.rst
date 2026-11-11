.. _umbra-admin-umbrastore-server:

Umbrastore Server
=================

Umbrastore is a self-hosted revision store server for UmbraEdit projects.
It stores document revisions, project files, and sidecar metadata in a
content-addressed store, and exposes them through a REST API for sync
clients. No network access is performed by the server itself; it is
entirely local and self-contained.

Overview
--------

Umbrastore is a separate Python package (``umbrastore``) that runs as a
standalone HTTP server. It is designed to be deployed on a private
network or on the same machine as UmbraEdit. The server stores:

- **Accounts** — named identities with bearer tokens for authentication.
- **Projects** — named collections of files and revisions.
- **Files** — individual project files (documents, project XML, sidecars).
- **Revisions** — immutable, content-addressed snapshots of files.
- **Events** — an append-only log of all changes for change feeds.

Data Layout
-----------

The server stores all data under a single data directory:

```
<data-dir>/
  umbrastore.db          # SQLite database (WAL mode, synchronous=FULL)
  blobs/
    <sha256[0:2]>/
      <sha256>           # Content-addressed blob storage
```

Install
-------

Umbrastore is installed as a separate Python package::

    pip install umbrastore

First Run
---------

1. Create a data directory::

       mkdir -p /var/lib/umbrastore

2. Create an account (the token is printed once and is never shown again)::

       umbrastore add-account --data /var/lib/umbrastore --name alice

3. Start the server::

       umbrastore serve --data /var/lib/umbrastore --host 127.0.0.1 --port 47400

Accounts and Tokens
-------------------

Accounts are created with ``umbrastore add-account``. The token is printed
to stdout and must be saved by the administrator; it cannot be recovered
later. Tokens are stored hashed (SHA-256 with random salt) in the database.

Clients authenticate by sending ``Authorization: Bearer <token>`` with
every request.

TLS
---

The server should only bind to loopback addresses (``127.0.0.1``,
``localhost``) unless TLS is configured. To bind to a non-loopback host
without TLS, pass ``--allow-insecure`` (not recommended for production).

With TLS::

       umbrastore serve --data /var/lib/umbrastore --host 0.0.0.0 --port 47400 \
           --cert /etc/ssl/cert.pem --key /etc/ssl/key.pem

Backup and Verify
-----------------

Backup the entire data directory as a zip file::

       umbrastore backup --data /var/lib/umbrastore --output /backup/umbrastore-$(date +%F).zip

Verify that all blobs match their recorded SHA-256::

       umbrastore verify --data /var/lib/umbrastore

Upgrade
-------

Stop the server, back up the data directory, install the new version, and
restart. The database schema is versioned; migrations are applied
automatically on startup.

Systemd Unit Example
--------------------

::

       [Unit]
       Description=UmbraStore Server
       After=network.target

       [Service]
       Type=simple
       ExecStart=/usr/local/bin/umbrastore serve --data /var/lib/umbrastore --host 127.0.0.1 --port 47400
       Restart=on-failure
       User=umbrastore
       Group=umbrastore

       [Install]
       WantedBy=multi-user.target

API Reference
-------------

All endpoints require ``Authorization: Bearer <token>``.

``GET /v1/health``
    Returns ``{"ok": true, "version": "..."}``.

``POST /v1/projects``
    Body: ``{"name": "..."}``. Returns ``{"id": "..."}``.

``PUT /v1/projects/{p}/files/{path}``
    Stores a file revision. Headers: ``If-Match``, ``X-Device``,
    ``X-Actor``. Body: file bytes. Returns ``{"rev", "sha256", "cursor"}``.
    On conflict: ``409 {"error": {"code": "headMoved", ...}}``.

``GET /v1/projects/{p}/files/{path}?rev=``
    Returns file bytes. Headers: ``X-Revision``, ``X-SHA-256``.

``DELETE /v1/projects/{p}/files/{path}``
    Marks a file deleted. Headers: ``If-Match``.

``GET /v1/projects/{p}/changes?since=<cursor>&limit=200``
    Returns ``{"items": [...], "next": "ev-<12 digits>"}``.

``GET /v1/projects/{p}/revisions?path=``
    Returns revision history for a path.

Error Body
~~~~~~~~~~

::

    {"error": {"code": "...", "message": "...", "details": {...}}}

Codes: ``unauthorized``, ``notFound``, ``headMoved``, ``invalidRequest``,
``internal``.

Troubleshooting
---------------

- **401 Unauthorized**: Check that the bearer token is correct and has
  not been revoked.
- **409 headMoved**: The file's head revision has changed since the
  client last read it. Retry with the new head revision.
- **Blob verification fails**: A blob file has been corrupted or deleted.
  Restore from backup.

.. umbra-owner:: P16
