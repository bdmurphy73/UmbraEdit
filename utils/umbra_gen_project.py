#!/usr/bin/env python3
"""
UmbraEdit - Benchmark Project Generator
========================================

This file is a part of UmbraEdit, a fork of novelWriter.

Copyright (C) 2026 B.D. Murphy and novelWriter contributors.

Generates a deterministic UmbraEdit project for benchmarking.

Usage:
    python3 utils/umbra_gen_project.py --words 400000 --scenes 2000 \
        --characters 40 --places 20 --seed 7 --output /tmp/bench_project
    python3 utils/umbra_gen_project.py --small --output /tmp/fixture-small
"""  # noqa

from __future__ import annotations

import argparse
import random
import sys

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

LOREM_WORDS = [
    "the", "of", "and", "a", "to", "in", "is", "you", "that", "it", "he",
    "was", "for", "on", "are", "as", "with", "his", "they", "I", "at", "be",
    "this", "have", "from", "or", "one", "had", "by", "word", "but", "not",
    "what", "all", "were", "we", "when", "your", "can", "said", "there",
    "use", "an", "each", "which", "she", "do", "how", "their", "if", "will",
    "up", "other", "about", "out", "many", "then", "them", "these", "so",
    "some", "her", "would", "make", "like", "him", "into", "time", "has",
    "look", "two", "more", "write", "go", "see", "number", "no", "way",
    "could", "people", "my", "than", "first", "water", "been", "call",
    "who", "oil", "its", "now", "find", "long", "down", "day", "did",
    "get", "come", "made", "may", "part",
]

DIALOGUE_STARTERS = [
    "\u201c{sentence}\u201d",
    "\u201c{sentence},\u201d she said.",
    "\u201c{sentence}\u201d he replied.",
    "\u201c{sentence},\u201d whispered {name}.",
    "\u201c{sentence}\u201d asked {name}.",
]

NARRATIVE_STARTERS = [
    "The {noun} {verb} through the {place}.",
    "{name} walked past the {noun} and {verb}.",
    "It was a {adjective} {timeperiod} in {place}.",
    "Outside, the {noun} was {adjective}.",
    "There was no sign of {name} anywhere.",
]


def _loremSentence(rng: random.Random) -> str:
    """Generate a single lorem-style sentence."""
    words = [rng.choice(LOREM_WORDS) for _ in range(rng.randint(8, 20))]
    sentence = " ".join(words).capitalize() + "."
    return sentence


def _loremParagraph(rng: random.Random, isDialogue: bool, name: str) -> str:
    """Generate a single lorem-style paragraph."""
    sentences = [_loremSentence(rng) for _ in range(rng.randint(3, 6))]
    if isDialogue:
        starter = rng.choice(DIALOGUE_STARTERS)
        return starter.format(sentence=" ".join(sentences[:2]), name=name)
    return " ".join(sentences)


def _makeNames(count: int, rng: random.Random) -> list[str]:
    """Generate character names."""
    firsts = [
        "Alice", "Bruno", "Clara", "Diego", "Elena", "Felix", "Grace",
        "Hugo", "Iris", "Jasper", "Kara", "Liam", "Mona", "Nils", "Olga",
        "Pablo", "Quinn", "Rosa", "Sven", "Tara", "Uma", "Viktor", "Wanda",
        "Xavier", "Yuki", "Zara",
    ]
    return [f"{rng.choice(firsts)} {chr(65 + i % 26)}." for i in range(count)]


def _makePlaces(count: int, rng: random.Random) -> list[str]:
    """Generate place names."""
    types = [
        "Street", "Avenue", "Park", "Cafe", "Building", "Bridge",
        "Square", "Garden", "Tower", "Harbour", "Station", "Library",
    ]
    return [f"{rng.choice(LOREM_WORDS).capitalize()} {rng.choice(types)}" for _ in range(count)]


