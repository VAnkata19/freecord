import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Server, ServerInvite, User, Notification, server_members, BannedUser
from schemas import InviteCreate, InviteOut, InviteJoin, ServerOut
from auth import get_current_user

router = APIRouter(prefix="/invites", tags=["invites"])


def _build_invite_out(inv: ServerInvite) -> InviteOut:
    return InviteOut(
        id=inv.id,
        server_id=inv.server_id,
        server_name=inv.server.name,
        code=inv.code,
        expires_at=inv.expires_at,
        max_uses=inv.max_uses,
        uses=inv.uses,
        created_by=inv.created_by,
        created_at=inv.created_at,
    )


@router.post("/servers/{server_id}", response_model=InviteOut, status_code=201)
def create_invite(
    server_id: int,
    data: InviteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member")

    expires_at = None
    if data.expires_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=data.expires_hours)

    code = secrets.token_urlsafe(8)
    invite = ServerInvite(
        server_id=server_id,
        code=code,
        expires_at=expires_at,
        max_uses=data.max_uses,
        created_by=user.id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return _build_invite_out(invite)


@router.get("/servers/{server_id}", response_model=List[InviteOut])
def list_invites(
    server_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member")

    invites = db.query(ServerInvite).filter(ServerInvite.server_id == server_id).all()
    return [_build_invite_out(i) for i in invites]


@router.post("/join", response_model=ServerOut)
def join_via_invite(
    data: InviteJoin,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invite = db.query(ServerInvite).filter(ServerInvite.code == data.code).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    # Check expiration
    if invite.expires_at and datetime.now(timezone.utc) > invite.expires_at.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=400, detail="Invite has expired")

    # Check max uses
    if invite.max_uses and invite.uses >= invite.max_uses:
        raise HTTPException(status_code=400, detail="Invite has reached max uses")

    server = invite.server

    # Check if banned
    banned = db.query(BannedUser).filter(
        BannedUser.server_id == server.id, BannedUser.user_id == user.id
    ).first()
    if banned:
        raise HTTPException(status_code=403, detail="You are banned from this server")

    # Join if not already member
    if user not in server.members:
        server.members.append(user)
        invite.uses += 1
        db.commit()

    return server


@router.get("/info/{code}", response_model=InviteOut)
def get_invite_info(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invite = db.query(ServerInvite).filter(ServerInvite.code == code).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    return _build_invite_out(invite)


@router.delete("/{invite_id}")
def delete_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    invite = db.query(ServerInvite).filter(ServerInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    server = invite.server
    if server.owner_id != user.id and invite.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only server owner or invite creator can delete")

    db.delete(invite)
    db.commit()
    return {"detail": "Invite deleted"}
