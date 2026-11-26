"""
UmbraEdit - Flatpak Build
===========================

This file is a part of UmbraEdit.

Copyright (C) 2025 Veronica Berglyd Olsen and UmbraEdit contributors.

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

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.common import (
    ROOT_DIR,
    appdataXml,
    extractBuildInfo,
    extractVersion,
    log,
    makeCheckSum,
    readFile,
    toUpload,
    updateMetaFile,
    writeFile,
)

PIP_GEN_COMMIT = "737c0085912f9f7dabf9341d4608e2a77a51a73a"
PIP_GEN_FILE = "pip/flatpak-pip-generator.py"
PIP_GEN_URL = f"https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/{PIP_GEN_COMMIT}/{PIP_GEN_FILE}"
FLATPAK_SDK = "org.kde.Sdk"
# Packages that cannot be built from source in the Flatpak sandbox are
# installed from a prebuilt wheel instead. The wheel must match the Python
# version and the architecture of the Flatpak runtime. The rpds-py package
# needs a Rust toolchain, and the pillow package needs the pybind11 module,
# neither of which are available in the sandbox.
PREFER_WHEELS = ("pillow", "rpds-py")
ENCHANT_RELEASE_API = "https://api.github.com/repos/rrthomas/enchant/releases/tags/v{version}"
NW_REPO_URL = "https://github.com/bdmurphy73/UmbraEdit.git"
NW_COMMIT_API = "https://api.github.com/repos/bdmurphy73/UmbraEdit/commits/v{version}"
FLATHUB_FILES = ("io.umbraedit.umbraedit.yml", "pypi-deps.json", "enchant.json", "umbraedit.appdata.xml")


def enchantChecksum(fileName: str, url: str, version: str) -> str:
    """Return the SHA256 checksum of an enchant release asset.

    The checksum is looked up in the release metadata on the GitHub API
    first, as that is the value published by the project. If the API
    cannot be reached, which happens when the rate limit for anonymous
    requests is exceeded, the asset is downloaded and the checksum is
    computed from it instead.
    """
    apiUrl = ENCHANT_RELEASE_API.format(version=version)
    log(f"Checking: {apiUrl}")
    try:
        with urllib.request.urlopen(apiUrl) as response:
            release = json.loads(response.read())
        assets = {a["name"]: a for a in release["assets"]}
        if fileName not in assets:
            raise ValueError(f"Asset '{fileName}' not found in release 'v{version}'")
        return str(assets[fileName]["digest"]).removeprefix("sha256:")
    except Exception as exc:
        log(f"[wr]Could not read the release metadata: {exc}[e]")
        log("Downloading the asset to compute the checksum instead ...")
        log("")

    with urllib.request.urlopen(url) as response:
        return hashlib.sha256(response.read()).hexdigest()


def processEnchant(bldDir: Path, enchantVersion: str) -> None:
    """Generate the enchant.json flatpak module for the pinned enchant version."""
    log("")
    log("[b]Generate Enchant Module[e]")
    log("[b]=======================[e]")
    log("")

    outFile = bldDir / "enchant.json"

    try:
        fileName = f"enchant-{enchantVersion}.tar.gz"
        url = f"https://github.com/rrthomas/enchant/releases/download/v{enchantVersion}/{fileName}"

        checksum = enchantChecksum(fileName, url, enchantVersion)

        log(f"Version: {enchantVersion}")
        log(f"SHA256: {checksum}")

        module = {
            "name": "enchant",
            "buildsystem": "autotools",
            "post-install": [
                "install -Dm644 -T COPYING.LIB ${FLATPAK_DEST}/share/licenses/${FLATPAK_ID}/enchant-COPYING.LIB",
            ],
            "sources": [
                {
                    "type": "archive",
                    "url": url,
                    "sha256": checksum,
                },
            ],
        }
        writeFile(outFile, json.dumps(module, indent=4) + "\n")
    except Exception as exc:
        log("[cr]Generate Enchant Module: FAILED[e]")
        log("")
        log(exc)
        sys.exit(1)

    log("")


def flatpakSdkRef(qtVersion: str) -> str:
    """Return the Flatpak SDK reference for a given runtime version.

    The SDK branch is the same as the runtime branch, as the SDK version
    defaults to the runtime version in the Flatpak manifest.
    """
    return f"{FLATPAK_SDK}//{qtVersion}"


def installFlatpakSdk(sdkRef: str) -> None:
    """Install the Flatpak SDK if it isn't already installed.

    The dependency generator needs the SDK to determine which prebuilt
    wheels are compatible with the Flatpak runtime.
    """
    check = subprocess.run(["flatpak", "info", "--user", sdkRef], check=False, capture_output=True)
    if check.returncode == 0:
        return

    log(f"Installing: {sdkRef}")
    log("")
    try:
        subprocess.run(["flatpak", "install", "--user", "-y", "flathub", sdkRef], check=True)
    except subprocess.CalledProcessError:
        log("[cr]ERROR:[e] Could not install the Flatpak SDK")
        log("")
        log(f"Run: flatpak install --user -y flathub {sdkRef}")
        log("")
        sys.exit(1)
    log("")


def processDependencies(bldDir: Path, sdkRef: str) -> None:
    """Generate the pypi-deps.json file."""
    log("")
    log("[b]Generate PyPI Dependencies[e]")
    log("[b]==========================[e]")
    log("")

    genScript = bldDir / "flatpak-pip-generator.py"
    outFile = bldDir / "pypi-deps"

    try:
        if not genScript.exists():
            log(f"Downloading: {PIP_GEN_URL}")
            urllib.request.urlretrieve(PIP_GEN_URL, genScript)

        log("")
        subprocess.run(
            [
                "uv",
                "run",
                str(genScript),
                "--pyproject-file",
                str(ROOT_DIR / "pyproject.toml"),
                "--ignore-pkg",
                "pyqt6",
                "--runtime",
                sdkRef,
                "--prefer-wheels",
                ",".join(PREFER_WHEELS),
                "-o",
                str(outFile),
            ],
            check=True,
        )
    except Exception as exc:
        log("[cr]Generate PyPI Dependencies: FAILED[e]")
        log("")
        log(exc)
        sys.exit(1)
    finally:
        genScript.unlink(missing_ok=True)

    log("")


def flatpak(args: argparse.Namespace) -> None:
    """Build a flatpak bundle locally, for direct download."""
    log("")
    log("[b]Build Flatpak[e]")
    log("[b]=============[e]")
    log("")

    buildInfo = extractBuildInfo("flatpak")
    qtVersion = buildInfo["qt_version"]
    enchantVersion = buildInfo["enchant_version"]

    pkgVers, _, relDate = extractVersion()
    relDate = datetime.datetime.strptime(relDate, "%Y-%m-%d")

    bldDir = ROOT_DIR / "dist_flatpak"
    bldPkg = f"umbraedit_{pkgVers}"
    outDir = bldDir / bldPkg

    # Set Up Folders
    # ==============

    if outDir.exists():
        log("[b]Removing old build files ...[e]")
        log("")
        shutil.rmtree(outDir)

    bldDir.mkdir(exist_ok=True)
    outDir.mkdir(exist_ok=True)

    sdkRef = flatpakSdkRef(qtVersion)
    installFlatpakSdk(sdkRef)
    processDependencies(bldDir, sdkRef)
    processEnchant(bldDir, enchantVersion)
    writeFile(bldDir / "umbraedit.appdata.xml", appdataXml())
    updateMetaFile(bldDir / "meta.toml", buildFormat="flatpak", installSource="github")

    template = readFile(ROOT_DIR / "setup" / "flatpak" / "io.umbraedit.umbraedit.yml")
    template = template.replace("@QT_VERSION@", qtVersion)
    template = template.replace("@FILESYSTEM_PERMISSION@", "home")
    manifestFile = bldDir / "io.umbraedit.umbraedit.yml"
    writeFile(manifestFile, template)

    # Build flatpak
    # ==============

    manifestPath = str(manifestFile)
    bundleFile = bldDir / f"umbraedit-{pkgVers}-linux.flatpak"

    try:
        subprocess.run(
            [
                "flatpak-builder",
                "--user",
                f"--repo={outDir}/repo",
                "--install-deps-from=flathub",
                "--force-clean",
                outDir,
                manifestPath,
            ],
            check=True,
        )
        subprocess.run(
            [
                "flatpak",
                "build-bundle",
                f"{outDir}/repo",
                bundleFile,
                "io.umbraedit.umbraedit",
            ],
            check=True,
        )
    except Exception as exc:
        log("[cr]Flatpak build: FAILED[e]")
        log("")
        log(exc)
        log("")
        log("[b]Dependencies:[e]")
        log(" * flatpak flatpak-builder")
        log("")
        sys.exit(1)

    shaFile = makeCheckSum(bundleFile.name, cwd=bldDir)

    toUpload(bundleFile)
    toUpload(shaFile)


def flathub(args: argparse.Namespace) -> None:
    """Generate the manifest and support files for a Flathub submission."""
    # Import here so we can still run pkgutils with plain python
    import yaml

    log("")
    log("[b]Build Flathub Submission[e]")
    log("[b]========================[e]")
    log("")

    buildInfo = extractBuildInfo("flatpak")
    qtVersion = buildInfo["qt_version"]
    enchantVersion = buildInfo["enchant_version"]

    pkgVers, _, _ = extractVersion()
    tag = f"v{pkgVers}"

    bldDir = ROOT_DIR / "dist_flathub"
    bldDir.mkdir(exist_ok=True)

    sdkRef = flatpakSdkRef(qtVersion)
    installFlatpakSdk(sdkRef)
    processDependencies(bldDir, sdkRef)
    processEnchant(bldDir, enchantVersion)
    writeFile(bldDir / "umbraedit.appdata.xml", appdataXml())

    log("[b]Resolve Release Commit[e]")
    log("[b]======================[e]")
    log("")

    commitApiUrl = NW_COMMIT_API.format(version=pkgVers)
    try:
        log(f"Checking: {commitApiUrl}")
        with urllib.request.urlopen(commitApiUrl) as response:
            commit = json.loads(response.read())["sha"]
        log(f"Tag: {tag}")
        log(f"Commit: {commit}")
    except Exception as exc:
        log("[cr]Resolve Release Commit: FAILED[e]")
        log("")
        log(exc)
        log("")
        log(f"[cy]Has version {pkgVers} been tagged and pushed to GitHub yet?[e]")
        log("")
        sys.exit(1)

    log("")

    manifest = yaml.safe_load(readFile(ROOT_DIR / "setup" / "flatpak" / "io.umbraedit.umbraedit.yml"))
    manifest["runtime-version"] = qtVersion
    manifest["base-version"] = qtVersion
    manifest["finish-args"] = [
        "--filesystem=xdg-documents" if a.startswith("--filesystem=") else a for a in manifest["finish-args"]
    ]
    for module in manifest["modules"]:
        if isinstance(module, dict) and module.get("name") == "UmbraEdit":
            module["sources"] = [
                {"type": "git", "url": NW_REPO_URL, "tag": tag, "commit": commit},
                {"type": "file", "path": "umbraedit.appdata.xml"},
            ]
            break

    manifestFile = bldDir / "io.umbraedit.umbraedit.yml"
    with open(manifestFile, mode="w", encoding="utf-8") as outFile:
        yaml.safe_dump(manifest, outFile, sort_keys=False)
    log(f"[cg]Wrote:[e] {manifestFile.relative_to(ROOT_DIR)}")
    log("")

    if path := args.path:
        dstDir = Path(path)
        if not dstDir.is_dir():
            log(f"[cr]Error:[e] not a directory: {dstDir}")
            sys.exit(1)

        log(f"[b]Copy Files to {dstDir}[e]")
        log("[b]" + "=" * (len(str(dstDir)) + 14) + "[e]")
        log("")
        for name in FLATHUB_FILES:
            shutil.copyfile(bldDir / name, dstDir / name)
            log(f"[cg]Copied:[e] {name}")
        log("")
    else:
        log(f"Flathub submission files written to {bldDir.relative_to(ROOT_DIR)}/")
        log("")
