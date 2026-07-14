from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..database import get_session
from ..models import (
    Chore,
    ChoreCreate,
    ChoreRead,
    ChoreUpdate,
    User,
    UserRole,
    utcnow,
)
from ..permissions import require_admin_role, require_user_role
from ..schedule import ClaimRecord, is_claimable, validate_schedule

router = APIRouter(prefix="/chores", tags=["chores"])


def claim_records_for_chore(session: Session, chore_id: int) -> list[ClaimRecord]:
    # No claim table yet — Phase 3 replaces this with a real query.
    return []


def _validate(chore_data) -> None:
    try:
        validate_schedule(chore_data.schedule, chore_data.schedule_config)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _check_assignees(session: Session, assignee_ids: list[int] | None) -> None:
    if not assignee_ids:
        return
    for user_id in assignee_ids:
        if session.get(User, user_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"No user with id {user_id}"
            )


def _to_read(session: Session, chore: Chore, user: User) -> ChoreRead:
    read = ChoreRead.model_validate(chore)
    read.claimable = is_claimable(
        chore, user.id, claim_records_for_chore(session, chore.id), utcnow()
    )
    return read


@router.get("", response_model=list[ChoreRead])
def list_chores(
    all: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    is_admin = user.role == UserRole.admin
    query = select(Chore).order_by(Chore.id)
    if not (all and is_admin):
        query = query.where(Chore.is_active == True)  # noqa: E712
    chores = session.exec(query).all()
    if not is_admin:
        # Kids only see chores available to them.
        chores = [c for c in chores if not c.assignee_ids or user.id in c.assignee_ids]
    return [_to_read(session, c, user) for c in chores]


@router.get("/{chore_id}", response_model=ChoreRead)
def get_chore(
    chore_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    chore = session.get(Chore, chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chore not found")
    return _to_read(session, chore, user)


@router.post("", response_model=ChoreRead, status_code=status.HTTP_201_CREATED)
def create_chore(
    body: ChoreCreate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    _validate(body)
    _check_assignees(session, body.assignee_ids)
    chore = Chore(**body.model_dump(), created_by=admin.id)
    session.add(chore)
    session.commit()
    session.refresh(chore)
    return _to_read(session, chore, admin)


@router.patch("/{chore_id}", response_model=ChoreRead)
def update_chore(
    chore_id: int,
    body: ChoreUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    chore = session.get(Chore, chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chore not found")
    changes = body.model_dump(exclude_unset=True)

    # Validate the schedule as it will be after the update.
    merged = Chore(**{**chore.model_dump(), **changes})
    _validate(merged)
    _check_assignees(session, changes.get("assignee_ids"))

    for field, value in changes.items():
        setattr(chore, field, value)
    chore.updated_at = utcnow()
    session.add(chore)
    session.commit()
    session.refresh(chore)
    return _to_read(session, chore, admin)


@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_chore(
    chore_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Soft delete — history against the chore is kept (SPEC.md)."""
    chore = session.get(Chore, chore_id)
    if chore is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chore not found")
    chore.is_active = False
    chore.updated_at = utcnow()
    session.add(chore)
    session.commit()
