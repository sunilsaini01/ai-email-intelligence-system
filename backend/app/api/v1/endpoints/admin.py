"""
Organization administration (Phase 22): settings, category taxonomy
(FR-23), users/roles/skills (PRD SS6.4 RBAC, FR-42), and GDPR erasure.

Reads that a manager needs to understand system behavior (settings,
taxonomy) are manager-or-admin; every mutation, and anything exposing
other users' accounts, is admin-only -- the same read-open/write-admin
split Phase 19 set for mailbox connections, one role tier higher.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user, require_admin, require_manager
from app.database.session import get_db
from app.feature_engineering.category_keywords import CATEGORY_LABELS
from app.models.user import (
    MEMBERSHIP_ADMIN_VERIFIED,
    MEMBERSHIP_LEGACY_UNVERIFIED,
    ROLE_ADMIN,
    USER_ROLES,
    User,
)
from app.schemas.admin import (
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdate,
    CategoryTaxonomyResponse,
    CategoryTaxonomyUpdate,
    DataSubjectErasureRequest,
    DataSubjectErasureResponse,
    OrganizationSettingsResponse,
    OrganizationSettingsUpdate,
)
from app.schemas.auth import (
    InvitationCreatedResponse,
    InvitationCreateRequest,
    InvitationListResponse,
    InvitationResponse,
)
from app.services.category_taxonomy import FALLBACK_CATEGORY, taxonomy_view
from app.services.membership_service import (
    EmailAlreadyRegistered,
    invitation_status,
    issue_invitation,
    list_invitations,
    revoke_invitation,
)
from app.services.organization_settings_service import (
    ASSIGNMENT_STRATEGIES,
    get_org_settings,
    update_org_settings,
)
from app.services.privacy_service import erase_data_subject

router = APIRouter(prefix="/admin", tags=["Administration"])
logger = logging.getLogger("app.admin")


@router.get("/settings", response_model=OrganizationSettingsResponse)
async def read_settings(
    current_user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)
) -> OrganizationSettingsResponse:
    return OrganizationSettingsResponse(**await get_org_settings(db, current_user.organization_id))


@router.put("/settings", response_model=OrganizationSettingsResponse)
async def write_settings(
    request: OrganizationSettingsUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSettingsResponse:
    if request.assignment_strategy is not None and request.assignment_strategy not in ASSIGNMENT_STRATEGIES:
        raise HTTPException(status_code=422, detail=f"assignment_strategy must be one of {ASSIGNMENT_STRATEGIES}.")

    changes = request.model_dump(exclude_none=True, exclude={"clear_webhook", "clear_retention"})
    if "notification_webhook_url" in changes:
        changes["notification_webhook_url"] = str(changes["notification_webhook_url"])
    if request.clear_webhook:
        changes["notification_webhook_url"] = None
    if request.clear_retention:
        changes["data_retention_days"] = None

    updated = await update_org_settings(db, current_user.organization_id, changes, str(current_user.id))
    logger.info(
        "organization_settings_updated",
        extra={"organization_id": current_user.organization_id, "keys": sorted(changes)},
    )
    return OrganizationSettingsResponse(**updated)


@router.get("/category-taxonomy", response_model=CategoryTaxonomyResponse)
async def read_category_taxonomy(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CategoryTaxonomyResponse:
    """Open to every signed-in user -- the dashboard needs display names."""
    settings = await get_org_settings(db, current_user.organization_id)
    return CategoryTaxonomyResponse(categories=taxonomy_view(settings["category_taxonomy"]))


@router.put("/category-taxonomy", response_model=CategoryTaxonomyResponse)
async def write_category_taxonomy(
    request: CategoryTaxonomyUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CategoryTaxonomyResponse:
    taxonomy: dict = {}
    for entry in request.categories:
        if entry.label not in CATEGORY_LABELS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown category '{entry.label}'. Categories are the model's fixed set {CATEGORY_LABELS}; "
                "a new category needs a retrained model, not a setting.",
            )
        if entry.label == FALLBACK_CATEGORY and not entry.enabled:
            raise HTTPException(status_code=422, detail="General is the fallback category and cannot be disabled.")
        taxonomy[entry.label] = {"display_name": (entry.display_name or "").strip() or None, "enabled": entry.enabled}

    updated = await update_org_settings(
        db, current_user.organization_id, {"category_taxonomy": taxonomy}, str(current_user.id)
    )
    return CategoryTaxonomyResponse(categories=taxonomy_view(updated["category_taxonomy"]))


def _user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        department=user.department,
        skills=list(user.skills or []),
        is_active=user.is_active,
        membership_source=user.membership_source,
        last_assigned_at=user.last_assigned_at,
        created_at=user.created_at,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> AdminUserListResponse:
    users = (
        await db.execute(
            select(User).where(User.organization_id == current_user.organization_id).order_by(User.created_at)
        )
    ).scalars()
    return AdminUserListResponse(users=[_user_response(u) for u in users])


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    request: AdminUserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserResponse:
    user = await db.get(User, user_id)
    if user is None or user.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="User not found.")
    if request.role is not None and request.role not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {USER_ROLES}.")

    # An admin removing their own admin rights (or deactivating
    # themselves) could leave the organization with nobody able to
    # administer it; another admin has to do it.
    if user.id == current_user.id and (
        (request.role is not None and request.role != ROLE_ADMIN) or request.is_active is False
    ):
        raise HTTPException(status_code=409, detail="Admins cannot demote or deactivate themselves.")

    if request.role is not None:
        user.role = request.role
    if request.department is not None:
        user.department = request.department.strip() or None
    if request.clear_department:
        user.department = None
    if request.skills is not None:
        user.skills = sorted({s.strip() for s in request.skills if s.strip()})
    if request.is_active is not None:
        user.is_active = request.is_active
    if request.confirm_membership and user.membership_source == MEMBERSHIP_LEGACY_UNVERIFIED:
        user.membership_source = MEMBERSHIP_ADMIN_VERIFIED
    await db.commit()
    await db.refresh(user)

    logger.info(
        "user_updated_by_admin",
        extra={"user_id": str(user.id), "admin_id": str(current_user.id), "role": user.role},
    )
    return _user_response(user)


@router.post("/privacy/erase", response_model=DataSubjectErasureResponse)
async def erase_subject(
    request: DataSubjectErasureRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DataSubjectErasureResponse:
    """GDPR right to deletion (PRD SS6.4). Permanent. See
    app/services/privacy_service.py for exactly what is and isn't erased."""
    if not request.confirm:
        raise HTTPException(status_code=422, detail="Set confirm=true -- erasure is permanent.")
    deleted = await erase_data_subject(db, current_user.organization_id, request.sender_email)
    logger.info("privacy_erasure_requested", extra={"admin_id": str(current_user.id)})
    return DataSubjectErasureResponse(status="erased", deleted=deleted)


# --- Organization invitations (membership security fix) ---------------------
# Admin-only. The organization is always the admin's own -- no request field
# can point an invitation at, list, or revoke another tenant's invitations.


def _invitation_response(invitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation_status(invitation),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
    )


@router.post("/invitations", response_model=InvitationCreatedResponse, status_code=201)
async def create_invitation(
    request: InvitationCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreatedResponse:
    if request.role not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {USER_ROLES}.")
    try:
        issued = await issue_invitation(db, current_user, request.email, request.role, request.expires_in_hours)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    return InvitationCreatedResponse(
        **_invitation_response(issued.invitation).model_dump(),
        token=issued.token,
        # Token in the URL fragment, not the query string: fragments are
        # never sent to the server, so it stays out of access logs.
        accept_path=f"/accept-invitation#token={issued.token}",
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def get_invitations(
    current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> InvitationListResponse:
    invitations = await list_invitations(db, current_user.organization_id)
    return InvitationListResponse(invitations=[_invitation_response(i) for i in invitations])


@router.delete("/invitations/{invitation_id}", status_code=204)
async def delete_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await revoke_invitation(db, current_user.organization_id, invitation_id):
        raise HTTPException(status_code=404, detail="No open invitation with this id.")
