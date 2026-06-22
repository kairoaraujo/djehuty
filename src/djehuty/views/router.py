"""Public UI page routes (faithful AS-IS port of the legacy handlers).

Starts with the small, public, mostly-anonymous pages so the rendering pattern
is validated before the larger my/admin/review groups: the home/portal page,
robots.txt, the sitemap, and the themed CSS/SVG assets the rendered pages link
to. Ported from ``ui_home`` / ``ui_redirect_to_home`` / ``robots_txt`` /
``sitemap`` / ``colors_css`` / ``loader_svg`` in ``djehuty.web.wsgi``.
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse

from djehuty.web.config import config
from djehuty.api.dependencies import get_db
from djehuty.services.content_negotiation import accepts_html, accepts_content_type
from djehuty.views import errors
from djehuty.views.responses import render_page, render_media

router = APIRouter(include_in_schema=False)


@router.get("/")
def ui_home(request: Request, db=Depends(get_db)):
    """Implements / (the portal home page)."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    summary_data = db.repository_statistics()
    try:
        for key in summary_data:
            summary_data[key] = f"{int(summary_data[key]):,}"
    except ValueError:
        summary_data = {"datasets": 0, "authors": 0, "collections": 0, "files": 0, "bytes": 0}

    latest = []
    try:
        records = db.latest_datasets_portal(15)
        for rec in records:
            authors = db.authors(item_uri  = rec["dataset_uri"],
                                 item_type = "dataset",
                                 limit     = None)
            pub_date = rec['published_date'][:10]
            url = f'/datasets/{rec["container_uuid"]}'
            latest.append((url, rec['title'], pub_date, authors))
    except (IndexError, KeyError):
        pass

    return render_page(db, request, "portal.html",
                       summary_data = summary_data,
                       latest = latest,
                       notice_message = config.notice_message,
                       show_portal_summary = config.show_portal_summary,
                       show_institutions = config.show_institutions,
                       show_science_categories = config.show_science_categories,
                       show_latest_datasets = config.show_latest_datasets)


@router.get("/portal")
def ui_redirect_to_home(request: Request):
    """Implements /portal."""
    if accepts_html(request.headers.get("Accept"), strict=True):
        return RedirectResponse("/", status_code=301)

    return JSONResponse(content={"status": "OK"})


@router.get("/robots.txt")
def robots_txt():
    """Implements /robots.txt."""
    output = "User-agent: *\n"
    if config.allow_crawlers:
        output += "Allow: /\n"
    else:
        output += "Disallow: /\n"

    output += f"Sitemap: {config.base_url}/sitemap.xml\n"
    response = PlainTextResponse(content=output)
    response.headers["Server"] = config.site_name
    return response


@router.get("/sitemap.xml")
def sitemap(request: Request, db=Depends(get_db)):
    """Implements /sitemap.xml."""
    if not accepts_content_type(request.headers.get("Accept"), "application/xml", strict=False):
        return errors.error_406("application/xml")

    datasets = db.datasets(is_published=True, is_latest=True, limit=50000)
    return render_media("sitemap_template.xml", "application/xml",
                        base_url = config.base_url,
                        datasets = datasets)


@router.get("/theme/colors.css")
def colors_css(request: Request):
    """Implements /theme/colors.css."""
    if not accepts_content_type(request.headers.get("Accept"), "text/css", strict=False):
        return errors.error_406("text/css")

    return render_media("colors.css", "text/css",
                        primary_color            = config.colors['primary-color'],
                        primary_color_hover      = config.colors['primary-color-hover'],
                        primary_color_active     = config.colors['primary-color-active'],
                        primary_foreground_color = config.colors['primary-foreground-color'],
                        footer_background_color  = config.colors['footer-background-color'],
                        privilege_button_color   = config.colors['privilege-button-color'],
                        background_color         = config.colors["background-color"],
                        sandbox_message_css      = config.sandbox_message_css)


@router.get("/theme/loader.svg")
def loader_svg(request: Request):
    """Implements /theme/loader.svg."""
    if not accepts_content_type(request.headers.get("Accept"), "image/svg+xml", strict=False):
        return errors.error_406("image/svg+xml")

    return render_media("loader.svg", "image/svg+xml",
                        primary_color = config.colors["primary-color"])
