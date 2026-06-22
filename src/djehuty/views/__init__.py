"""FastAPI UI surface for djehuty (Jinja2-rendered pages).

A faithful AS-IS port of the legacy Werkzeug UI handlers in
``djehuty.web.wsgi``. This package starts with the shared templating
foundation (``templating``) and error pages (``errors``) that every UI page,
and the auth surface, render through. The page handlers (my/admin/review and
the public pages) land on top of it. Part of the wsgi.py -> FastAPI migration.
"""
