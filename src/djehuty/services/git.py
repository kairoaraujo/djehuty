"""
Shared git repository helpers.

Extracted from ``djehuty.web.wsgi`` so the FastAPI git endpoints (REST
helpers + smart-HTTP protocol) can serve repositories identically to
the legacy implementation.

All functions take whatever state they need as arguments (``db``,
``account_uuid``, ``dataset_id``) and do not depend on the legacy
``ApiServer`` instance.
"""

from __future__ import annotations

import logging
import os

import pygit2

from djehuty.web.config import config


_log = logging.getLogger(__name__)


def default_branch_guess(repository: "pygit2.Repository") -> str | None:
    """Return the repository's default branch, or guess one and persist it.

    Mirrors ``ApiServer.__git_repository_default_branch_guess``.
    """
    branch_name: str | None = None

    head_reference = repository.references.get("HEAD")
    try:
        head_reference = head_reference.resolve() if head_reference else None
    except pygit2.GitError as error:  # pylint: disable=no-member
        _log.error(
            "Failed to resolve git repository HEAD for '%s': %s",
            repository.path, error,
        )
        head_reference = None
    except KeyError as error:
        _log.error(
            "HEAD points to non-existing branch for '%s': %s",
            repository.path, error,
        )
        head_reference = None

    if head_reference is not None:
        try:
            name = head_reference.name
            if name.startswith("refs/heads/"):
                branch_name = name[11:]
        except AttributeError:
            pass

    if branch_name is None:
        branches = list(repository.branches.local)
        if branches:
            branch_name = branches[0]
            if "master" in branches:
                branch_name = "master"
            elif "main" in branches:
                branch_name = "main"
            set_default_branch(repository, branch_name)

    return branch_name


def set_default_branch(repository: "pygit2.Repository", branch_name: str) -> bool:
    """Set the symbolic HEAD reference for the repository."""
    if branch_name is None:
        return False
    try:
        repository.set_head(f"refs/heads/{branch_name}")
        return True
    except (pygit2.GitError, KeyError) as error:  # pylint: disable=no-member
        _log.error(
            "Failed to set default branch '%s' on '%s': %s",
            branch_name, repository.path, error,
        )
        return False


def repository_by_dataset_id(db, account_uuid: str, dataset_id, action: str = "read") -> "pygit2.Repository | None":
    """Resolve a dataset to its git repository (or ``None`` if unavailable).

    Returns ``None`` for any failure: dataset not found / not owned,
    insufficient collaborative ``data_{action}`` permission, git repo directory
    missing, etc. The caller maps this to 404 like the legacy handlers do --
    note legacy deliberately hides a git permission denial as 404, not 403.
    """
    from djehuty.utils.convenience import parses_to_int

    try:
        if parses_to_int(dataset_id):
            datasets = db.datasets(
                dataset_id=int(dataset_id),
                account_uuid=account_uuid,
                is_published=False,
                limit=1,
            )
        else:
            datasets = db.datasets(
                container_uuid=str(dataset_id),
                account_uuid=account_uuid,
                is_published=False,
                limit=1,
            )
        dataset = datasets[0]
    except (IndexError, AttributeError, TypeError):
        _log.error("No Git repository for dataset %s.", dataset_id)
        return None

    # AS-IS: a collaborator needs data_{action} (read/edit). On denial legacy
    # returns None -- the caller renders 404, not 403. Owners are unaffected.
    from djehuty.services.permissions import is_permitted
    if not is_permitted(db, account_uuid, dataset, "dataset", f"data_{action}"):
        return None

    if "git_uuid" not in dataset:
        _log.error("Dataset %s has no git_uuid assigned.", dataset_id)
        return None

    git_directory = os.path.join(config.storage, f"{dataset['git_uuid']}.git")
    if not os.path.exists(git_directory):
        _log.error("No Git repository at '%s'", git_directory)
        return None

    return pygit2.Repository(git_directory)


def repository_by_git_uuid(git_uuid: str) -> "pygit2.Repository | None":
    """Open a repository directly by its git_uuid, no auth check.

    Used by the statistics endpoints (languages, contributors, zip) where
    auth is handled separately.
    """
    git_directory = os.path.join(config.storage, f"{git_uuid}.git")
    if not os.path.exists(git_directory):
        return None
    try:
        return pygit2.Repository(git_directory)
    except pygit2.GitError:  # pylint: disable=no-member
        return None
