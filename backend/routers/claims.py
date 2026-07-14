from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_session
from ..models import (
    Chore,
    Claim,
    ClaimCreate,
    ClaimKind,
    ClaimMode,
    ClaimRead,
    ClaimResolve,
    ClaimStatus,
    ScheduleKind,
    Transaction,
    TransactionType,
    User,
    UserRole,
    utcnow,
)
from ..permissions import require_admin_role, require_user_role
from ..schedule import is_claimable
from .chores import claim_records_for_chore

router = APIRouter(prefix="/claims", tags=["claims"])


def _to_read(session: Session, claim: Claim) -> ClaimRead:
    def name_of(user_id: int | None) -> str | None:
        if user_id is None:
            return None
        user = session.get(User, user_id)
        return (user.name or user.email) if user else f"user {user_id}"

    chore_name = claim.adhoc_name or ""
    if claim.chore_id is not None:
        chore = session.get(Chore, claim.chore_id)
        chore_name = chore.name if chore else chore_name
    data = claim.model_dump()
    data.update(
        chore_name=chore_name,
        user_name=name_of(claim.user_id),
        submitted_by_name=name_of(claim.submitted_by),
        resolved_by_name=name_of(claim.resolved_by),
    )
    return ClaimRead.model_validate(data)


def _approve(session: Session, claim: Claim, admin: User, resolve: ClaimResolve):
    """Resolve a pending claim as approved and write the ledger row.

    Caller commits — the status change and the transaction land atomically.
    """
    value = resolve.approved_value if resolve.approved_value is not None else claim.original_value
    if claim.kind == ClaimKind.penalty:
        if value >= 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Penalty value must be negative"
            )
        tx_type = TransactionType.penalty
    else:
        if value < 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Approved value cannot be negative (use a penalty claim)",
            )
        tx_type = TransactionType.claim_payout
    claim.status = ClaimStatus.approved
    claim.approved_value = value
    claim.resolution_note = resolve.note
    claim.resolved_by = admin.id
    claim.resolved_at = utcnow()
    session.add(claim)
    session.add(
        Transaction(
            user_id=claim.user_id,
            claim_id=claim.id,
            type=tx_type,
            amount=value,
            created_by=admin.id,
        )
    )


@router.get("", response_model=list[ClaimRead])
def list_claims(
    response: Response,
    status_filter: ClaimStatus | None = None,
    user_id: int | None = None,
    chore_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    query = select(Claim)
    if user.role != UserRole.admin:
        query = query.where(Claim.user_id == user.id)
    else:
        if user_id is not None:
            query = query.where(Claim.user_id == user_id)
        if chore_id is not None:
            query = query.where(Claim.chore_id == chore_id)
    if status_filter is not None:
        query = query.where(Claim.status == status_filter)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    claims = session.exec(
        query.order_by(Claim.submitted_at.desc(), Claim.id.desc())
        .limit(min(limit, 200))
        .offset(offset)
    ).all()
    return [_to_read(session, c) for c in claims]


@router.post("", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
def create_claim(
    body: ClaimCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    is_admin = user.role == UserRole.admin
    admin_features = (
        (body.user_id is not None and body.user_id != user.id)
        or body.kind != ClaimKind.chore
        or body.auto_approve
        or body.create_chore
        or body.value is not None
    )
    if admin_features and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")

    target_id = body.user_id if body.user_id is not None else user.id
    target = session.get(User, target_id)
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target user not found")

    if body.kind == ClaimKind.chore:
        claim = _build_chore_claim(session, body, target)
    else:
        claim = _build_adhoc_claim(session, body, target, admin=user)

    claim.submitted_by = user.id
    claim.original_note = body.note
    session.add(claim)
    if body.auto_approve:
        session.flush()  # claim needs an id for the transaction row
        _approve(session, claim, user, ClaimResolve())
    session.commit()
    session.refresh(claim)
    return _to_read(session, claim)


def _build_chore_claim(session: Session, body: ClaimCreate, target: User) -> Claim:
    if body.chore_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "chore_id required")
    chore = session.get(Chore, body.chore_id)
    if chore is None or not chore.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chore not found")
    records = claim_records_for_chore(session, chore.id)
    if not is_claimable(chore, target.id, records, utcnow()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Chore is not claimable right now"
        )
    return Claim(
        chore_id=chore.id,
        user_id=target.id,
        kind=ClaimKind.chore,
        original_value=chore.value,
        submitted_by=0,  # set by caller
    )


def _build_adhoc_claim(
    session: Session, body: ClaimCreate, target: User, admin: User
) -> Claim:
    if not body.name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "name required for ad-hoc claims"
        )
    if body.value is None or body.value == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "non-zero value required"
        )
    if body.kind == ClaimKind.penalty and body.value > 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Penalty value must be negative"
        )
    if body.kind == ClaimKind.adhoc and body.value < 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ad-hoc value must be positive (use kind=penalty)",
        )
    chore_id = None
    kind = body.kind
    if body.create_chore:
        if body.kind != ClaimKind.adhoc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Only ad-hoc claims can be promoted to a chore",
            )
        chore = Chore(
            name=body.name,
            value=body.value,
            schedule=ScheduleKind.none,
            claim_mode=ClaimMode.per_user,
            created_by=admin.id,
        )
        session.add(chore)
        session.flush()
        chore_id = chore.id
        kind = ClaimKind.chore  # it's an ordinary chore claim from here on
    return Claim(
        chore_id=chore_id,
        user_id=target.id,
        kind=kind,
        adhoc_name=body.name,
        original_value=body.value,
        submitted_by=0,  # set by caller
    )


def _get_pending(session: Session, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if claim.status != ClaimStatus.pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Claim already {claim.status.value}"
        )
    return claim


@router.post("/{claim_id}/approve", response_model=ClaimRead)
def approve_claim(
    claim_id: int,
    body: ClaimResolve,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    claim = _get_pending(session, claim_id)
    _approve(session, claim, admin, body)
    session.commit()
    session.refresh(claim)
    return _to_read(session, claim)


@router.post("/{claim_id}/reject", response_model=ClaimRead)
def reject_claim(
    claim_id: int,
    body: ClaimResolve,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    claim = _get_pending(session, claim_id)
    claim.status = ClaimStatus.rejected
    claim.resolution_note = body.note
    claim.resolved_by = admin.id
    claim.resolved_at = utcnow()
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return _to_read(session, claim)


@router.post("/{claim_id}/cancel", response_model=ClaimRead)
def cancel_claim(
    claim_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    claim = _get_pending(session, claim_id)
    if claim.submitted_by != user.id and user.role != UserRole.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the submitter can cancel a claim"
        )
    claim.status = ClaimStatus.cancelled
    claim.resolved_by = user.id
    claim.resolved_at = utcnow()
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return _to_read(session, claim)
