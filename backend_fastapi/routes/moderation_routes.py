from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Server, User, BannedUser, Channel, Message, server_members
from schemas import KickRequest, BanRequest, BannedUserOut
from auth import get_current_user

router = APIRouter(prefix="/servers/{server_id}/mod", tags=["moderation"])


def _require_owner(db: Session, server_id: int, user: User) -> Server:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only server owner can do this")
    return server


# ── Kick member ──

@router.post("/kick")
def kick_member(
    server_id: int,
    data: KickRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = _require_owner(db, server_id, user)

    if data.user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot kick yourself")

    target = db.query(User).filter(User.id == data.user_id).first()
    if not target or target not in server.members:
        raise HTTPException(status_code=404, detail="User not a member")

    server.members.remove(target)
    db.commit()
    return {"detail": f"{target.username} kicked from server"}


# ── Ban member ──

@router.post("/ban", response_model=BannedUserOut)
def ban_member(
    server_id: int,
    data: BanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = _require_owner(db, server_id, user)

    if data.user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")

    target = db.query(User).filter(User.id == data.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(BannedUser).filter(
        BannedUser.server_id == server_id, BannedUser.user_id == data.user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already banned")

    ban = BannedUser(
        server_id=server_id,
        user_id=data.user_id,
        banned_by=user.id,
        reason=data.reason,
    )
    db.add(ban)

    # Remove from members
    if target in server.members:
        server.members.remove(target)

    db.commit()
    db.refresh(ban)

    return BannedUserOut(
        id=ban.id,
        user_id=ban.user_id,
        username=target.username,
        banned_by=ban.banned_by,
        reason=ban.reason,
        banned_at=ban.banned_at,
    )


# ── Unban ──

@router.delete("/ban/{target_user_id}")
def unban_member(
    server_id: int,
    target_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner(db, server_id, user)

    ban = db.query(BannedUser).filter(
        BannedUser.server_id == server_id, BannedUser.user_id == target_user_id
    ).first()
    if not ban:
        raise HTTPException(status_code=404, detail="User not banned")

    db.delete(ban)
    db.commit()
    return {"detail": "User unbanned"}


# ── List bans ──

@router.get("/bans", response_model=List[BannedUserOut])
def list_bans(
    server_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner(db, server_id, user)

    bans = db.query(BannedUser).filter(BannedUser.server_id == server_id).all()
    return [
        BannedUserOut(
            id=b.id,
            user_id=b.user_id,
            username=b.user.username,
            banned_by=b.banned_by,
            reason=b.reason,
            banned_at=b.banned_at,
        )
        for b in bans
    ]


# ── Lock / Unlock channel ──

@router.post("/channels/{channel_id}/lock")
def lock_channel(
    server_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner(db, server_id, user)

    channel = db.query(Channel).filter(
        Channel.id == channel_id, Channel.server_id == server_id
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.is_locked = True
    db.commit()
    return {"detail": f"#{channel.name} locked"}


@router.post("/channels/{channel_id}/unlock")
def unlock_channel(
    server_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner(db, server_id, user)

    channel = db.query(Channel).filter(
        Channel.id == channel_id, Channel.server_id == server_id
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.is_locked = False
    db.commit()
    return {"detail": f"#{channel.name} unlocked"}


# ── Purge user messages in channel ──

@router.delete("/channels/{channel_id}/purge/{target_user_id}")
async def purge_user_messages(
    server_id: int,
    channel_id: int,
    target_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_owner(db, server_id, user)

    channel = db.query(Channel).filter(
        Channel.id == channel_id, Channel.server_id == server_id
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    from routes.message_routes import encrypt_message
    deleted_text = "This message was deleted"
    encrypted = await encrypt_message(channel_id, deleted_text)

    msgs = db.query(Message).filter(
        Message.channel_id == channel_id,
        Message.user_id == target_user_id,
        Message.is_deleted == False,
    ).all()

    count = 0
    for msg in msgs:
        msg.is_deleted = True
        msg.encrypted_content = encrypted
        count += 1

    db.commit()

    # Broadcast deletions via WS
    from ws_manager import manager
    for msg in msgs:
        await manager.broadcast(channel_id, {
            "type": "message_deleted",
            "message_id": msg.id,
        })

    return {"detail": f"{count} messages purged"}


# ── Get server members (for moderation UI) ──

@router.get("/members")
def list_members(
    server_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member")

    return [
        {
            "id": m.id,
            "username": m.username,
            "display_name": m.display_name,
            "avatar_url": f"/avatars/{m.avatar}" if m.avatar else None,
            "status": m.status or "offline",
            "is_owner": m.id == server.owner_id,
        }
        for m in server.members
    ]
