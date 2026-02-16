import os
import uuid
import mimetypes
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from database import get_db
from models import Conversation, DirectMessage, User, DMReaction, PinnedMessage, Friend, DmReadState
from schemas import DMStart, ConversationOut, DMMessageOut, MessageSend, MessageEdit, UserOut, ReactionOut, PinnedMessageOut, FriendDmOut
from auth import get_current_user

router = APIRouter(prefix="/dms", tags=["direct-messages"])

RUST_SERVICE_URL = os.getenv("RUST_SERVICE_URL", "http://127.0.0.1:8001")
UPLOADS_DM_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "dms")
ATTACHMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "attachments")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "csv", "json", "xml",
    "zip", "tar", "gz", "rar", "7z",
    "mp3", "wav", "ogg", "mp4", "webm", "mov",
}

# Offset DM conversation IDs to avoid key collision with channel IDs in the Rust service
DM_KEY_OFFSET = 1_000_000


async def dm_encrypt(conversation_id: int, plaintext: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RUST_SERVICE_URL}/encrypt",
            json={"channel_id": conversation_id + DM_KEY_OFFSET, "message": plaintext},
            timeout=5.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Encryption service error")
    return resp.json()["encrypted"]


async def dm_decrypt(conversation_id: int, encrypted: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RUST_SERVICE_URL}/decrypt",
            json={"channel_id": conversation_id + DM_KEY_OFFSET, "encrypted": encrypted},
            timeout=5.0,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Decryption service error")
    return resp.json()["message"]


def _get_conversation(db: Session, user: User, conversation_id: int) -> Conversation:
    """Fetch a conversation and verify the user is a participant."""
    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user.id not in (convo.user1_id, convo.user2_id):
        raise HTTPException(status_code=403, detail="Not a participant")
    return convo


def _other_user(convo: Conversation, me: User) -> User:
    return convo.user2 if convo.user1_id == me.id else convo.user1


def _avatar_url(user: User) -> str | None:
    return f"/avatars/{user.avatar}" if user.avatar else None


def _validate_file(filename: str, size: int):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed")
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 10MB")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")


def _get_dm_reactions(db: Session, dm_message_id: int) -> List[ReactionOut]:
    reactions = db.query(DMReaction).filter(DMReaction.dm_message_id == dm_message_id).all()
    emoji_map: dict[str, list[str]] = {}
    for r in reactions:
        emoji_map.setdefault(r.emoji, []).append(r.user.username)
    return [ReactionOut(emoji=e, count=len(users), users=users) for e, users in emoji_map.items()]


def _build_dm_message_out(msg: DirectMessage, plaintext: str, db: Session) -> DMMessageOut:
    attachment_url = None
    if msg.attachment:
        new_path = os.path.join(UPLOADS_DM_DIR, msg.attachment)
        if os.path.exists(new_path):
            attachment_url = f"/uploads/dms/{msg.attachment}"
        else:
            attachment_url = f"/attachments/{msg.attachment}"

    return DMMessageOut(
        id=msg.id,
        content=plaintext,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_username=msg.sender.username,
        sender_display_name=msg.sender.display_name,
        sender_avatar_url=_avatar_url(msg.sender),
        attachment_url=attachment_url,
        attachment_name=msg.attachment_name,
        attachment_size=msg.attachment_size,
        attachment_mime=msg.attachment_mime,
        is_deleted=msg.is_deleted,
        edited_at=msg.edited_at,
        reactions=_get_dm_reactions(db, msg.id),
        created_at=msg.created_at,
    )


