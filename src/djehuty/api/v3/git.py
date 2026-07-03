"""Git endpoints for the v3 API.

REST helpers:
  - GET    /v3/datasets/<dataset_id>.git/files
  - GET    /v3/datasets/<dataset_id>.git/branches
  - PUT    /v3/datasets/<dataset_id>.git/set-default-branch

Git smart-HTTP protocol (CGI-style passthrough to git-http-backend):
  - GET    /v3/datasets/<git_uuid>.git
  - GET    /v3/datasets/<git_uuid>.git/info/refs
  - POST   /v3/datasets/<git_uuid>.git/git-upload-pack
  - POST   /v3/datasets/<git_uuid>.git/git-receive-pack

Statistics:
  - GET    /v3/datasets/<git_uuid>.git/languages
  - GET    /v3/datasets/<git_uuid>.git/contributors
  - GET    /v3/datasets/<git_uuid>.git/zip
"""

from __future__ import annotations

import os
import subprocess

import pygit2
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import (
    get_db,
    get_token,
    require_auth,
)
from djehuty.api.exceptions import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
)
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok
from djehuty.services import git as git_service

router = APIRouter(tags=["V3 / Git"])


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------


@router.get(
    "/datasets/{dataset_id}.git/files",
    summary="List files in default branch",
    responses={
        200: _ok("File names in the default branch", ["README.md", "analysis.py"]),
        403: {"model": ErrorResponse},
    },
)
def git_files(
    dataset_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    repository = git_service.repository_by_dataset_id(db, account["uuid"], dataset_id)
    if repository is None:
        raise NotFoundError()

    branch_name = git_service.default_branch_guess(repository)
    files: list = []
    if branch_name:
        try:
            tree = repository.revparse_single(branch_name).tree
            files = [entry.name for entry in tree]
        except pygit2.GitError as error:  # pylint: disable=no-member
            raise InvalidInputError(
                f"Failed to retrieve Git files for '{branch_name}' in '{repository.path}': {error}",
                "GitReadFailed",
            )
    return JSONResponse(content=files)


@router.get(
    "/datasets/{dataset_id}.git/branches",
    summary="List branches + default",
    responses={
        200: _ok(
            "Local branches and the default branch",
            {"default-branch": "main", "branches": ["main", "dev"]},
        ),
        403: {"model": ErrorResponse},
    },
)
def git_branches(
    dataset_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    repository = git_service.repository_by_dataset_id(db, account["uuid"], dataset_id)
    if repository is None:
        raise NotFoundError()

    return JSONResponse(
        content={
            "default-branch": git_service.default_branch_guess(repository),
            "branches": list(repository.branches.local),
        }
    )


@router.put(
    "/datasets/{dataset_id}.git/set-default-branch",
    summary="Set the repository's default branch",
    responses={205: {"description": "Default branch set"}, 403: {"model": ErrorResponse}},
)
def git_set_default_branch(
    dataset_id: str,
    body: dict = Body(
        ...,
        openapi_examples={
            "default": {"summary": "Set the default branch", "value": {"branch": "main"}}
        },
    ),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    # AS-IS: setting the default branch is a write -> requires data_edit.
    repository = git_service.repository_by_dataset_id(
        db, account["uuid"], dataset_id, action="edit"
    )
    if repository is None:
        raise NotFoundError()

    branch_name = body.get("branch") if isinstance(body, dict) else None
    if not isinstance(branch_name, str):
        raise InvalidInputError("Field 'branch' is required.", "BadBranch")
    if branch_name not in repository.branches.local:
        raise InvalidInputError(f"Branch '{branch_name}' does not exist.", "UnknownBranch")

    if not git_service.set_default_branch(repository, branch_name):
        raise InvalidInputError("Failed to set default branch.", "SetDefaultFailed")
    return Response(status_code=205)


# ---------------------------------------------------------------------------
# Smart-HTTP protocol passthrough
#
# git-http-backend(1) is a CGI program shipped with git that handles the
# upload-pack / receive-pack flow. We invoke it as a subprocess and stream
# its stdout back to the client.
# ---------------------------------------------------------------------------


def _git_directory(git_uuid: str) -> str | None:
    """Return the on-disk path of the bare repository, or None if missing."""
    from djehuty.web.config import config

    path = os.path.join(config.storage, f"{git_uuid}.git")
    return path if os.path.exists(path) else None


def _ensure_repo_or_404(git_uuid: str) -> str:
    path = _git_directory(git_uuid)
    if path is None:
        raise NotFoundError()
    return path


def _resolve_repo_for_auth(db, git_uuid: str, token: str | None, write: bool) -> str:
    """Authorise + locate the repository directory.

    Raises NotFoundError when the dataset is missing.
    Raises ForbiddenError when the caller lacks access.
    """
    from djehuty.web import validator

    if not validator.is_valid_uuid(git_uuid):
        raise NotFoundError()

    if token is None:
        raise ForbiddenError("Authentication required.")
    account = db.account_by_session_token(token)
    if account is None:
        raise ForbiddenError("Invalid session.")

    try:
        dataset = db.datasets(
            git_uuid=git_uuid,
            account_uuid=account["uuid"],
            is_published=False,
            limit=1,
        )[0]
    except (IndexError, AttributeError, TypeError):
        raise NotFoundError()

    if write and not bool(dataset.get("may_write", True)):
        raise ForbiddenError("Write access required.")

    path = _git_directory(git_uuid)
    if path is None:
        raise NotFoundError()
    return path


@router.get("/datasets/{git_uuid}.git", summary="Git smart-HTTP instructions")
def git_instructions(git_uuid: str):
    # Legacy returns 404 for non-existent .git URLs to avoid leaking
    # repository existence to unauthenticated probes.
    if _git_directory(git_uuid) is None:
        raise NotFoundError()
    return Response(
        content=(
            "This is a Djehuty-backed git repository.\nUse git clone <url>.git for read access.\n"
        ),
        media_type="text/plain",
    )


def _git_cgi(
    repository_path: str,
    environ: dict,
    body: bytes | None = None,
) -> tuple[int, dict, bytes]:
    """Invoke git-http-backend(1) and capture its (status, headers, body)."""
    env = {**os.environ}
    env.update(environ)
    env["GIT_PROJECT_ROOT"] = os.path.dirname(repository_path)
    env["GIT_HTTP_EXPORT_ALL"] = "1"
    env["PATH_INFO"] = "/" + os.path.basename(repository_path) + env.get("PATH_INFO", "")
    env.pop("HTTP_AUTHORIZATION", None)

    process = subprocess.run(
        ["git", "http-backend"],
        input=body or b"",
        capture_output=True,
        env=env,
        check=False,
    )
    raw = process.stdout
    headers: dict = {}
    status_code = 200
    # CGI response: headers terminated by blank line.
    if b"\r\n\r\n" in raw:
        header_block, payload = raw.split(b"\r\n\r\n", 1)
    elif b"\n\n" in raw:
        header_block, payload = raw.split(b"\n\n", 1)
    else:
        header_block, payload = b"", raw

    for line in header_block.decode("latin-1", errors="replace").splitlines():
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip()
        value = value.strip()
        if name.lower() == "status":
            try:
                status_code = int(value.split()[0])
            except ValueError:
                pass
        else:
            headers[name] = value
    return status_code, headers, payload


@router.get("/datasets/{git_uuid}.git/info/refs", summary="git info/refs")
def git_info_refs(
    git_uuid: str,
    request: Request,
    service: str = Query(..., max_length=64),
    token: str | None = Depends(get_token),
    db=Depends(get_db),
):
    write = service == "git-receive-pack"
    repo_path = _resolve_repo_for_auth(db, git_uuid, token, write=write)
    env = {
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": str(request.url.query),
        "PATH_INFO": "/info/refs",
    }
    status, headers, payload = _git_cgi(repo_path, env)
    return Response(content=payload, status_code=status, headers=headers)


@router.post("/datasets/{git_uuid}.git/git-upload-pack", summary="git-upload-pack")
async def git_upload_pack(
    git_uuid: str,
    request: Request,
    token: str | None = Depends(get_token),
    db=Depends(get_db),
):
    repo_path = _resolve_repo_for_auth(db, git_uuid, token, write=False)
    body = await request.body()
    env = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": request.headers.get(
            "content-type", "application/x-git-upload-pack-request"
        ),
        "CONTENT_LENGTH": str(len(body)),
        "PATH_INFO": "/git-upload-pack",
    }
    status, headers, payload = _git_cgi(repo_path, env, body=body)
    return Response(content=payload, status_code=status, headers=headers)


@router.post("/datasets/{git_uuid}.git/git-receive-pack", summary="git-receive-pack")
async def git_receive_pack(
    git_uuid: str,
    request: Request,
    token: str | None = Depends(get_token),
    db=Depends(get_db),
):
    repo_path = _resolve_repo_for_auth(db, git_uuid, token, write=True)
    body = await request.body()
    env = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": request.headers.get(
            "content-type", "application/x-git-receive-pack-request"
        ),
        "CONTENT_LENGTH": str(len(body)),
        "PATH_INFO": "/git-receive-pack",
    }
    status, headers, payload = _git_cgi(repo_path, env, body=body)
    return Response(content=payload, status_code=status, headers=headers)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@router.get(
    "/datasets/{git_uuid}.git/languages",
    summary="Languages in default branch",
    responses={200: _ok("File-extension counts in the default branch", {"py": 12, "md": 2})},
)
def git_languages(git_uuid: str, db=Depends(get_db)):
    repository = git_service.repository_by_git_uuid(git_uuid)
    if repository is None:
        raise NotFoundError()
    branch_name = git_service.default_branch_guess(repository)
    if not branch_name:
        return JSONResponse(content={})
    try:
        tree = repository.revparse_single(branch_name).tree
    except pygit2.GitError:  # pylint: disable=no-member
        raise NotFoundError()

    languages: dict[str, int] = {}
    for entry in tree:
        if isinstance(entry, pygit2.Tree):  # pylint: disable=no-member
            continue
        ext = os.path.splitext(entry.name)[1].lstrip(".").lower()
        if not ext:
            continue
        languages[ext] = languages.get(ext, 0) + 1
    return JSONResponse(content=languages)


