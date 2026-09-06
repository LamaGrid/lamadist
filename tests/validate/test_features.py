# SPDX-License-Identifier: Apache-2.0
"""Turn every scenario under ``features/`` into a plain pytest function.

gherkin-official's ``Parser`` reads each feature file and its
``Compiler`` expands outlines, backgrounds, and tag inheritance into
pickles.  This module only names, tags, and dispatches: one function
per pickle, tags as markers, example values in the node id so ``-k``
selects one row, and every step text routed through ``steps.STEPS``.
An unmatched step fails the test.

Rule 4 (ADR 0010) is enforced at import time: every property scenario
(tagged ``@P<n>``) must have a ``@negative`` twin carrying the same
property tag, or collection fails.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from gherkin.parser import Parser
from gherkin.pickles.compiler import Compiler, GherkinDocumentWithURI, Pickle
from steps import STEPS, Context

FEATURES = Path(__file__).parent / "features"
_PROPERTY_TAG = re.compile(r"^@P\d+$")


def _dispatch(ctx: Context, text: str) -> None:
    for pattern, fn in STEPS:
        matched = pattern.fullmatch(text)
        if matched:
            fn(ctx, *matched.groups())
            return
    pytest.fail(f"no step definition for: {text}")


def _with_target(steps: list[str]) -> Callable[[Any], None]:
    def test(target: Any) -> None:
        ctx: Context = {"target": target}
        for text in steps:
            _dispatch(ctx, text)

    return test


def _without_target(steps: list[str]) -> Callable[[], None]:
    def test() -> None:
        ctx: Context = {}
        for text in steps:
            _dispatch(ctx, text)

    return test


def _make(pickle: Pickle, needs_target: bool) -> Callable[..., None]:
    steps = [s["text"] for s in pickle["steps"]]
    test: Callable[..., None] = (
        _with_target(steps) if needs_target else _without_target(steps)
    )
    for tag in pickle["tags"]:
        test = getattr(pytest.mark, tag["name"].lstrip("@"))(test)
    test.__doc__ = pickle["name"]
    return test


def _example_rows(doc: GherkinDocumentWithURI) -> dict[str, list[str]]:
    """Examples row AST id to its cell values, for readable node ids."""
    rows: dict[str, list[str]] = {}
    for child in doc["feature"]["children"]:
        for examples in child.get("scenario", {}).get("examples", []):
            for row in examples.get("tableBody", []):
                rows[row["id"]] = [cell["value"] for cell in row["cells"]]
    return rows


def _load() -> list[tuple[str, Pickle]]:
    named: list[tuple[str, Pickle]] = []
    for feature in sorted(FEATURES.glob("*.feature")):
        parsed = Parser().parse(feature.read_text())
        doc = cast(GherkinDocumentWithURI, {**parsed, "uri": feature.name})
        rows = _example_rows(doc)
        for pickle in Compiler().compile(doc):
            base = re.sub(r"\W+", "_", pickle["name"]).strip("_").lower()
            cells = [rows[i] for i in pickle["astNodeIds"] if i in rows]
            param = "[" + "-".join(cells[0]) + "]" if cells else ""
            named.append((f"test_{base}{param}", pickle))
    return named


def _check_twins(pickles: list[Pickle]) -> None:
    positive: set[str] = set()
    negative: set[str] = set()
    for pickle in pickles:
        tags = {t["name"] for t in pickle["tags"]}
        props = {t for t in tags if _PROPERTY_TAG.match(t)}
        (negative if "@negative" in tags else positive).update(props)
    missing = sorted(positive - negative)
    if missing:
        raise pytest.UsageError(
            f"property scenarios without a @negative twin (rule 4): {', '.join(missing)}"
        )


_named = _load()
_check_twins([p for _, p in _named])
for _name, _pickle in _named:
    _tags = {t["name"] for t in _pickle["tags"]}
    globals()[_name] = _make(_pickle, needs_target="@negative" not in _tags)
