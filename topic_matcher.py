#!/usr/bin/env python3
"""Deterministic topic candidates and fail-closed reality-anchor selection."""

import json
import os
import re


HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "topic_registry.json")
SUFFIX = r"(?:s|es)?"


def load_registry(path=REGISTRY):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["topics"]


def _match(text, rule):
    if rule.get("regex"):
        return re.search(rule["regex"], text or "", re.I)
    phrase = rule["phrase"]
    return re.search(
        r"(?<![a-z0-9])" + re.escape(phrase) + SUFFIX + r"(?![a-z0-9])",
        text or "", re.I)


def _blocked(text, exclusions):
    return any(_match(text, {"phrase": phrase}) for phrase in exclusions)


def match_texts(headline, publisher_tags, span_sentences, registry=None):
    """Return all topic candidates and at most one anchor topic.

    Headline evidence receives twice the rule score. Publisher tags and figure sentences
    receive the stated score. A tie at the best anchor score abstains.
    """
    registry = registry or load_registry()
    texts = [("headline", headline or "")]
    texts += [("publisher tag", tag) for tag in (publisher_tags or [])]
    texts += [("article span", sent) for sent in (span_sentences or [])]
    candidates = []

    for topic, spec in registry.items():
        if _blocked(headline or "", spec.get("headline_exclude", [])):
            continue
        evidence, score = [], 0
        seen_rules = set()
        for basis, text in texts:
            if _blocked(text, spec.get("exclude", [])):
                continue
            factor = 2 if basis == "headline" else 1
            for rule_index, rule in enumerate(spec.get("rules", [])):
                hit = _match(text, rule)
                if not hit:
                    continue
                # Repetition across several article spans must not manufacture confidence.
                # Each rule contributes once per evidence class.
                evidence_class = (basis, rule_index)
                if evidence_class in seen_rules:
                    continue
                seen_rules.add(evidence_class)
                points = int(rule.get("score", 1)) * factor
                score += points
                evidence.append({
                    "basis": basis,
                    "match": hit.group(0),
                    "score": points,
                    "text": text,
                })
        surface_evidence = any(e["basis"] in {"headline", "publisher tag"}
                               for e in evidence)
        if score >= int(spec.get("topic_min_score", 2)) and surface_evidence:
            candidates.append({
                "topic": topic,
                "label": spec["label"],
                "score": score,
                "evidence": evidence,
                "anchors": spec.get("anchors", []),
                "anchor_min_score": int(spec.get("anchor_min_score", 999)),
            })

    candidates.sort(key=lambda c: (-c["score"], c["topic"]))
    eligible = [c for c in candidates
                if c["anchors"] and c["score"] >= c["anchor_min_score"]
                and any(e["basis"] == "headline" for e in c["evidence"])]
    anchor = None
    if eligible and (len(eligible) == 1 or eligible[0]["score"] > eligible[1]["score"]):
        anchor = eligible[0]
    return {"topics": candidates, "anchor": anchor, "ambiguous": bool(eligible and not anchor)}


def match_item(item, spans, registry=None):
    url = next((s.get("url", "") for s in item.get("sources", []) if s.get("url")), "")
    rec = spans.get(url) or {}
    return match_texts(
        item.get("headline", ""),
        rec.get("publisher_tags") or [],
        [s.get("sentence", "") for s in rec.get("spans", [])],
        registry,
    )
