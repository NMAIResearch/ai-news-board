#!/usr/bin/env python3
"""Fail-closed integrity checks for data consumed by the static board build."""

from url_identity import canonical_url


class BoardIntegrityError(ValueError):
    """Raised when generated board data makes an unsupported provenance claim."""


def _url_of(item):
    return next((source.get("url", "") for source in item.get("sources", [])
                 if source.get("url")), "")


def validate_board(items, spans, evidence, registry, source_types):
    """Validate source, label, URL, topic and claim-relationship provenance."""
    errors = []
    identities = {}

    for index, item in enumerate(items):
        label = item.get("headline", f"item {index}")
        sources = item.get("sources") or []
        for source in sources:
            source_type = source.get("source_type", "other")
            spec = source_types.get(source_type)
            if spec is None:
                errors.append(f"{label}: unknown source type {source_type}")
                continue
            expected = int(spec["tier"])
            actual = source.get("source_tier")
            if actual is None or int(actual) != expected:
                errors.append(
                    f"{label}: source tier {actual} disagrees with {source_type} tier {expected}")

        url = _url_of(item)
        if url:
            identity = canonical_url(url)
            if identity in identities:
                errors.append(
                    f"{label}: URL identity duplicates {identities[identity]} ({identity})")
            else:
                identities[identity] = label

        rec = spans.get(url) or {}
        span_total = len(rec.get("spans", [])) if rec.get("fetch") == "ok" else 0
        method = item.get("evidence_method")
        denominator = item.get("denominator_stated", "?")
        coverage = item.get("evidence_coverage") or {}
        seen = int(coverage.get("seen", 0))
        stated_total = int(coverage.get("total", 0))
        if seen < 0 or stated_total < 0 or seen > stated_total:
            errors.append(f"{label}: invalid evidence coverage {seen}/{stated_total}")
        if denominator == "n/a" and span_total:
            errors.append(f"{label}: n/a denominator conflicts with {span_total} figure spans")
        if method in {"rule", "local-model"}:
            if rec.get("fetch") != "ok":
                errors.append(f"{label}: {method} label has no fetched article evidence")
            if seen != span_total or stated_total != span_total:
                errors.append(
                    f"{label}: {method} coverage {seen}/{stated_total} does not cover "
                    f"all {span_total} spans")
            if not rec.get("content_hash") or not item.get("content_hash"):
                errors.append(f"{label}: {method} label is missing an article content hash")
            elif item.get("content_hash") != rec.get("content_hash"):
                errors.append(f"{label}: label content hash is stale")
            if not rec.get("evidence_hash") or not item.get("evidence_hash"):
                errors.append(f"{label}: {method} label is missing an extracted evidence hash")
            elif item.get("evidence_hash") != rec.get("evidence_hash"):
                errors.append(f"{label}: extracted evidence hash is stale")
        if method == "unassessed" and seen:
            errors.append(f"{label}: unassessed label claims {seen} spans read")

        topics = item.get("topics") or []
        unknown_topics = [topic for topic in topics if topic not in registry]
        if unknown_topics:
            errors.append(f"{label}: unknown topics {', '.join(unknown_topics)}")
        anchor = item.get("_anchor_match")
        if anchor and item.get("_anchor_ambiguous"):
            errors.append(f"{label}: ambiguous automatic anchor was published")
        if anchor and anchor.get("topic") not in topics:
            errors.append(f"{label}: anchor topic is absent from item topics")

        ev = evidence.get(url) or {}
        claim_tier = ev.get("claim_tier")
        relationship = ev.get("claim_relationship")
        if claim_tier is not None and relationship in {None, "unresolved"}:
            errors.append(f"{label}: numeric claim tier has no resolved relationship")
        if sources and ev and int(ev.get("source_tier", -1)) != int(sources[0].get("source_tier", -2)):
            errors.append(f"{label}: article evidence carries a stale source tier")

    if errors:
        preview = "\n  - ".join(errors[:20])
        extra = f"\n  - and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise BoardIntegrityError(f"board integrity check failed:\n  - {preview}{extra}")
    return len(items)
