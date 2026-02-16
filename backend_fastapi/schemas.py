from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


# ── Auth ──

class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = "offline"
    custom_status_text: Optional[str] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Profile ──

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None

class ProfileOut(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = "offline"
    custom_status_text: Optional[str] = None
    last_activity: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── User Status ──

class StatusUpdate(BaseModel):
    status: str  # online, idle, dnd, offline
    custom_status_text: Optional[str] = None


# ── Servers ──

class ServerCreate(BaseModel):
    name: str

class ServerOut(BaseModel):
    id: int
    name: str
    owner_id: int

    class Config:
        from_attributes = True


# ── Channels ──

class ChannelCreate(BaseModel):
    name: str

class ChannelOut(BaseModel):
    id: int
    name: str
    server_id: int
    is_locked: bool = False

    class Config:
        from_attributes = True


# ── Reactions ──

class ReactionOut(BaseModel):
    emoji: str
    count: int
    users: List[str]  # list of usernames


# ── Messages ──

class MessageSend(BaseModel):
    content: str

class MessageEdit(BaseModel):
    content: str

class MessageOut(BaseModel):
    id: int
    content: str
    channel_id: int
    user_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_size: Optional[int] = None
    attachment_mime: Optional[str] = None
    is_deleted: bool = False
    edited_at: Optional[datetime] = None
    reactions: List[ReactionOut] = []
    created_at: datetime

    class Config:
        from_attributes = True


# ── Direct Messages ──

class DMStart(BaseModel):
    username: str

class ConversationOut(BaseModel):
    id: int
    other_user_id: int
    other_username: str
    other_display_name: Optional[str] = None
    other_avatar_url: Optional[str] = None
    created_at: datetime

class DMMessageOut(BaseModel):
    id: int
    content: str
    conversation_id: int
    sender_id: int
    sender_username: str
    sender_display_name: Optional[str] = None
    sender_avatar_url: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_size: Optional[int] = None
    attachment_mime: Optional[str] = None
    is_deleted: bool = False
    edited_at: Optional[datetime] = None
    reactions: List[ReactionOut] = []
    created_at: datetime


# ── Friend System ──

class FriendRequestCreate(BaseModel):
    username: str

class FriendRequestOut(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    sender_display_name: Optional[str] = None
    sender_avatar_url: Optional[str] = None
    receiver_id: int
    receiver_username: str
    receiver_display_name: Optional[str] = None
    receiver_avatar_url: Optional[str] = None
    status: str
    created_at: datetime

class FriendOut(BaseModel):
    id: int
    user_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = "offline"
    custom_status_text: Optional[str] = None

class FriendDmOut(BaseModel):
    """Friend info for the DM sidebar, including status and unread count."""
    user_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Optional[str] = "offline"
    custom_status_text: Optional[str] = None
    unread_count: int = 0
    conversation_id: Optional[int] = None

class BlockedUserOut(BaseModel):
    id: int
    blocked_user_id: int
    username: str


# ── Pinned Messages ──

class PinnedMessageOut(BaseModel):
    id: int
    message_id: Optional[int] = None
    dm_message_id: Optional[int] = None
    pinned_by: int
    pinned_by_username: str
    pinned_at: datetime
    content: str
    author_username: str
    author_display_name: Optional[str] = None


# ── Server Invites ──

class InviteCreate(BaseModel):
    expires_hours: Optional[int] = None  # None = never expires
    max_uses: Optional[int] = None       # None = unlimited

class InviteOut(BaseModel):
    id: int
    server_id: int
    server_name: str
    code: str
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: int
    created_by: int
    created_at: datetime

class InviteJoin(BaseModel):
    code: str


# ── Notifications ──

class NotificationOut(BaseModel):
    id: int
    user_id: int
    type: str
    reference_id: Optional[int] = None
    content: Optional[str] = None
    is_read: bool
    created_at: datetime


# ── Moderation ──

class KickRequest(BaseModel):
    user_id: int

class BanRequest(BaseModel):
    user_id: int
    reason: Optional[str] = None

class BannedUserOut(BaseModel):
    id: int
    user_id: int
    username: str
    banned_by: int
    reason: Optional[str] = None
    banned_at: datetime
