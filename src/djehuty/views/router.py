"""Public UI page routes (faithful AS-IS port of the legacy handlers).

The public, mostly-anonymous pages, ported before the larger my/admin/review
groups: the home/portal page, robots.txt, the sitemap, the themed CSS/SVG
assets, the category/institution/author landing pages, search, the OpenDAP
back-link page, and the feedback and data-access-request forms. Ported from the
matching ``ui_*`` / ``robots_txt`` / ``sitemap`` / ``colors_css`` /
``loader_svg`` handlers in ``djehuty.web.wsgi``.

The dataset and collection landing pages are intentionally left for a later
batch (they are large and central).
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse, Response

from djehuty.web.config import config
from djehuty.web import validator
from djehuty.api.dependencies import get_db
from djehuty.services.content_negotiation import accepts_html, accepts_content_type
from djehuty.services import email as email_service
from djehuty.utils.constants import group_to_member, member_url_names
from djehuty.utils.convenience import value_or, value_or_none
from djehuty.views import errors
from djehuty.views.responses import render_page, render_media

router = APIRouter(include_in_schema=False)

# Cookie name: must match djehuty.views.templating and the legacy server.
COOKIE_KEY = "djehuty_session"


def _email_from_request(db, request: Request):
    """The e-mail of the account behind the request, or None (faithful AS-IS)."""
    account = db.account_by_session_token(request.cookies.get(COOKIE_KEY))
    return account["email"] if account else None


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


@router.get("/browse")
def browse(request: Request):
    """Implements /browse (redirects to the home page like /portal)."""
    if accepts_html(request.headers.get("Accept"), strict=True):
        return RedirectResponse("/", status_code=301)
    return JSONResponse(content={"status": "OK"})


@router.get("/categories/{category_id}")
def ui_categories(category_id: str, request: Request, db=Depends(get_db)):
    """Implements /categories/<id>."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    page_size = request.query_params.get("page_size")
    page      = request.query_params.get("page")
    if page_size is None:
        page_size = 100
    if page is None:
        page = 1

    try:
        offset, limit = validator.paging_to_offset_and_limit({
            "page":      page,
            "page_size": page_size,
        })
        validator.integer_value({"id": category_id}, "id", required=True)
    except validator.ValidationException:
        return errors.error_404(db, request)

    category = db.category_by_id(category_id)
    if category is None:
        return errors.error_404(db, request)

    subcategories = db.subcategories_for_category(category["uuid"])
    datasets      = db.datasets(categories=[category["id"]], limit=limit, offset=offset)
    collections   = db.collections(categories=[category["id"]], limit=100)

    return render_page(db, request, "categories.html",
                       articles=datasets,
                       collections=collections,
                       category=category,
                       subcategories=subcategories)


@router.get("/category")
def ui_category(request: Request, db=Depends(get_db)):
    """Implements /category."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    categories = db.root_categories()
    for category in categories:
        category_id = category["id"]
        category["articles"] = db.datasets(categories=[category_id], limit=5)

    return render_page(db, request, "category.html", categories=categories)


@router.get("/institutions/{institution_name}")
def ui_institution(institution_name: str, request: Request, db=Depends(get_db)):
    """Implements /institutions/<name>."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    group_name    = institution_name.replace('_', ' ')
    group         = db.group_by_name(group_name)
    sub_groups    = db.group_by_name(group_name, startswith=True)
    sub_group_ids = [item['group_id'] for item in sub_groups]
    datasets      = db.datasets(groups=sub_group_ids, is_published=True, limit=100)

    return render_page(db, request, "institutions.html",
                       articles=datasets,
                       group=group,
                       sub_groups=sub_groups)


@router.get("/authors/{author_uuid}")
def ui_author(author_uuid: str, request: Request, db=Depends(get_db)):
    """Implements /authors/<id>."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    if not validator.is_valid_uuid(author_uuid):
        return errors.error_403(db, request)

    author_uri = f'author:{author_uuid}'
    try:
        profile = db.author_profile(author_uri)[0]
        public_items = db.author_public_items(author_uri)
        datasets    = [pi for pi in public_items if pi['is_dataset']]
        collections = [pi for pi in public_items if not pi['is_dataset']]
        associated_authors = db.associated_authors(author_uri)
        member = value_or(group_to_member, value_or_none(profile, 'group_id'), 'other')
        member_url_name = member_url_names[member]
        categories = None
        if 'categories' in profile:
            account_uuid = profile['account'].split(':', 1)[1]
            categories = db.account_categories(account_uuid)
        statistics = {metric: sum(value_or(dataset, metric, 0) for dataset in datasets)
                      for metric in ('downloads', 'views', 'shares', 'cites')}
        statistics = {key: val for (key, val) in statistics.items() if val > 0}
        return render_page(db, request, "author.html",
                           profile=profile,
                           datasets=datasets,
                           collections=collections,
                           associated_authors=associated_authors,
                           member=member,
                           member_url_name=member_url_name,
                           categories=categories,
                           statistics=statistics,
                           page_title=f"{value_or(profile, 'full_name', 'unknown')} (profile)")
    except IndexError:
        return errors.error_404(db, request)


@router.get("/search")
def ui_search(request: Request, db=Depends(get_db)):
    """Implements /search."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    search_for = request.query_params.get("search")
    search_for = validator.string_value(search_for, None, error_on_disallowed_html=False)
    if search_for is None:
        search_for = ""

    search_for = search_for.strip()
    categories = db.categories(limit=None)
    licenses   = db.licenses()
    groups     = db.group()
    return render_page(db, request, "search.html",
                       search_for=search_for,
                       licenses=licenses,
                       institutions=groups,
                       categories=categories,
                       page_title=f"{search_for} (search)")


