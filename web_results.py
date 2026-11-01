"""Validate web result links and extract provider-originated citation spans."""

import ipaddress
from urllib.parse import urlsplit
from provider import ProviderError


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid page URL.")
    p = urlsplit(value)
    if (
        p.scheme not in {"https", "http"}
        or not p.hostname
        or p.username
        or p.password
        or "\\" in value
    ):
        raise ValueError("Use a public HTTP or HTTPS page URL.")
    if p.hostname == "localhost" or p.hostname.endswith((".local", ".internal")):
        raise ValueError("Local/private pages are not supported by this web card.")
    try:
        if not ipaddress.ip_address(p.hostname).is_global:
            raise ValueError("Private addresses are not supported.")
    except ValueError as exc:
        if "supported" in str(exc):
            raise
    return value


def research_result(response):
    if response.get("status") not in {None, "completed"}:
        raise ProviderError("Research did not complete. Try a narrower question.")
    searched = any(o.get("type") == "web_search_call" for o in response.get("output", []))
    text = ""
    citations = []
    for output in response.get("output", []):
        for part in output.get("content", []):
            if part.get("type") != "output_text":
                continue
            value = part.get("text", "")
            offset = len(text)
            if not isinstance(value, str):
                continue
            for annotation in part.get("annotations", []):
                if annotation.get("type") != "url_citation":
                    continue
                try:
                    url = safe_url(annotation.get("url"))
                    start, end = annotation["start_index"], annotation["end_index"]
                    if (
                        type(start) is not int
                        or type(end) is not int
                        or not 0 <= start < end <= len(value)
                    ):
                        continue
                    citations.append(
                        {
                            "url": url,
                            "title": str(annotation.get("title") or url)[:180],
                            "start": offset + start,
                            "end": offset + end,
                        }
                    )
                except (ValueError, KeyError, TypeError):
                    continue
            text += value + "\n"
    if not searched or not text.strip() or not citations or len(text) > 20000:
        raise ProviderError(
            "Research returned no usable cited answer. No unsourced result was substituted."
        )
    return {"text": text.strip(), "citations": citations[:24], "searched": True}
