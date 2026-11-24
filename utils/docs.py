"""
UmbraEdit - Documentation
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
import os
import shutil
import subprocess
import sys

from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from utils.common import ROOT_DIR, extractVersion, formatVersion, log, splitVersion, systemCall
from utils.manual import validate_manual_pdf


def updateDocsTranslationSources(args: argparse.Namespace) -> None:
    """Build the documentation .po files."""
    log("")
    log("[b]Building Docs Translation Files[e]")
    log("[b]===============================[e]")
    log("")

    docsDir = ROOT_DIR / "docs"
    locsDir = ROOT_DIR / "docs" / "source" / "locales"
    locsDir.mkdir(exist_ok=True)

    log("[b]Generating POT Files[e]")
    systemCall(["make", "gettext"], cwd=docsDir)
    log("")

    lang = args.lang
    update = []
    if lang == ["all"]:
        update = [i.stem for i in locsDir.iterdir() if i.is_dir()]
    else:
        update = lang

    log("[b]Generating PO Files[e]")
    log(f"Languages: {update}")
    log("")

    for code in update:
        systemCall(["sphinx-intl", "update", "-p", "build/gettext", "-l", code], cwd=docsDir)
        log("")

    log("[cg]Done[e]")
    log("")


def _buildTectonicPdf(docsDir: Path, code: str, env: dict[str, str]) -> str:
    """Build a PDF manual with Sphinx and Tectonic.

    Tectonic is used as a local fallback when latexmk is unavailable. The
    release CI uses latexmk, while this path keeps manual generation
    reproducible on developer machines that do not install a full TeX
    distribution.
    """
    latexDir = docsDir / "build" / "latex"
    doctreeDir = docsDir / "build" / "doctrees"
    if latexDir.exists():
        shutil.rmtree(latexDir)
    if doctreeDir.exists():
        shutil.rmtree(doctreeDir)

    sphinxCmd = [sys.executable, "-m", "sphinx", "-b", "latex"]
    if code != "en":
        sphinxCmd.extend(["-D", f"language={code}"])
    sphinxCmd.extend([str(docsDir / "source"), str(latexDir)])
    sphinxResult = subprocess.run(
        sphinxCmd,
        cwd=docsDir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    tectonic = shutil.which("tectonic")
    if not tectonic:
        raise RuntimeError("Neither latexmk nor tectonic is available to build PDF manuals")
    tectonicCmd = [
        tectonic,
        "-X",
        "compile",
        "-r",
        "2",
        "--keep-logs",
        "--outdir",
        str(latexDir),
        str(latexDir / "manual.tex"),
    ]
    tectonicResult = subprocess.run(
        tectonicCmd,
        cwd=latexDir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return "\n".join((sphinxResult.stdout, sphinxResult.stderr, tectonicResult.stdout, tectonicResult.stderr))


def buildDocs(args: argparse.Namespace | None = None, *, pdf: bool = False) -> None:
    """Build the documentation files, either as HTML or PDF."""
    log("")
    log("[b]" + ("Building Docs Manuals" if pdf else "Building HTML Docs") + "[e]")
    log("[b]" + ("=====================" if pdf else "==================") + "[e]")
    log("")

    bldRoot = ROOT_DIR / "dist_doc" / "html"
    docsDir = ROOT_DIR / "docs"
    locsDir = ROOT_DIR / "docs" / "source" / "locales"
    pdfFile = docsDir / "build" / "latex" / "manual.pdf"
    locsDir.mkdir(exist_ok=True)
    bldRoot.mkdir(exist_ok=True, parents=True)
    locConf = tomllib.loads((locsDir / "config.toml").read_text(encoding="utf-8"))

    currVersion = extractVersion()[0]
    major, minor, _ = splitVersion(currVersion)
    intVersion = major * 100 + minor
    cutoffVersion = intVersion - 200

    lang = args.lang if args else ["all"]
    build = []
    if lang == ["all"]:
        build = ["en"] + [i.stem for i in locsDir.iterdir() if i.is_dir()]
    else:
        build = lang

    for code in build:
        outDir = bldRoot / code
        env = os.environ.copy()
        env["SPHINX_I18N_VERSION"] = formatVersion(currVersion)
        pdfName = "manual.pdf"
        if code != "en":
            if code not in locConf:
                raise RuntimeError(f"No config for language code '{code}' in config.toml")

            locVersion = locConf[code].get("version", "")
            locMajor, locMinor, _ = splitVersion(locVersion)
            locIntVersion = locMajor * 100 + locMinor
            if locIntVersion < cutoffVersion:
                log(f"[cy]WARNING:[e] Skipping build for '{code}' because version is too old ({locVersion})")
                continue

            env["SPHINX_I18N_VERSION"] = formatVersion(locVersion)
            env["SPHINX_I18N_AUTHORS"] = ", ".join(locConf[code].get("authors", []))
            pdfName = f"manual_{code}.pdf"

        env["SPHINXOPTS"] = f"-D language={code}" if code != "en" else ""

        try:
            if pdf and not (shutil.which("latexmk") and shutil.which("make")):
                output = _buildTectonicPdf(docsDir, code, env)
            else:
                target = "latexpdf" if pdf else "html"
                result = subprocess.run(
                    ["make", "clean", target],
                    cwd=docsDir,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                output = "\n".join((result.stdout, result.stderr))
            log("\n".join(output.rstrip().splitlines()[-11:]))
            log("")
            if pdf:
                validate_manual_pdf(pdfFile)
                assetDir = ROOT_DIR / "umbraedit" / "assets"
                assetDir.mkdir(exist_ok=True, parents=True)
                os.replace(pdfFile, assetDir / pdfName)
            else:
                if outDir.exists():
                    shutil.rmtree(outDir)
                (docsDir / "build" / "html").rename(outDir)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Documentation build returned error code {exc.returncode}") from exc
        except Exception as exc:
            raise RuntimeError(f"Documentation build failed for '{code}': {exc}") from exc

    log("")


def buildHtmlDocs(args: argparse.Namespace | None = None) -> None:
    """Build the documentation files."""
    buildDocs(args, pdf=False)


def buildPdfDocAssets(args: argparse.Namespace | None = None) -> None:
    """Build the documentation PDF files."""
    buildDocs(args, pdf=True)
