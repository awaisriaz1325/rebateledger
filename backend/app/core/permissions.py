"""Named permissions and the role → permission map (SPEC §2.3)."""

from __future__ import annotations

from enum import StrEnum

from app.db.models.identity import Role


class Permission(StrEnum):
    VIEW_DATA = "view_data"
    EXPORT = "export"
    EDIT_SUPPLIERS = "edit_suppliers"
    EDIT_AGREEMENTS = "edit_agreements"
    ACTIVATE_AGREEMENTS = "activate_agreements"
    APPROVE = "approve"
    MANAGE_IMPORTS = "manage_imports"
    RUN_RECONCILIATION = "run_reconciliation"
    EDIT_CLAIMS = "edit_claims"
    WRITE_OFF_CLAIMS = "write_off_claims"
    MANAGE_USERS = "manage_users"
    MANAGE_OWNERS = "manage_owners"
    MANAGE_SETTINGS = "manage_settings"
    VIEW_AUDIT = "view_audit"
    VIEW_BILLING = "view_billing"
    FULL_EXPORT = "full_export"
    DELETE_ORG = "delete_org"
    MANAGE_SUPPORT_ACCESS = "manage_support_access"


P = Permission
_VIEWER = {P.VIEW_DATA, P.EXPORT}
_ANALYST = _VIEWER | {
    P.EDIT_SUPPLIERS,
    P.EDIT_AGREEMENTS,
    P.ACTIVATE_AGREEMENTS,
    P.MANAGE_IMPORTS,
    P.RUN_RECONCILIATION,
    P.EDIT_CLAIMS,
    P.WRITE_OFF_CLAIMS,
}
_ADMIN = _ANALYST | {
    P.APPROVE,
    P.MANAGE_USERS,
    P.MANAGE_SETTINGS,
    P.VIEW_AUDIT,
    P.VIEW_BILLING,
    P.MANAGE_SUPPORT_ACCESS,
}
_OWNER = _ADMIN | {P.MANAGE_OWNERS, P.FULL_EXPORT, P.DELETE_ORG}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(_VIEWER),
    Role.ANALYST: frozenset(_ANALYST),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_OWNER),
}

READ_ONLY_PERMISSIONS = frozenset({P.VIEW_DATA, P.EXPORT})
"""What a read-only support grant or a suspended tenant may still do."""

MFA_REQUIRED_ROLES = frozenset({Role.OWNER, Role.ADMIN})


def permissions_for(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[Role(role)]
