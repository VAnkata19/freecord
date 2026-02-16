import os
import re
import uuid
import mimetypes
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from database import get_db
from models import Message, Channel, Server, User, Reaction, PinnedMessage, Notification
from schemas import MessageSend, MessageEdit, MessageOut, ReactionOut, PinnedMessageOut
from auth import get_current_user

router = APIRouter(prefix="/servers/{server_id}/channels/{channel_id}/messages", tags=["messages"])

RUST_SERVICE_URL = os.getenv("RUST_SERVICE_URL", "http://127.0.0.1:8001")
UPLOADS_CHANNEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "channels")
# Keep old dir for backward compat serving
ATTACHMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "attachments")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "csv", "json", "xml",
    "zip", "tar", "gz", "rar", "7z",
    "mp3", "wav", "ogg", "mp4", "webm", "mov",
}


async def encrypt_message(channel_id: int, plaintext: str) -> str:
    """Call the Rust encryption service to encrypt a message."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RUST_SERVICE_URL}/encrypt",
            json={"channel_id": channel_id, "message": plaintext},
            timeout=5.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Encryption service error")
    return resp.json()["encrypted"]


async def decrypt_message(channel_id: int, encrypted: str) -> str:
    """Call the Rust encryption service to decrypt a message."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RUST_SERVICE_URL}/decrypt",
            json={"channel_id": channel_id, "encrypted": encrypted},
            timeout=5.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Decryption service error")
    return resp.json()["message"]


def _validate_file(filename: str, size: int):
    """Validate file extension and size."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed")
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 10MB")
    # Path traversal prevention
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")


def _get_reactions(db: Session, message_id: int) -> List[ReactionOut]:
    """Get aggregated reactions for a message."""
    reactions = db.query(Reaction).filter(Reaction.message_id == message_id).all()
    emoji_map: dict[str, list[str]] = {}
    for r in reactions:
        emoji_map.setdefault(r.emoji, []).append(r.user.username)
    return [ReactionOut(emoji=e, count=len(users), users=users) for e, users in emoji_map.items()]


def _build_message_out(msg: Message, plaintext: str, db: Session) -> MessageOut:
    """Build a MessageOut from a Message model instance."""
    # Determine attachment URL based on where file is stored
    attachment_url = None
    if msg.attachment:
        # Check if file is in new uploads dir or old attachments dir
        new_path = os.path.join(UPLOADS_CHANNEL_DIR, msg.attachment)
        if os.path.exists(new_path):
            attachment_url = f"/uploads/channels/{msg.attachment}"
        else:
            attachment_url = f"/attachments/{msg.attachment}"

    return MessageOut(
        id=msg.id,
        content=plaintext,
        channel_id=msg.channel_id,
        user_id=msg.user_id,
        username=msg.user.username,
        display_name=msg.user.display_name,
        avatar_url=f"/avatars/{msg.user.avatar}" if msg.user.avatar else None,
        attachment_url=attachment_url,
        attachment_name=msg.attachment_name,
        attachment_size=msg.attachment_size,
        attachment_mime=msg.attachment_mime,
        is_deleted=msg.is_deleted,
        edited_at=msg.edited_at,
        reactions=_get_reactions(db, msg.id),
        created_at=msg.created_at,
    )


def _verify_channel_access(db: Session, server_id: int, channel_id: int, user: User):
    """Verify channel exists, belongs to server, and user is a member."""
    channel = db.query(Channel).filter(
        Channel.id == channel_id, Channel.server_id == server_id
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    server = db.query(Server).filter(Server.id == server_id).first()
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member")
    return channel, server


def _detect_mentions(content: str, db: Session, sender: User, channel_id: int, server: Server):
    """Detect @username and @everyone mentions, create notifications."""
    # @everyone - admin only
    if "@everyone" in content and sender.id == server.owner_id:
        for member in server.members:
            if member.id != sender.id:
                db.add(Notification(
                    user_id=member.id,
                    type="mention",
                    reference_id=channel_id,
                    content=f"{sender.username} mentioned @everyone in #{db.query(Channel).get(channel_id).name}",
                ))

    # @username mentions
    mentions = re.findall(r"@(\w+)", content)
    for uname in set(mentions):
        if uname == "everyone":
            continue
        mentioned = db.query(User).filter(User.username == uname).first()
        if mentioned and mentioned.id != sender.id:
            db.add(Notification(
                user_id=mentioned.id,
                type="mention",
                reference_id=channel_id,
                content=f"{sender.username} mentioned you in #{db.query(Channel).get(channel_id).name}",
            ))


@router.post("/", response_model=MessageOut, status_code=201)
async def send_message(
    server_id: int,
    channel_id: int,
    data: MessageSend,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel, server = _verify_channel_access(db, server_id, channel_id, user)

    if channel.is_locked and server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Channel is locked")

    encrypted = await encrypt_message(channel_id, data.content)

    msg = Message(
        encrypted_content=encrypted,
        channel_id=channel_id,
        user_id=user.id,
    )
    db.add(msg)

    _detect_mentions(data.content, db, user, channel_id, server)

    db.commit()
    db.refresh(msg)

    return _build_message_out(msg, data.content, db)


@router.get("/", response_model=List[MessageOut])
async def get_messages(
    server_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _verify_channel_access(db, server_id, channel_id, user)

    messages = (
        db.query(Message)
        .filter(Message.channel_id == channel_id)
        .order_by(Message.created_at.asc())
        .limit(100)
        .all()
    )

    result = []
    for msg in messages:
        if msg.is_deleted:
            plaintext = "This message was deleted"
        else:
            try:
                plaintext = await decrypt_message(channel_id, msg.encrypted_content)
            except Exception:
                plaintext = "[decryption error]"
        result.append(_build_message_out(msg, plaintext, db))

    return result


@router.post("/upload", response_model=MessageOut, status_code=201)
async def send_message_with_file(
    server_id: int,
    channel_id: int,
    content: str = Form(""),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a message with optional file attachment."""
    channel, server = _verify_channel_access(db, server_id, channel_id, user)

    if channel.is_locked and server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Channel is locked")

    attachment_filename = None
    original_filename = None
    file_size = None
    mime_type = None

    if file and file.filename:
        contents = await file.read()
        _validate_file(file.filename, len(contents))

        os.makedirs(UPLOADS_CHANNEL_DIR, exist_ok=True)

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
        attachment_filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOADS_CHANNEL_DIR, attachment_filename)

        with open(filepath, "wb") as f:
            f.write(contents)

        original_filename = file.filename
        file_size = len(contents)
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    message_text = content.strip() if content else ""
    encrypted = await encrypt_message(channel_id, message_text)

    msg = Message(
        encrypted_content=encrypted,
        channel_id=channel_id,
        user_id=user.id,
        attachment=attachment_filename,
        attachment_name=original_filename,
        attachment_size=file_size,
        attachment_mime=mime_type,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    _detect_mentions(message_text, db, user, channel_id, server)
    db.commit()
    db.refresh(msg)

    out = _build_message_out(msg, message_text, db)

    # Broadcast to all WebSocket clients in this channel
    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "message",
        "id": msg.id,
        "content": message_text,
        "channel_id": channel_id,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": out.avatar_url,
        "attachment_url": out.attachment_url,
        "attachment_name": msg.attachment_name,
        "attachment_size": msg.attachment_size,
        "attachment_mime": msg.attachment_mime,
        "is_deleted": False,
        "edited_at": None,
        "reactions": [],
        "created_at": msg.created_at.isoformat(),
    })

    return out


