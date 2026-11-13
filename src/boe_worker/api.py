"""Validate BoE requests and decode the source's revision-aware XML format."""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from xml.etree.ElementTree import Element

from .transport import ApiError, Config, request_bytes
from .values import iso_date, number, source_json
from .xml import local_name, parse_xml

CODE = r"^[A-Za-z][A-Za-z0-9_]{1,63}$"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def codes(values: list[str]) -> list[str]:
    """Validate the documented 300-series limit and normalize case."""
    if not 1 <= len(values) <= 300 or any(not isinstance(v, str) or re.fullmatch(CODE, v) is None for v in values):
        raise ApiError("series_codes must contain 1-300 valid BoE series codes")
    result = [v.upper() for v in values]
    if len(set(result)) != len(result):
        raise ApiError("series_codes must not repeat")
    return result


def source_date(value: str) -> str:
    """Format an ISO date using English month names independent of process locale."""
    parsed = iso_date(value)
    return f"{parsed.day:02d}/{MONTHS[parsed.month - 1]}/{parsed.year:04d}"


def bounds(start: str, end: str, updated: str = "") -> None:
    """Validate dates and the earliest supported revision baseline."""
    if iso_date(start) > iso_date(end):
        raise ApiError("start_date must not be after end_date")
    if updated and updated != "latest" and iso_date(updated) < date(2007, 6, 3):
        raise ApiError("updated_since must be latest or a date on or after 2007-06-03")


def detail(node: Element, *, depth: int = 0) -> dict[str, Any]:
    """Preserve source attributes, text and hierarchy without fetching linked resources."""
    if depth > 32:
        raise ApiError("BoE XML metadata exceeds the supported nesting depth")
    return {
        "tag": local_name(node.tag),
        "attributes": dict(node.attrib),
        "text": node.text,
        "children": [detail(child, depth=depth + 1) for child in node],
    }


def request(
    selected: list[str] | None,
    start: str,
    end: str,
    *,
    provisional: bool = False,
    updated: str = "",
    updates_only: bool = False,
) -> list[Element]:
    """Retrieve XML with metadata, footnotes and available publication history."""
    query = [
        ("CodeVer", "new"),
        ("xml.x", "yes"),
        ("Datefrom", source_date(start)),
        ("Dateto", source_date(end)),
        ("SeriesCodes", ",".join(selected) if selected else "all"),
        ("VPD", "Y" if provisional else "N"),
        ("VFD", "Y"),
        ("VUD", "B" if updates_only else "A"),
    ]
    if selected is None:
        query = [(key, value) for key, value in query if key not in {"VPD", "VFD", "VUD"}]
    if updated:
        query.append(("VUDdate", updated if updated == "latest" else source_date(updated)))
    response = request_bytes("_iadb-fromshowcolumns.asp", query, Config.from_env(), accept="application/xml")
    root = parse_xml(response.body)
    if root.tag != "{http://www.gesmes.org/xml/2002-08-01}Envelope":
        raise ApiError("BoE response is not a statistics XML envelope")
    result = [n for n in root if local_name(n.tag) == "Cube" and n.get("SCODE")]
    if any(local_name(n.tag).lower() in {"error", "message"} for n in root):
        raise ApiError("BoE returned an error in its XML envelope")
    identifiers = [n.get("SCODE", "").upper() for n in result]
    if len(set(identifiers)) != len(identifiers):
        raise ApiError("BoE response contains duplicate series")
    if selected is not None and (
        set(identifiers) - set(selected) or (not updates_only and set(identifiers) != set(selected))
    ):
        raise ApiError("BoE response contains unexpected or missing requested series")
    return result


def metadata(node: Element) -> dict[str, Any]:
    """Expose source series descriptions, categories and full non-observation metadata."""
    children = [n for n in node if "TIME" not in n.attrib]
    attributes = {
        key: value
        for child in children
        for key, value in child.attrib.items()
        if not key.startswith("CAT_") and key != "VAL_DESC"
    }
    categories = [dict(n.attrib) for n in children if "CAT_NAME" in n.attrib]
    return {
        "series_code": node.get("SCODE"),
        "title": node.get("DESC"),
        "description": node.get("CONCAT"),
        "frequency": attributes.get("FREQ_CODE"),
        "frequency_name": attributes.get("FREQ_NAME"),
        "unit_descriptor": next((n.get("VAL_DESC") for n in categories if n.get("CAT_NAME") == "OUTPUT IN"), None),
        "first_observation": attributes.get("FIRST_OBS"),
        "last_observation": attributes.get("LAST_OBS"),
        "categories_json": source_json(categories),
        "metadata_json": source_json({"attributes": dict(node.attrib), "children": [detail(n) for n in children]}),
    }


def observations(nodes: list[Element], *, revisions: bool = False) -> list[dict[str, Any]]:
    """Flatten observations and source-provided releases, preserving decimal text."""
    result = []
    for series in nodes:
        shared = metadata(series)
        seen: set[str] = set()
        for obs in series:
            period = obs.get("TIME")
            if period is None:
                continue
            observed = iso_date(period)
            if period in seen:
                raise ApiError("BoE response contains a duplicate observation period")
            seen.add(period)
            value, raw = number(obs.get("OBS_VALUE"))
            provisional, provisional_raw = number(obs.get("PROV_VALUE"))
            common = {
                **shared,
                "period": period,
                "observation_date": observed,
                "last_updated": obs.get("LAST_UPDATED"),
                "confidentiality": obs.get("OBS_CONF"),
                "details_json": source_json(detail(obs)),
            }
            if not revisions:
                result.append(
                    {
                        **common,
                        "value": value,
                        "value_text": raw,
                        "provisional_value": provisional,
                        "provisional_value_text": provisional_raw,
                    }
                )
                continue
            releases: list[dict[str, Any]] = []
            signatures: set[tuple[str | None, str | None]] = set()
            for revision in obs:
                if local_name(revision.tag) != "Revision":
                    continue
                published = revision.get("UPDATE_TIMESTAMP")
                if not published:
                    raise ApiError("BoE revision is missing its publication timestamp")
                old_value, old_raw = number(revision.get("OBS_VALUE"))
                signature = (published, old_raw)
                if signature in signatures:
                    raise ApiError("BoE response contains a duplicate revision")
                signatures.add(signature)
                releases.append(
                    {
                        **common,
                        "published_at": published,
                        "value": old_value,
                        "value_text": old_raw,
                        "is_current": published == obs.get("LAST_UPDATED") and old_raw == raw,
                        "is_provisional": False,
                    }
                )
            if (obs.get("LAST_UPDATED"), raw) not in signatures and (raw is not None or provisional_raw is None):
                releases.append(
                    {
                        **common,
                        "published_at": obs.get("LAST_UPDATED"),
                        "value": value,
                        "value_text": raw,
                        "is_current": True,
                        "is_provisional": False,
                    }
                )
            if provisional_raw is not None:
                releases.append(
                    {
                        **common,
                        "published_at": obs.get("LAST_UPDATED"),
                        "value": provisional,
                        "value_text": provisional_raw,
                        "is_current": True,
                        "is_provisional": True,
                    }
                )
            result.extend(releases)
    return result