def generateProject(
    output: Path,
    words: int,
    scenes: int,
    characters: int,
    places: int,
    seed: int,
) -> None:
    """Generate a deterministic UmbraEdit project."""
    rng = random.Random(seed)
    names = _makeNames(characters, rng)
    placeNames = _makePlaces(places, rng)

    wordsPerScene = max(1, words // max(1, scenes))
    paragraphsPerScene = max(1, wordsPerScene // 15)

    if output.exists():
        print(f"ERROR: Output folder already exists: {output}")
        sys.exit(1)

    output.mkdir(parents=True)

    # Write project XML
    projXml = output / "nwProject.nwx"
    projXml.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<UmbraEditXML appVersion=\"2026.11.0005\" hexVersion=\"0x01000000\" "
        "fileVersion=\"1.6\" fileRevision=\"1\" timeStamp=\"2026-01-01T00:00:00Z\">\n"
        "  <project id=\"bench-project-0000\" saveCount=\"0\" autoCount=\"0\" "
        "editTime=\"0\" indexRevision=\"0\">\n"
        "    <name>Benchmark Project</name>\n"
        "    <author>Benchmark Generator</author>\n"
        "  </project>\n"
        "  <settings>\n"
        "    <doBackup>no</doBackup>\n"
        "  </settings>\n"
        "  <content items=\"0\" novelWords=\"0\" notesWords=\"0\" "
        "novelChars=\"0\" notesChars=\"0\">\n"
        "  </content>\n"
        "</UmbraEditXML>\n",
        encoding="utf-8",
    )

    # Create content folder
    contentDir = output / "content"
    contentDir.mkdir(exist_ok=True)

    # Write character notes
    for i, name in enumerate(names):
        noteHandle = f"char_{i:04d}"
        noteFile = contentDir / f"{noteHandle}.md"
        noteFile.write_text(
            f"+++\nname = \"{name}\"\nparent = \"chars\"\nhandle = \"{noteHandle}\"\n"
            f"class = \"CHARACTER\"\nlayout = \"NOTE\"\n+++\n\n"
            f"# {name}\n\n@tag: {name.split()[0].lower()}\n\n"
            f"A character in the benchmark project.\n",
            encoding="utf-8",
        )

    # Write place notes
    for i, place in enumerate(placeNames):
        noteHandle = f"place_{i:04d}"
        noteFile = contentDir / f"{noteHandle}.md"
        noteFile.write_text(
            f"+++\nname = \"{place}\"\nparent = \"places\"\nhandle = \"{noteHandle}\"\n"
            f"class = \"WORLD\"\nlayout = \"NOTE\"\n+++\n\n"
            f"# {place}\n\n@tag: {place.lower().replace(' ', '')}\n\n"
            f"A location in the benchmark project.\n",
            encoding="utf-8",
        )

    # Write scenes
    totalWords = 0
    for sceneIdx in range(scenes):
        chapterIdx = sceneIdx // 4 + 1
        sceneInChapter = sceneIdx % 4 + 1
        sceneHandle = f"scene_{sceneIdx:04d}"
        sceneFile = contentDir / f"{sceneHandle}.md"

        povName = names[sceneIdx % len(names)]
        charName = names[(sceneIdx + 1) % len(names)]
        placeName = placeNames[sceneIdx % len(placeNames)]

        # 30% dialogue paragraphs
        paragraphs = []
        for _ in range(paragraphsPerScene):
            isDialogue = rng.random() < 0.30
            paragraphs.append(_loremParagraph(rng, isDialogue, charName))

        sceneText = "\n\n".join(paragraphs)
        wordCount = len(sceneText.split())
        totalWords += wordCount

        meta = (
            f"+++\nname = \"Scene {sceneIdx + 1}\"\nparent = \"novel\"\n"
            f"handle = \"{sceneHandle}\"\nclass = \"NOVEL\"\nlayout = \"DOCUMENT\"\n"
            f"heading = \"H3\"\n+++\n\n"
            f"### Scene {sceneIdx + 1}\n\n"
            f"@pov: {povName.split()[0].lower()}\n"
            f"@char: {charName.split()[0].lower()}\n"
            f"@location: {placeName.lower().replace(' ', '')}\n\n"
            f"%Synopsis: A benchmark scene.\n\n"
        )
        sceneFile.write_text(meta + sceneText + "\n", encoding="utf-8")

    print(f"Generated project: {output}")
    print(f"  Scenes: {scenes}")
    print(f"  Characters: {characters}")
    print(f"  Places: {places}")
    print(f"  Total words: ~{totalWords}")
    print(f"  Seed: {seed}")


def main() -> None:
    """Parse arguments and generate the project."""
    parser = argparse.ArgumentParser(description="Generate a benchmark UmbraEdit project.")
    parser.add_argument("--words", type=int, default=400000, help="Target word count.")
    parser.add_argument("--scenes", type=int, default=2000, help="Number of scenes.")
    parser.add_argument("--characters", type=int, default=40, help="Number of characters.")
    parser.add_argument("--places", type=int, default=20, help="Number of places.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for determinism.")
    parser.add_argument("--output", type=str, required=True, help="Output folder.")
    parser.add_argument("--small", action="store_true", help="Generate the 12-scene fixture-small.")

    args = parser.parse_args()

    if args.small:
        generateProject(
            output=Path(args.output),
            words=1200,
            scenes=12,
            characters=4,
            places=3,
            seed=args.seed,
        )
    else:
        generateProject(
            output=Path(args.output),
            words=args.words,
            scenes=args.scenes,
            characters=args.characters,
            places=args.places,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()