# ── Message Editing ──

@router.put("/{message_id}", response_model=MessageOut)
async def edit_message(
    server_id: int,
    channel_id: int,
    message_id: int,
    data: MessageEdit,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _verify_channel_access(db, server_id, channel_id, user)

    msg = db.query(Message).filter(Message.id == message_id, Message.channel_id == channel_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.user_id != user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own messages")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")

    # 10-minute edit window
    now = datetime.now(timezone.utc)
    if (now - msg.created_at.replace(tzinfo=timezone.utc)) > timedelta(minutes=10):
        raise HTTPException(status_code=400, detail="Edit window expired (10 minutes)")

    encrypted = await encrypt_message(channel_id, data.content)
    msg.encrypted_content = encrypted
    msg.edited_at = now
    db.commit()
    db.refresh(msg)

    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "message_edited",
        "message_id": msg.id,
        "new_content": data.content,
        "edited_at": msg.edited_at.isoformat(),
    })

    return _build_message_out(msg, data.content, db)


# ── Message Deletion ──

@router.delete("/{message_id}", response_model=MessageOut)
async def delete_message(
    server_id: int,
    channel_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, server = _verify_channel_access(db, server_id, channel_id, user)

    msg = db.query(Message).filter(Message.id == message_id, Message.channel_id == channel_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Users can delete own messages; server owner (admin) can delete any
    if msg.user_id != user.id and server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot delete this message")

    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Already deleted")

    # Soft delete
    deleted_text = "This message was deleted"
    encrypted = await encrypt_message(channel_id, deleted_text)
    msg.encrypted_content = encrypted
    msg.is_deleted = True
    db.commit()
    db.refresh(msg)

    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "message_deleted",
        "message_id": msg.id,
    })

    return _build_message_out(msg, deleted_text, db)


