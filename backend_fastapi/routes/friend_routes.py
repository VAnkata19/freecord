import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List
from database import get_db
from models import User, FriendRequest, Friend, BlockedUser, Notification
from schemas import FriendRequestCreate, FriendRequestOut, FriendOut, BlockedUserOut
from auth import get_current_user

router = APIRouter(prefix="/friends", tags=["friends"])


def _avatar_url(user: User) -> str | None:
    return f"/avatars/{user.avatar}" if user.avatar else None


def _notify_user_ws(user_id: int, payload: dict):
    """Send a WebSocket message to all connections of a specific user."""
    from ws_manager import connected_users
    for ws in list(connected_users.get(user_id, set())):
        try:
            asyncio.get_event_loop().create_task(ws.send_json(payload))
        except Exception:
            pass


def _build_request_out(req: FriendRequest) -> FriendRequestOut:
    return FriendRequestOut(
        id=req.id,
        sender_id=req.sender_id,
        sender_username=req.sender.username,
        sender_display_name=req.sender.display_name,
        sender_avatar_url=_avatar_url(req.sender),
        receiver_id=req.receiver_id,
        receiver_username=req.receiver.username,
        receiver_display_name=req.receiver.display_name,
        receiver_avatar_url=_avatar_url(req.receiver),
        status=req.status,
        created_at=req.created_at,
    )


# ── Send friend request ──