@router.get(
    "/datasets/{git_uuid}.git/contributors",
    summary="Commit-author counts",
    responses={200: _ok("Commit counts per author", {"Ada Lovelace": 42, "Grace Hopper": 7})},
)
def git_contributors(git_uuid: str, db=Depends(get_db)):
    repository = git_service.repository_by_git_uuid(git_uuid)
    if repository is None:
        raise NotFoundError()
    contributors: dict[str, int] = {}
    try:
        for commit in repository.walk(repository.head.target):
            author = commit.author.name or commit.author.email or "unknown"
            contributors[author] = contributors.get(author, 0) + 1
    except (KeyError, pygit2.GitError):  # pylint: disable=no-member
        pass
    return JSONResponse(content=contributors)


@router.get("/datasets/{git_uuid}.git/zip", summary="Default branch as zip")
def git_zip(git_uuid: str, db=Depends(get_db)):
    import io
    import zipfile

    repository = git_service.repository_by_git_uuid(git_uuid)
    if repository is None:
        raise NotFoundError()

    branch_name = git_service.default_branch_guess(repository)
    if not branch_name:
        raise NotFoundError()
    try:
        tree = repository.revparse_single(branch_name).tree
    except pygit2.GitError:  # pylint: disable=no-member
        raise NotFoundError()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        def _walk(t, prefix=""):
            for entry in t:
                if isinstance(entry, pygit2.Tree):  # pylint: disable=no-member
                    _walk(entry, prefix=f"{prefix}{entry.name}/")
                elif isinstance(entry, pygit2.Commit):  # pylint: disable=no-member
                    continue
                else:
                    blob = repository[entry.id]
                    zf.writestr(f"{prefix}{entry.name}", blob.data)

        _walk(tree)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": (f'attachment; filename="{git_uuid}.zip"')},
    )