# ── Emoji Reactions ──

@router.post("/{message_id}/reactions")
async def toggle_reaction(
    server_id: int,
    channel_id: int,
    message_id: int,
    emoji: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _verify_channel_access(db, server_id, channel_id, user)

    msg = db.query(Message).filter(Message.id == message_id, Message.channel_id == channel_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    existing = db.query(Reaction).filter(
        Reaction.user_id == user.id, Reaction.message_id == message_id, Reaction.emoji == emoji
    ).first()

    if existing:
        db.delete(existing)
    else:
        db.add(Reaction(user_id=user.id, message_id=message_id, emoji=emoji))

    db.commit()

    # Get updated count
    count = db.query(Reaction).filter(Reaction.message_id == message_id, Reaction.emoji == emoji).count()

    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "reaction_update",
        "message_id": message_id,
        "emoji": emoji,
        "count": count,
        "user": user.username,
        "action": "removed" if existing else "added",
    })

    return {"emoji": emoji, "count": count}


# ── Message Search ──

@router.get("/search", response_model=List[MessageOut])
async def search_messages(
    server_id: int,
    channel_id: int,
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _verify_channel_access(db, server_id, channel_id, user)

    messages = (
        db.query(Message)
        .filter(Message.channel_id == channel_id, Message.is_deleted == False)
        .order_by(Message.created_at.desc())
        .limit(200)
        .all()
    )

    query_lower = q.lower()
    result = []
    for msg in messages:
        try:
            plaintext = await decrypt_message(channel_id, msg.encrypted_content)
        except Exception:
            continue
        if query_lower in plaintext.lower():
            result.append(_build_message_out(msg, plaintext, db))

    return result[:50]  # Cap results


# ── Pinned Messages ──

@router.post("/{message_id}/pin", response_model=PinnedMessageOut)
async def pin_message(
    server_id: int,
    channel_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, server = _verify_channel_access(db, server_id, channel_id, user)

    # Only server owner can pin in channels
    if server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only server owner can pin messages")

    msg = db.query(Message).filter(Message.id == message_id, Message.channel_id == channel_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # Check max 10
    pin_count = db.query(PinnedMessage).filter(PinnedMessage.channel_id == channel_id).count()
    if pin_count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 pinned messages per channel")

    # Check already pinned
    existing = db.query(PinnedMessage).filter(
        PinnedMessage.message_id == message_id, PinnedMessage.channel_id == channel_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Message already pinned")

    pin = PinnedMessage(message_id=message_id, channel_id=channel_id, pinned_by=user.id)
    db.add(pin)
    db.commit()
    db.refresh(pin)

    try:
        content = await decrypt_message(channel_id, msg.encrypted_content)
    except Exception:
        content = "[encrypted]"

    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "message_pinned",
        "message_id": message_id,
        "pinned_by": user.username,
    })

    return PinnedMessageOut(
        id=pin.id, message_id=message_id, pinned_by=user.id,
        pinned_by_username=user.username, pinned_at=pin.pinned_at,
        content=content, author_username=msg.user.username,
        author_display_name=msg.user.display_name,
    )


@router.delete("/{message_id}/pin")
async def unpin_message(
    server_id: int,
    channel_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _, server = _verify_channel_access(db, server_id, channel_id, user)

    if server.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only server owner can unpin messages")

    pin = db.query(PinnedMessage).filter(
        PinnedMessage.message_id == message_id, PinnedMessage.channel_id == channel_id
    ).first()
    if not pin:
        raise HTTPException(status_code=404, detail="Message not pinned")

    db.delete(pin)
    db.commit()

    from ws_manager import manager
    await manager.broadcast(channel_id, {
        "type": "message_unpinned",
        "message_id": message_id,
    })

    return {"detail": "Message unpinned"}


@router.get("/pinned", response_model=List[PinnedMessageOut])
async def get_pinned_messages(
    server_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _verify_channel_access(db, server_id, channel_id, user)

    pins = (
        db.query(PinnedMessage)
        .filter(PinnedMessage.channel_id == channel_id)
        .order_by(PinnedMessage.pinned_at.desc())
        .all()
    )

    result = []
    for pin in pins:
        msg = pin.message
        if not msg:
            continue
        try:
            content = await decrypt_message(channel_id, msg.encrypted_content)
        except Exception:
            content = "[encrypted]"
        result.append(PinnedMessageOut(
            id=pin.id, message_id=msg.id, pinned_by=pin.pinned_by,
            pinned_by_username=pin.pinner.username, pinned_at=pin.pinned_at,
            content=content, author_username=msg.user.username,
            author_display_name=msg.user.display_name,
        ))

    return result