@router.post("/request", response_model=FriendRequestOut, status_code=201)
def send_friend_request(
    data: FriendRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    other = db.query(User).filter(User.username == data.username).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself")

    # Check if blocked
    blocked = db.query(BlockedUser).filter(
        or_(
            and_(BlockedUser.user_id == user.id, BlockedUser.blocked_user_id == other.id),
            and_(BlockedUser.user_id == other.id, BlockedUser.blocked_user_id == user.id),
        )
    ).first()
    if blocked:
        raise HTTPException(status_code=400, detail="Cannot send request to this user")

    # Check if already friends
    existing_friend = db.query(Friend).filter(
        Friend.user_id == user.id, Friend.friend_id == other.id
    ).first()
    if existing_friend:
        raise HTTPException(status_code=400, detail="Already friends")

    # Check for existing pending request in either direction
    existing = db.query(FriendRequest).filter(
        FriendRequest.status == "pending",
        or_(
            and_(FriendRequest.sender_id == user.id, FriendRequest.receiver_id == other.id),
            and_(FriendRequest.sender_id == other.id, FriendRequest.receiver_id == user.id),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Friend request already pending")

    req = FriendRequest(sender_id=user.id, receiver_id=other.id)
    db.add(req)

    # Create notification
    notif = Notification(
        user_id=other.id,
        type="friend_request",
        reference_id=req.id,
        content=f"{user.username} sent you a friend request",
    )
    db.add(notif)
    db.commit()
    db.refresh(req)

    _notify_user_ws(other.id, {
        "type": "friend_request_received",
        "request_id": req.id,
        "sender_id": user.id,
        "sender_username": user.username,
        "sender_display_name": user.display_name,
        "sender_avatar_url": _avatar_url(user),
    })

    return _build_request_out(req)


# ── List pending requests ──

@router.get("/requests/incoming", response_model=List[FriendRequestOut])
def get_incoming_requests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    reqs = db.query(FriendRequest).filter(
        FriendRequest.receiver_id == user.id, FriendRequest.status == "pending"
    ).all()
    return [_build_request_out(r) for r in reqs]


@router.get("/requests/outgoing", response_model=List[FriendRequestOut])
def get_outgoing_requests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    reqs = db.query(FriendRequest).filter(
        FriendRequest.sender_id == user.id, FriendRequest.status == "pending"
    ).all()
    return [_build_request_out(r) for r in reqs]


# ── Accept friend request ──

@router.post("/request/{request_id}/accept", response_model=FriendRequestOut)
def accept_friend_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.query(FriendRequest).filter(FriendRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your request")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request already handled")

    req.status = "accepted"

    # Create bidirectional friendship
    db.add(Friend(user_id=req.sender_id, friend_id=req.receiver_id))
    db.add(Friend(user_id=req.receiver_id, friend_id=req.sender_id))

    db.commit()
    db.refresh(req)

    # Notify the sender that their request was accepted
    _notify_user_ws(req.sender_id, {
        "type": "friend_request_accepted",
        "request_id": req.id,
        "friend_id": user.id,
        "friend_username": user.username,
        "friend_display_name": user.display_name,
        "friend_avatar_url": _avatar_url(user),
        "friend_status": user.status or "offline",
    })

    # Notify the acceptor's own other connections
    sender = req.sender
    _notify_user_ws(user.id, {
        "type": "friend_request_accepted",
        "request_id": req.id,
        "friend_id": sender.id,
        "friend_username": sender.username,
        "friend_display_name": sender.display_name,
        "friend_avatar_url": _avatar_url(sender),
        "friend_status": sender.status or "offline",
    })

    return _build_request_out(req)


# ── Deny friend request ──

@router.post("/request/{request_id}/deny", response_model=FriendRequestOut)
def deny_friend_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.query(FriendRequest).filter(FriendRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your request")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request already handled")

    req.status = "denied"
    db.commit()
    db.refresh(req)

    # Notify the sender that their request was denied
    _notify_user_ws(req.sender_id, {
        "type": "friend_request_denied",
        "request_id": req.id,
        "denier_id": user.id,
        "denier_username": user.username,
    })

    return _build_request_out(req)


# ── Cancel outgoing request ──

@router.delete("/request/{request_id}")
def cancel_friend_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    req = db.query(FriendRequest).filter(FriendRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Not your request")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request already handled")

    db.delete(req)
    db.commit()
    return {"detail": "Request cancelled"}


# ── List friends ──

@router.get("/", response_model=List[FriendOut])
def list_friends(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    friendships = db.query(Friend).filter(Friend.user_id == user.id).all()
    result = []
    for f in friendships:
        friend_user = f.friend
        result.append(FriendOut(
            id=f.id,
            user_id=friend_user.id,
            username=friend_user.username,
            display_name=friend_user.display_name,
            avatar_url=_avatar_url(friend_user),
            status=friend_user.status or "offline",
            custom_status_text=friend_user.custom_status_text,
        ))
    return result


# ── Remove friend ──

@router.delete("/{friend_user_id}")
def remove_friend(
    friend_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Remove both directions
    f1 = db.query(Friend).filter(Friend.user_id == user.id, Friend.friend_id == friend_user_id).first()
    f2 = db.query(Friend).filter(Friend.user_id == friend_user_id, Friend.friend_id == user.id).first()
    if not f1:
        raise HTTPException(status_code=404, detail="Not friends")
    if f1:
        db.delete(f1)
    if f2:
        db.delete(f2)
    db.commit()
    return {"detail": "Friend removed"}


# ── Block user ──

@router.post("/block/{target_user_id}")
def block_user(
    target_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if target_user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(BlockedUser).filter(
        BlockedUser.user_id == user.id, BlockedUser.blocked_user_id == target_user_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already blocked")

    db.add(BlockedUser(user_id=user.id, blocked_user_id=target_user_id))

    # Also remove friendship if exists
    f1 = db.query(Friend).filter(Friend.user_id == user.id, Friend.friend_id == target_user_id).first()
    f2 = db.query(Friend).filter(Friend.user_id == target_user_id, Friend.friend_id == user.id).first()
    if f1:
        db.delete(f1)
    if f2:
        db.delete(f2)

    # Cancel any pending requests
    pending = db.query(FriendRequest).filter(
        FriendRequest.status == "pending",
        or_(
            and_(FriendRequest.sender_id == user.id, FriendRequest.receiver_id == target_user_id),
            and_(FriendRequest.sender_id == target_user_id, FriendRequest.receiver_id == user.id),
        )
    ).all()
    for p in pending:
        db.delete(p)

    db.commit()
    return {"detail": "User blocked"}


# ── Unblock user ──

@router.delete("/block/{target_user_id}")
def unblock_user(
    target_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    block = db.query(BlockedUser).filter(
        BlockedUser.user_id == user.id, BlockedUser.blocked_user_id == target_user_id
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="User not blocked")
    db.delete(block)
    db.commit()
    return {"detail": "User unblocked"}


# ── List blocked ──

@router.get("/blocked", response_model=List[BlockedUserOut])
def list_blocked(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    blocks = db.query(BlockedUser).filter(BlockedUser.user_id == user.id).all()
    return [
        BlockedUserOut(
            id=b.id,
            blocked_user_id=b.blocked_user_id,
            username=b.blocked_user.username,
        )
        for b in blocks
    ]
