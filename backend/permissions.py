from fastapi import Depends, HTTPException, status

from .auth import get_current_user
from .models import User, UserRole


def require_user_role(user: User = Depends(get_current_user)) -> User:
    return user


def require_admin_role(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user
