"""
UmbraStore - Command line interface
===================================

CLI commands: serve, add-account, backup, verify.
"""  # noqa

from __future__ import annotations

import argparse
import os
import sys
import zipfile

from pathlib import Path

import uvicorn

from umbrastore import __version__
from umbrastore.auth import generateToken, hashToken
from umbrastore.database import connect, initDatabase, utcNow
from umbrastore.server import app


def cmdServe(args: argparse.Namespace) -> int:
    """Start the UmbraStore HTTP server."""
    dataDir = Path(args.data)
    host = args.host
    port = args.port

    # TLS check
    if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        if args.cert is None or args.key is None:
            if not args.allow_insecure:
                print(
                    "Error: Binding to a non-loopback host requires TLS (--cert and --key) or --allow-insecure",
                    file=sys.stderr,
                )
                return 1
            print(
                "Warning: Binding to non-loopback host without TLS",
                file=sys.stderr,
            )

    # Set environment for the server module
    os.environ["UMBRASTORE_DATA_DIR"] = str(dataDir)

    initDatabase(dataDir)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


def cmdAddAccount(args: argparse.Namespace) -> int:
    """Create a new account and print the token once."""
    dataDir = Path(args.data)
    initDatabase(dataDir)
    conn = connect(dataDir)

    name = args.name
    from umbrastore.database import Database

    db = Database(conn)

    from umbrastore.database import ulid

    accountId = ulid()
    token = generateToken()
    tokenHash = hashToken(token)
    createdAt = utcNow()

    db.createAccount(accountId, name, tokenHash, createdAt)
    db.commit()
    db.close()

    print(token)
    return 0


def cmdBackup(args: argparse.Namespace) -> int:
    """Backup the database and blobs to a zip file."""
    dataDir = Path(args.data)
    outputFile = Path(args.output)

    if not dataDir.is_dir():
        print(f"Error: Data directory {dataDir} does not exist", file=sys.stderr)
        return 1

    dbPath = dataDir / "umbrastore.db"
    blobsDir = dataDir / "blobs"

    outputFile.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(str(outputFile), "w", zipfile.ZIP_DEFLATED) as zf:
        # Add database
        if dbPath.is_file():
            zf.write(str(dbPath), arcname="umbrastore.db")
        # Add blobs
        if blobsDir.is_dir():
            for root, _dirs, files in os.walk(blobsDir):
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = str(fpath.relative_to(dataDir))
                    zf.write(str(fpath), arcname=arcname)

    print(f"Backup written to {outputFile}")
    return 0


def cmdVerify(args: argparse.Namespace) -> int:
    """Verify every blob's SHA-256 against its row in the database."""
    dataDir = Path(args.data)
    initDatabase(dataDir)
    conn = connect(dataDir)

    from umbrastore.database import Database

    db = Database(conn)

    blobsDir = dataDir / "blobs"
    mismatches = db.verifyBlobs(blobsDir)

    if mismatches:
        print(f"Verification FAILED: {len(mismatches)} blob(s) corrupted or missing:")
        for revId, expectedSha in mismatches:
            print(f"  {revId}: expected {expectedSha}")
        db.close()
        return 1

    total = db.connection.execute("SELECT COUNT(*) AS c FROM revision").fetchone()["c"]
    print(f"Verification OK: {total} blob(s) verified")
    db.close()
    return 0


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="umbrastore",
        description="UmbraStore - Self-hosted revision store server",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    pServe = sub.add_parser("serve", help="Start the HTTP server")
    pServe.add_argument("--data", required=True, help="Data directory")
    pServe.add_argument("--host", default="127.0.0.1", help="Bind host")
    pServe.add_argument("--port", type=int, default=47400, help="Bind port")
    pServe.add_argument("--cert", help="TLS certificate file")
    pServe.add_argument("--key", help="TLS private key file")
    pServe.add_argument(
        "--allow-insecure",
        action="store_true",
        help="Allow binding to non-loopback without TLS",
    )
    pServe.set_defaults(func=cmdServe)

    # add-account
    pAcct = sub.add_parser("add-account", help="Create a new account")
    pAcct.add_argument("--data", required=True, help="Data directory")
    pAcct.add_argument("--name", required=True, help="Account name")
    pAcct.set_defaults(func=cmdAddAccount)

    # backup
    pBackup = sub.add_parser("backup", help="Backup data to a zip file")
    pBackup.add_argument("--data", required=True, help="Data directory")
    pBackup.add_argument("--output", required=True, help="Output zip file")
    pBackup.set_defaults(func=cmdBackup)

    # verify
    pVerify = sub.add_parser("verify", help="Verify all blobs")
    pVerify.add_argument("--data", required=True, help="Data directory")
    pVerify.set_defaults(func=cmdVerify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = buildParser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