@router.get("/users", response_model=List[FriendDmOut])
def list_dm_friends(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """List only friends of the current user with status and unread message counts."""
    friendships = db.query(Friend).filter(Friend.user_id == user.id).all()

    result = []
    for f in friendships:
        friend_user = f.friend

        # Find existing conversation between the two users
        convo = db.query(Conversation).filter(
            or_(
                and_(Conversation.user1_id == user.id, Conversation.user2_id == friend_user.id),
                and_(Conversation.user1_id == friend_user.id, Conversation.user2_id == user.id),
            )
        ).first()

        unread_count = 0
        convo_id = None
        if convo:
            convo_id = convo.id
            # Get the user's read state for this conversation
            read_state = db.query(DmReadState).filter(
                DmReadState.user_id == user.id,
                DmReadState.conversation_id == convo.id,
            ).first()

            # Count messages from the other user after last_read_at
            query = db.query(DirectMessage).filter(
                DirectMessage.conversation_id == convo.id,
                DirectMessage.sender_id == friend_user.id,
                DirectMessage.is_deleted == False,
            )
            if read_state:
                query = query.filter(DirectMessage.created_at > read_state.last_read_at)
            unread_count = query.count()

        result.append(FriendDmOut(
            user_id=friend_user.id,
            username=friend_user.username,
            display_name=friend_user.display_name,
            avatar_url=_avatar_url(friend_user),
            status=friend_user.status or "offline",
            custom_status_text=friend_user.custom_status_text,
            unread_count=unread_count,
            conversation_id=convo_id,
        ))
    return result


@router.post("/", response_model=ConversationOut)
def start_conversation(
    data: DMStart,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a DM with another user by username, or return existing conversation."""
    other = db.query(User).filter(User.username == data.username).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot DM yourself")

    existing = db.query(Conversation).filter(
        or_(
            and_(Conversation.user1_id == user.id, Conversation.user2_id == other.id),
            and_(Conversation.user1_id == other.id, Conversation.user2_id == user.id),
        )
    ).first()

    if existing:
        return ConversationOut(
            id=existing.id,
            other_user_id=other.id,
            other_username=other.username,
            other_display_name=other.display_name,
            other_avatar_url=_avatar_url(other),
            created_at=existing.created_at,
        )

    convo = Conversation(user1_id=user.id, user2_id=other.id)
    db.add(convo)
    db.commit()
    db.refresh(convo)

    return ConversationOut(
        id=convo.id,
        other_user_id=other.id,
        other_username=other.username,
        other_display_name=other.display_name,
        other_avatar_url=_avatar_url(other),
        created_at=convo.created_at,
    )


@router.get("/", response_model=List[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    convos = db.query(Conversation).filter(
        or_(Conversation.user1_id == user.id, Conversation.user2_id == user.id)
    ).all()

    result = []
    for c in convos:
        other = _other_user(c, user)
        result.append(ConversationOut(
            id=c.id,
            other_user_id=other.id,
            other_username=other.username,
            other_display_name=other.display_name,
            other_avatar_url=_avatar_url(other),
            created_at=c.created_at,
        ))
    return result


@router.post("/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a DM conversation as read (updates the read state timestamp)."""
    _get_conversation(db, user, conversation_id)

    read_state = db.query(DmReadState).filter(
        DmReadState.user_id == user.id,
        DmReadState.conversation_id == conversation_id,
    ).first()

    now = datetime.now(timezone.utc)
    if read_state:
        read_state.last_read_at = now
    else:
        read_state = DmReadState(user_id=user.id, conversation_id=conversation_id, last_read_at=now)
        db.add(read_state)

    db.commit()
    return {"detail": "Conversation marked as read"}


@router.get("/{conversation_id}/messages", response_model=List[DMMessageOut])
async def get_dm_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    messages = (
        db.query(DirectMessage)
        .filter(DirectMessage.conversation_id == conversation_id)
        .order_by(DirectMessage.created_at.asc())
        .limit(100)
        .all()
    )

    result = []
    for msg in messages:
        if msg.is_deleted:
            plaintext = "This message was deleted"
        else:
            try:
                plaintext = await dm_decrypt(conversation_id, msg.encrypted_content)
            except Exception:
                plaintext = "[decryption error]"
        result.append(_build_dm_message_out(msg, plaintext, db))
    return result


@router.post("/{conversation_id}/messages", response_model=DMMessageOut, status_code=201)
async def send_dm_message(
    conversation_id: int,
    data: MessageSend,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    encrypted = await dm_encrypt(conversation_id, data.content)

    msg = DirectMessage(
        encrypted_content=encrypted,
        conversation_id=conversation_id,
        sender_id=user.id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return _build_dm_message_out(msg, data.content, db)


@router.post("/{conversation_id}/messages/upload", response_model=DMMessageOut, status_code=201)
async def send_dm_message_with_file(
    conversation_id: int,
    content: str = Form(""),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a DM message with optional file attachment."""
    _get_conversation(db, user, conversation_id)

    attachment_filename = None
    original_filename = None
    file_size = None
    mime_type = None

    if file and file.filename:
        contents = await file.read()
        _validate_file(file.filename, len(contents))

        os.makedirs(UPLOADS_DM_DIR, exist_ok=True)

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
        attachment_filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOADS_DM_DIR, attachment_filename)

        with open(filepath, "wb") as f:
            f.write(contents)

        original_filename = file.filename
        file_size = len(contents)
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    message_text = content.strip() if content else ""
    encrypted = await dm_encrypt(conversation_id, message_text)

    msg = DirectMessage(
        encrypted_content=encrypted,
        conversation_id=conversation_id,
        sender_id=user.id,
        attachment=attachment_filename,
        attachment_name=original_filename,
        attachment_size=file_size,
        attachment_mime=mime_type,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    out = _build_dm_message_out(msg, message_text, db)

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "message",
        "id": msg.id,
        "content": message_text,
        "conversation_id": conversation_id,
        "sender_id": user.id,
        "sender_username": user.username,
        "sender_display_name": user.display_name,
        "sender_avatar_url": _avatar_url(user),
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


# ── DM Message Editing ──

@router.put("/{conversation_id}/messages/{message_id}", response_model=DMMessageOut)
async def edit_dm_message(
    conversation_id: int,
    message_id: int,
    data: MessageEdit,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id, DirectMessage.conversation_id == conversation_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Can only edit your own messages")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")

    now = datetime.now(timezone.utc)
    if (now - msg.created_at.replace(tzinfo=timezone.utc)) > timedelta(minutes=10):
        raise HTTPException(status_code=400, detail="Edit window expired (10 minutes)")

    encrypted = await dm_encrypt(conversation_id, data.content)
    msg.encrypted_content = encrypted
    msg.edited_at = now
    db.commit()
    db.refresh(msg)

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "message_edited",
        "message_id": msg.id,
        "new_content": data.content,
        "edited_at": msg.edited_at.isoformat(),
    })

    return _build_dm_message_out(msg, data.content, db)


# ── DM Message Deletion ──

@router.delete("/{conversation_id}/messages/{message_id}", response_model=DMMessageOut)
async def delete_dm_message(
    conversation_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id, DirectMessage.conversation_id == conversation_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    # In DMs, only sender can delete
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Can only delete your own messages")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Already deleted")

    deleted_text = "This message was deleted"
    encrypted = await dm_encrypt(conversation_id, deleted_text)
    msg.encrypted_content = encrypted
    msg.is_deleted = True
    db.commit()
    db.refresh(msg)

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "message_deleted",
        "message_id": msg.id,
    })

    return _build_dm_message_out(msg, deleted_text, db)


# ── DM Emoji Reactions ──

@router.post("/{conversation_id}/messages/{message_id}/reactions")
async def toggle_dm_reaction(
    conversation_id: int,
    message_id: int,
    emoji: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id, DirectMessage.conversation_id == conversation_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    existing = db.query(DMReaction).filter(
        DMReaction.user_id == user.id, DMReaction.dm_message_id == message_id, DMReaction.emoji == emoji
    ).first()

    if existing:
        db.delete(existing)
    else:
        db.add(DMReaction(user_id=user.id, dm_message_id=message_id, emoji=emoji))

    db.commit()

    count = db.query(DMReaction).filter(DMReaction.dm_message_id == message_id, DMReaction.emoji == emoji).count()

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "reaction_update",
        "message_id": message_id,
        "emoji": emoji,
        "count": count,
        "user": user.username,
        "action": "removed" if existing else "added",
    })

    return {"emoji": emoji, "count": count}


# ── DM Message Search ──

@router.get("/{conversation_id}/messages/search", response_model=List[DMMessageOut])
async def search_dm_messages(
    conversation_id: int,
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    messages = (
        db.query(DirectMessage)
        .filter(DirectMessage.conversation_id == conversation_id, DirectMessage.is_deleted == False)
        .order_by(DirectMessage.created_at.desc())
        .limit(200)
        .all()
    )

    query_lower = q.lower()
    result = []
    for msg in messages:
        try:
            plaintext = await dm_decrypt(conversation_id, msg.encrypted_content)
        except Exception:
            continue
        if query_lower in plaintext.lower():
            result.append(_build_dm_message_out(msg, plaintext, db))

    return result[:50]


# ── DM Pinned Messages ──

@router.post("/{conversation_id}/messages/{message_id}/pin", response_model=PinnedMessageOut)
async def pin_dm_message(
    conversation_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id, DirectMessage.conversation_id == conversation_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    pin_count = db.query(PinnedMessage).filter(PinnedMessage.conversation_id == conversation_id).count()
    if pin_count >= 10:
        raise HTTPException(status_code=400, detail="Maximum 10 pinned messages per conversation")

    existing = db.query(PinnedMessage).filter(
        PinnedMessage.dm_message_id == message_id, PinnedMessage.conversation_id == conversation_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Message already pinned")

    pin = PinnedMessage(dm_message_id=message_id, conversation_id=conversation_id, pinned_by=user.id)
    db.add(pin)
    db.commit()
    db.refresh(pin)

    try:
        content = await dm_decrypt(conversation_id, msg.encrypted_content)
    except Exception:
        content = "[encrypted]"

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "message_pinned",
        "message_id": message_id,
        "pinned_by": user.username,
    })

    return PinnedMessageOut(
        id=pin.id, dm_message_id=message_id, pinned_by=user.id,
        pinned_by_username=user.username, pinned_at=pin.pinned_at,
        content=content, author_username=msg.sender.username,
        author_display_name=msg.sender.display_name,
    )


@router.delete("/{conversation_id}/messages/{message_id}/pin")
async def unpin_dm_message(
    conversation_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    pin = db.query(PinnedMessage).filter(
        PinnedMessage.dm_message_id == message_id, PinnedMessage.conversation_id == conversation_id
    ).first()
    if not pin:
        raise HTTPException(status_code=404, detail="Message not pinned")

    db.delete(pin)
    db.commit()

    from ws_manager import dm_manager
    await dm_manager.broadcast(conversation_id, {
        "type": "message_unpinned",
        "message_id": message_id,
    })

    return {"detail": "Message unpinned"}


@router.get("/{conversation_id}/messages/pinned", response_model=List[PinnedMessageOut])
async def get_pinned_dm_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_conversation(db, user, conversation_id)

    pins = (
        db.query(PinnedMessage)
        .filter(PinnedMessage.conversation_id == conversation_id)
        .order_by(PinnedMessage.pinned_at.desc())
        .all()
    )

    result = []
    for pin in pins:
        msg = pin.dm_message
        if not msg:
            continue
        try:
            content = await dm_decrypt(conversation_id, msg.encrypted_content)
        except Exception:
            content = "[encrypted]"
        result.append(PinnedMessageOut(
            id=pin.id, dm_message_id=msg.id, pinned_by=pin.pinned_by,
            pinned_by_username=pin.pinner.username, pinned_at=pin.pinned_at,
            content=content, author_username=msg.sender.username,
            author_display_name=msg.sender.display_name,
        ))

    return result