@router.get("/opendap_to_doi")
def ui_opendap_to_doi(request: Request, db=Depends(get_db)):
    """Establish back-links from OpenDAP by matching the HTTP referrer.

    Lists matching datasets, or redirects when there is exactly one.
    """
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    referrer = request.headers.get("Referer")
    catalog = ""
    dois = []
    if referrer is None:
        referrer = ""
    else:
        catalog = referrer.split('.nl/thredds/', 1)[-1].split('?')[0]
        if catalog.startswith('catalog/data2/IDRA'):
            # IDRA is available at two places. Use the one in the triple store.
            catalog = catalog.replace('catalog/data2/IDRA', 'catalog/IDRA')
    catalog_parts = catalog.split('/')
    # start with this catalog and go broader until something found
    for end_index in range(len(catalog_parts[:-1]), 0, -1):
        catalog_end = '/'.join(catalog_parts[:end_index] + [catalog_parts[-1]])
        dois = db.opendap_to_doi(endswith=catalog_end)
        if dois:
            break
    if not dois:
        # search narrower catalogs (either opendap.4tu.nl or opendap.tudelft.nl)
        catalog_start = [f"https://opendap.4tu.nl/thredds/{ '/'.join(catalog_parts[:-1]) }/",
                         f"https://opendap.tudelft.nl/thredds/{ '/'.join(catalog_parts[:-1]) }/"]
        dois = db.opendap_to_doi(startswith=catalog_start)
    if len(dois) == 1:
        return RedirectResponse(f"https://doi.org/{ dois[0]['doi'] }", status_code=302)

    dois.sort(key=lambda x: x["title"])

    return render_page(db, request, "opendap_to_doi.html", dois=dois, referrer=referrer)


@router.api_route("/feedback", methods=["GET", "POST"])
async def ui_feedback(request: Request, db=Depends(get_db)):
    """Implement /feedback."""
    addresses = db.feedback_reviewer_email_addresses()
    if not addresses:
        return errors.error_404(db, request)

    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    if request.method in ("GET", "HEAD"):
        email = _email_from_request(db, request)
        return render_page(db, request, "feedback.html", email=email)

    if request.method == "POST":
        form = await request.form()
        record = {
            "email":       form.get("email"),
            "type":        form.get("feedback_type"),
            "description": form.get("description")
        }
        try:
            validator.string_value(record, "email", 5, 255, False)
            validator.options_value(record, "type", ["bug", "missing", "other"], True)
            validator.string_value(record, "description", 10, 4096, True, strip_html=False)
        except validator.ValidationException as error:
            email = _email_from_request(db, request)
            return render_page(db, request, "feedback.html",
                               email = email,
                               error_message = error.message)

        subject = "Feedback for Djehuty"
        if record["type"] == "bug":
            subject = "Bug report for Djehuty"
        elif record["type"] == "missing":
            subject = "Missing feature report for Djehuty"

        email_service.send_templated_email(
            db,
            addresses,
            subject,
            "feedback",
            title         = subject,
            email_address = record["email"],
            report_type   = record["type"],
            description   = record["description"])

        return render_page(db, request, "feedback.html",
                           email = record["email"],
                           success_message = "Thank you! Your feedback has been sent.")

    return errors.error_406("text/html")


@router.post("/data_access_request")
async def ui_data_access_request(request: Request, db=Depends(get_db)):
    """Implements /data_access_request."""
    if not accepts_content_type(request.headers.get("Accept"), "application/json", strict=False):
        return errors.error_406("application/json")

    try:
        parameters = await request.json()
        email      = validator.string_value(parameters, "email", required=True)
        name       = validator.string_value(parameters, "name", required=True)
        dataset_id = validator.string_value(parameters, "dataset_id", required=True)
        version    = validator.string_value(parameters, "version", required=True)
        reason     = validator.string_value(parameters, "reason", 0, 10000, required=True, strip_html=False)

        dataset = db.datasets(container_uuid=dataset_id, version=version)[0]

        if not value_or_none(dataset, 'is_confidential') and not (not value_or_none(dataset, 'embargo_until_date') and value_or_none(dataset, 'embargo_type')):
            return errors.error_403(db, request, (f"{email} attempted to request "
                                                  "access to non-confidential "
                                                  f"dataset:{dataset_id}."))

        # When in pre-production state, don't mind about DOI.
        doi = value_or_none(dataset, 'doi')
        if doi is None and config.in_production and not config.in_preproduction:
            return errors.error_403(db, request, f"dataset:{dataset_id} does not have a DOI.")
        title = dataset['title']
        contact_info = db.contact_info_from_container(dataset_id)
        addresses = db.reviewer_email_addresses()

        # When in pre-production state, don't send e-mails to depositors.
        owner_email = None
        if contact_info and config.in_production and not config.in_preproduction:
            owner_email = contact_info['email']
            addresses.append(owner_email)

        email_service.send_templated_email(
            db,
            addresses,
            f"Request from {name} for data access to {doi}",
            "data_access_request",
            requester_email = email,
            requester_name  = name,
            owner_email     = owner_email,
            doi             = doi,
            title           = title,
            reason          = reason)

        return Response(status_code=204)
    except (validator.ValidationException, KeyError):
        pass
    except IndexError:
        return errors.error_400("Dataset does not exist", 400)

    return errors.error_500()
