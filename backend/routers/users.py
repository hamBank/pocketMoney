from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..database import get_session
from ..ledger import user_read
from ..models import User, UserInvite, UserRead, UserRole, UserUpdate
from ..permissions import require_admin_role

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    users = session.exec(select(User).order_by(User.id)).all()
    return [user_read(session, u) for u in users]


@router.post("/invite", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def invite_user(
    body: UserInvite,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Pre-approve an email so that Google account can sign in later."""
    email = body.email.strip().lower()
    if session.exec(select(User).where(User.email == email)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already exists")
    user = User(email=email, name=body.name, role=body.role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user_read(session, user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (
        changes.get("role") == UserRole.user or changes.get("is_active") is False
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Admins cannot demote or deactivate themselves"
        )
    for field, value in changes.items():
        setattr(user, field, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user_read(session, user)
