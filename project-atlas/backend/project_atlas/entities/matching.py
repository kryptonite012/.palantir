"""Deterministic, explainable entity matching.

Algorithm ``er-1.1``:

1. Blocking: candidate pairs share a normalized name token or an identifier value.
2. Comparison per feature, only where *both* entities have a value
   (missing data is reported as "not compared" and never counts as agreement):

   * name: RapidFuzz token-sort / token-set similarity on normalized names
   * identifier fields (ontology ``identifier: true``): exact normalized overlap
   * other attributes: exact normalized equality, with fuzzy comparison for strings

3. Score = weighted mean of compared feature similarities.
4. Bands: ``strong`` (>= 0.90, at least one identifier agrees and none conflicts),
   ``ambiguous`` (>= threshold), else discarded. Matches resting on names and
   descriptive attributes alone (e.g. same city) can never be ``strong``.
   Every candidate still requires human review before merging.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from itertools import combinations
from typing import Any

from rapidfuzz import fuzz

ALGORITHM_VERSION = "er-1.1"

WEIGHTS = {"name": 0.45, "identifier": 0.35, "attribute": 0.2}
STRONG = 0.90
DEFAULT_THRESHOLD = 0.75
MAX_BLOCK = 250

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "madam"}
_ORG_SUFFIXES = {"inc", "ltd", "llc", "gmbh", "corp", "corporation", "co", "company", "plc", "sa", "ag", "bv", "limited"}


def normalize_name(name: str, entity_type: str = "") -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = [t for t in s.split() if t]
    drop = _HONORIFICS if entity_type == "person" else _ORG_SUFFIXES if entity_type == "organization" else set()
    tokens = [t for t in tokens if t not in drop] or tokens
    return " ".join(tokens)


def _values(attrs: dict[str, Any], field: str) -> set[str]:
    out = set()
    for item in attrs.get(field, []) or []:
        v = item.get("normalized") if isinstance(item, dict) else item
        if v not in (None, ""):
            out.add(str(v).strip().lower())
    return out


def compare(a: dict[str, Any], b: dict[str, Any], identifier_fields: set[str]) -> dict[str, Any]:
    """Compare two entity feature dicts: {id, name, attributes}."""
    na, nb = normalize_name(a["name"], a.get("type", "")), normalize_name(b["name"], b.get("type", ""))
    name_sim = max(fuzz.token_sort_ratio(na, nb), 0.95 * fuzz.token_set_ratio(na, nb)) / 100.0
    features: list[dict[str, Any]] = [{"feature": "name", "kind": "name", "a": a["name"], "b": b["name"],
                                        "similarity": round(name_sim, 4), "method": "rapidfuzz token_sort/token_set"}]
    not_compared, conflicts, matching = [], [], []
    fields = (set(a["attributes"]) | set(b["attributes"])) - {"name"}
    for f in sorted(fields):
        va, vb = _values(a["attributes"], f), _values(b["attributes"], f)
        if not va or not vb:
            not_compared.append(f)
            continue
        if f in identifier_fields:
            sim = 1.0 if va & vb else 0.0
            kind, method = "identifier", "exact normalized identifier"
        else:
            if va & vb:
                sim = 1.0
            else:
                sim = max(fuzz.ratio(x, y) for x in va for y in vb) / 100.0
                sim = sim if sim >= 0.9 else 0.0
            kind, method = "attribute", "normalized equality / fuzzy >= 0.9"
        entry = {"feature": f, "kind": kind, "a": sorted(va), "b": sorted(vb), "similarity": round(sim, 4), "method": method}
        features.append(entry)
        (matching if sim >= 0.9 else conflicts).append(f)
    total_w = sum(WEIGHTS[x["kind"]] for x in features)
    score = sum(WEIGHTS[x["kind"]] * x["similarity"] for x in features) / total_w
    identifier_agree = any(x["kind"] == "identifier" and x["similarity"] == 1.0 for x in features)
    identifier_conflict = any(x["kind"] == "identifier" and x["similarity"] == 0 for x in features)
    band = "strong" if score >= STRONG and identifier_agree and not identifier_conflict else "ambiguous"
    return {
        "score": round(score, 4), "band": band, "features": features, "matching_fields": matching,
        "conflicting_fields": conflicts, "not_compared": not_compared,
        "note": "Fields missing on either side were not compared and are not evidence of identity.",
        "algorithm_version": ALGORITHM_VERSION,
    }


def candidate_pairs(items: list[dict[str, Any]], identifier_fields: set[str]) -> set[tuple[int, int]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        for tok in normalize_name(it["name"], it.get("type", "")).split():
            if len(tok) >= 2:
                blocks[f"n:{tok}"].append(i)
        for f in identifier_fields:
            for v in _values(it["attributes"], f):
                blocks[f"i:{f}:{v}"].append(i)
    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        if 1 < len(members) <= MAX_BLOCK:
            pairs.update(combinations(sorted(set(members)), 2))
    return pairs


def find_matches(items: list[dict[str, Any]], identifier_fields: set[str],
                 threshold: float = DEFAULT_THRESHOLD) -> list[dict[str, Any]]:
    out = []
    for i, j in candidate_pairs(items, identifier_fields):
        res = compare(items[i], items[j], identifier_fields)
        if res["score"] >= threshold:
            out.append({"a": items[i]["id"], "b": items[j]["id"], **res})
    out.sort(key=lambda r: -r["score"])
    return out
