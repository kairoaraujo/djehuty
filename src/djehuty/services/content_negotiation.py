"""Framework-neutral HTTP content-negotiation helpers (faithful port).

Extracted AS-IS from ``djehuty.web.wsgi`` (``accepts_content_type`` /
``accepts_html`` / ``accepts_xml`` ...). Callers pass the raw ``Accept`` header
string (``None`` when absent) instead of a framework request object.
"""


def accepts_content_type(accept_header, content_type, strict=True) -> bool:
    """Whether the client accepts ``content_type``.

    A missing ``Accept`` header is treated as ``*/*`` -- accepted unless strict,
    exactly as legacy did (its ``KeyError`` branch returns ``not strict``).
    """
    if accept_header is None:
        return not strict
    if not accept_header:
        return False

    exact_match = content_type in accept_header
    if strict:
        return exact_match

    global_match = "*/*" in accept_header
    return global_match or exact_match


def accepts_html(accept_header, strict=False) -> bool:
    """Whether the client accepts ``text/html``."""
    return accepts_content_type(accept_header, "text/html", strict=strict)


def accepts_xml(accept_header) -> bool:
    """Whether the client accepts XML."""
    return (accepts_content_type(accept_header, "application/xml") or
            accepts_content_type(accept_header, "text/xml"))
