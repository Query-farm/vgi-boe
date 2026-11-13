"""Bounded XML parsing with DTDs, entities and external references forbidden."""

from __future__ import annotations

from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from .transport import ApiError


def parse_xml(raw: bytes) -> Element:
    """Parse source bytes while preserving their declared character encoding."""
    try:
        root = fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ParseError, DefusedXmlException, ValueError):
        raise ApiError("API returned invalid or unsafe XML") from None
    if root is None:
        raise ApiError("API returned empty XML")
    return root


def local_name(tag: str) -> str:
    """Read an element's local name independently of a provider's changing host namespace."""
    return tag.rsplit("}", 1)[-1]
