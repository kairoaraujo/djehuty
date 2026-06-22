"""Unit tests for the collaborative-permission check (djehuty.api.permissions).

These pin the faithful behaviour of the legacy
``__needs_collaborative_permissions``: a no-op for the owner, and a 403
(ForbiddenError) for a collaborator who lacks the required permission.
"""

import pytest

from djehuty.api.exceptions import ForbiddenError
from djehuty.api.permissions import enforce_collaborative_permissions
from djehuty.services.permissions import is_permitted


class FakeDB:
    def __init__(self, perms):
        self._perms = perms
        self.calls = 0

    def item_collaborative_permissions(self, item_type, item_uuid, account_uuid):
        self.calls += 1
        return self._perms


def test_owner_path_is_a_noop_and_skips_the_db():
    # is_shared_with_me absent -> owner path -> no enforcement, no db lookup.
    db = FakeDB({"metadata_edit": False})
    item = {"uuid": "d1"}
    assert enforce_collaborative_permissions(db, "acc", item, "dataset", "metadata_edit") is None
    assert db.calls == 0


def test_collaborator_with_permission_passes():
    item = {"uuid": "d1", "is_shared_with_me": True}
    db = FakeDB({"metadata_read": True, "metadata_edit": True})
    # Does not raise when the collaborator holds the required permission.
    enforce_collaborative_permissions(db, "acc", item, "dataset", "metadata_edit")


def test_collaborator_without_permission_is_forbidden():
    item = {"uuid": "d1", "is_shared_with_me": True}
    db = FakeDB({"metadata_read": True, "metadata_edit": False})
    with pytest.raises(ForbiddenError):
        enforce_collaborative_permissions(db, "acc", item, "dataset", "metadata_edit")


def test_collaborator_with_no_record_is_forbidden():
    item = {"uuid": "d1", "is_shared_with_me": True}
    with pytest.raises(ForbiddenError):
        enforce_collaborative_permissions(FakeDB(None), "acc", item, "dataset", "data_read")


def test_all_listed_permissions_are_required():
    item = {"uuid": "d1", "is_shared_with_me": True}
    db = FakeDB({"metadata_read": True, "metadata_edit": False})
    with pytest.raises(ForbiddenError):
        enforce_collaborative_permissions(
            db, "acc", item, "dataset", ["metadata_read", "metadata_edit"]
        )


def test_shared_item_without_uuid_is_forbidden():
    item = {"is_shared_with_me": True}  # no uuid
    with pytest.raises(ForbiddenError):
        enforce_collaborative_permissions(FakeDB({}), "acc", item, "dataset", "metadata_read")


# --- neutral decision logic (services.permissions.is_permitted) -------------

def test_is_permitted_owner_true_without_db():
    db = FakeDB(None)
    assert is_permitted(db, "acc", {"uuid": "d1"}, "dataset", "data_edit") is True
    assert db.calls == 0


def test_is_permitted_collaborator_with_permission_true():
    item = {"uuid": "d1", "is_shared_with_me": True}
    assert is_permitted(FakeDB({"data_read": True}), "acc", item, "file", "data_read") is True


def test_is_permitted_collaborator_without_permission_false():
    item = {"uuid": "d1", "is_shared_with_me": True}
    assert is_permitted(FakeDB({"data_read": False}), "acc", item, "file", "data_read") is False
