#!/usr/bin/env python3
"""Canonical URL identities for board joins and source-rating host matches."""

import urllib.parse


TRACKING_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid",
}


def hostname(url):
    """Lower-case hostname without a leading www."""
    return (urllib.parse.urlsplit(url or "").hostname or "").lower().removeprefix("www.")


def _is_tracking(key):
    key = key.lower()
    return key.startswith("utm_") or key in TRACKING_KEYS


def canonical_url(url):
    """Normalise identity while retaining query parameters that identify the resource."""
    p = urllib.parse.urlsplit((url or "").strip())
    if not p.scheme or not p.netloc:
        return (url or "").strip()

    scheme = p.scheme.lower()
    host = hostname(url)
    path = p.path or "/"
    query = urllib.parse.parse_qsl(p.query, keep_blank_values=True)

    if host == "youtu.be":
        video_id = path.strip("/").split("/")[0]
        host, path = "youtube.com", "/watch"
        query = [("v", video_id)] if video_id else []
    elif host in {"youtube.com", "m.youtube.com"}:
        host = "youtube.com"
        if path == "/watch":
            query = [(k, v) for k, v in query if k == "v"]
        elif path.startswith("/shorts/"):
            video_id = path.split("/", 3)[2]
            path, query = "/watch", [("v", video_id)]
        else:
            query = [(k, v) for k, v in query if not _is_tracking(k)]
    else:
        query = [(k, v) for k, v in query if not _is_tracking(k)]

    path = path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((scheme, host, path, urllib.parse.urlencode(sorted(query)), ""))
