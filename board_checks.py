#!/usr/bin/env python3
"""Fail-closed integrity checks for data consumed by the static board build."""

from url_identity import canonical_url


ALERT_SCHEMA_VERSION = 2
EVALUATED_ALERT_METHODS = {"local-model", "administrative-noise-rule", "human"}
UNASSESSED_ALERT_METHODS = {"unassessed", "legacy-unassessed"}


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


def _valid_alert_priority(value):
    return not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= 5


def has_valid_alert_evaluation(alert):
    """Return whether an alert carries a complete assessed-priority provenance chain."""
    if alert.get("alert_schema_version") != ALERT_SCHEMA_VERSION:
        return False
    method = alert.get("evaluation_method")
    priority = alert.get("substantive_priority")
    if method not in EVALUATED_ALERT_METHODS or not _valid_alert_priority(priority):
        return False
    if method == "local-model":
        return isinstance(alert.get("model"), str) and bool(alert["model"].strip())
    if method == "administrative-noise-rule":
        return alert.get("model") is None
    return alert.get("reviewed") is True


def evaluated_alert_priority(alert):
    """Return the substantive priority only when its provenance is valid."""
    if has_valid_alert_evaluation(alert):
        return alert["substantive_priority"]
    return None


def regulatory_notification_eligible(alert):
    """Require an evaluated local-model P1 or P2 and the existing duty-shift predicate."""
    return (
        alert.get("evaluation_method") == "local-model"
        and has_valid_alert_evaluation(alert)
        and evaluated_alert_priority(alert) in (1, 2)
        and alert.get("is_operator_duty_shift") is True
    )


def validate_regulatory_alerts(alerts):
    """Reject ambiguous, incomplete or unsupported Sovereign Watch provenance."""
    if not isinstance(alerts, list) or not alerts:
        raise BoardIntegrityError("regulatory alerts must be a non-empty list")

    errors = []
    allowed_methods = EVALUATED_ALERT_METHODS | UNASSESSED_ALERT_METHODS
    for index, alert in enumerate(alerts):
        label = f"regulatory alert {index}"
        if not isinstance(alert, dict):
            errors.append(f"{label} is not an object")
            continue
        if alert.get("alert_schema_version") != ALERT_SCHEMA_VERSION:
            errors.append(f"{label} has unsupported or missing alert schema version")

        queue_priority = alert.get("source_queue_priority")
        if not _valid_alert_priority(queue_priority):
            errors.append(f"{label} has invalid source queue priority")

        method = alert.get("evaluation_method")
        if method not in allowed_methods:
            errors.append(f"{label} has invalid or missing evaluation method")
            continue

        substantive = alert.get("substantive_priority")
        reviewed = alert.get("reviewed")
        model = alert.get("model")
        legacy_raw = alert.get("legacy_raw_priority")
        deprecated_raw = alert.get("priority")

        if not isinstance(alert.get("is_operator_duty_shift"), bool):
            errors.append(f"{label} has invalid duty-shift state")
        if reviewed is True and method != "human":
            errors.append(f"{label} claims human review without a human method")

        if method == "legacy-unassessed":
            if substantive is not None:
                errors.append(f"{label} gives legacy unassessed data a substantive priority")
            if not _valid_alert_priority(legacy_raw):
                errors.append(f"{label} has invalid or missing legacy raw priority")
            if deprecated_raw is not None and deprecated_raw != legacy_raw:
                errors.append(f"{label} legacy raw priority disagrees with retained priority")
            if model is not None:
                errors.append(f"{label} assigns a model identity to missing legacy provenance")
        elif method == "unassessed":
            if substantive is not None:
                errors.append(f"{label} gives an unassessed record a substantive priority")
            if reviewed is not False:
                errors.append(f"{label} unassessed record lacks explicit reviewed false")
            if legacy_raw is not None:
                errors.append(f"{label} unassessed record carries a legacy raw priority")
        elif method == "local-model":
            if not _valid_alert_priority(substantive):
                errors.append(f"{label} has invalid evaluated priority")
            if not isinstance(model, str) or not model.strip():
                errors.append(f"{label} local-model evaluation lacks model identity")
            if reviewed is not False:
                errors.append(f"{label} local-model record lacks explicit reviewed false")
            if legacy_raw is not None:
                errors.append(f"{label} evaluated record carries a legacy raw priority")
        elif method == "administrative-noise-rule":
            if not _valid_alert_priority(substantive):
                errors.append(f"{label} has invalid rule-evaluated priority")
            if model is not None:
                errors.append(f"{label} rule evaluation has a model identity")
            if reviewed is not False:
                errors.append(f"{label} rule-evaluated record lacks explicit reviewed false")
            if legacy_raw is not None:
                errors.append(f"{label} rule-evaluated record carries a legacy raw priority")
        elif method == "human":
            if not _valid_alert_priority(substantive):
                errors.append(f"{label} has invalid human-evaluated priority")
            if reviewed is not True:
                errors.append(f"{label} human method lacks reviewed true")
            if legacy_raw is not None:
                errors.append(f"{label} human-evaluated record carries a legacy raw priority")

        if method in EVALUATED_ALERT_METHODS and deprecated_raw is not None:
            if deprecated_raw != substantive:
                errors.append(f"{label} retained priority disagrees with substantive priority")

    if errors:
        preview = "\n  - ".join(errors[:20])
        extra = f"\n  - and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise BoardIntegrityError(
            f"regulatory alert integrity check failed:\n  - {preview}{extra}")
    return len(alerts)
