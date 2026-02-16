import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import UserCreate, UserLogin, UserOut, Token, ProfileUpdate, ProfileOut, StatusUpdate
from auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

AVATARS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "avatars")


def _avatar_url(user: User) -> str | None:
    if user.avatar:
        return f"/avatars/{user.avatar}"
    return None


def _profile_out(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=_avatar_url(user),
        status=user.status or "offline",
        custom_status_text=user.custom_status_text,
        last_activity=user.last_activity,
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, username=user.username, display_name=user.display_name, avatar_url=_avatar_url(user))


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id, user.username)
    return Token(access_token=token)


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(get_current_user)):
    return _profile_out(user)


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.display_name is not None:
        user.display_name = data.display_name.strip() or None
    db.commit()
    db.refresh(user)
    return _profile_out(user)


@router.put("/status", response_model=ProfileOut)
def update_status(
    data: StatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually set user status (online, idle, dnd, offline) with optional custom text."""
    if data.status not in ("online", "idle", "dnd", "offline"):
        raise HTTPException(status_code=400, detail="Invalid status")
    user.status = data.status
    if data.custom_status_text is not None:
        user.custom_status_text = data.custom_status_text.strip() or None
    user.last_activity = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _profile_out(user)


@router.post("/avatar", response_model=ProfileOut)
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    allowed = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Only PNG, JPEG, GIF, or WebP images allowed")

    contents = file.file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 10MB")

    if user.avatar:
        old_path = os.path.join(AVATARS_DIR, user.avatar)
        if os.path.exists(old_path):
            os.remove(old_path)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    filename = f"{user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(AVATARS_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    user.avatar = filename
    db.commit()
    db.refresh(user)
    return _profile_out(user)
