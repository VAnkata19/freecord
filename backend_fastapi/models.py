from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

# Many-to-many: users <-> servers
server_members = Table(
    "server_members",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("server_id", Integer, ForeignKey("servers.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)   # shown instead of username
    avatar = Column(String(255), nullable=True)          # filename in avatars/
    status = Column(String(20), default="offline")       # online, idle, dnd, offline
    custom_status_text = Column(String(128), nullable=True)  # custom status message
    last_activity = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    servers = relationship("Server", secondary=server_members, back_populates="members")


class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", foreign_keys=[owner_id])
    members = relationship("User", secondary=server_members, back_populates="servers")
    channels = relationship("Channel", back_populates="server", cascade="all, delete-orphan")


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    is_locked = Column(Boolean, default=False)  # read-only when locked

    server = relationship("Server", back_populates="channels")
    messages = relationship("Message", back_populates="channel", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    encrypted_content = Column(String, nullable=False)  # stored encrypted
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    attachment = Column(String(255), nullable=True)     # filename in uploads/
    attachment_name = Column(String(255), nullable=True)  # original filename
    attachment_size = Column(Integer, nullable=True)      # file size in bytes
    attachment_mime = Column(String(128), nullable=True)  # MIME type
    is_deleted = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    channel = relationship("Channel", back_populates="messages")
    user = relationship("User")
    reactions = relationship("Reaction", back_populates="message", cascade="all, delete-orphan")


class Conversation(Base):
    """A DM conversation between two users."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])
    direct_messages = relationship("DirectMessage", back_populates="conversation", cascade="all, delete-orphan")


class DirectMessage(Base):
    """A message within a DM conversation, stored encrypted."""
    __tablename__ = "direct_messages"

    id = Column(Integer, primary_key=True, index=True)
    encrypted_content = Column(String, nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    attachment = Column(String(255), nullable=True)       # filename in uploads/
    attachment_name = Column(String(255), nullable=True)  # original filename
    attachment_size = Column(Integer, nullable=True)      # file size in bytes
    attachment_mime = Column(String(128), nullable=True)  # MIME type
    is_deleted = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="direct_messages")
    sender = relationship("User")
    reactions = relationship("DMReaction", back_populates="dm_message", cascade="all, delete-orphan")


class Reaction(Base):
    """Emoji reaction on a channel message."""
    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    emoji = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", "emoji", name="uq_reaction"),
    )

    user = relationship("User")
    message = relationship("Message", back_populates="reactions")


class DMReaction(Base):
    """Emoji reaction on a DM message."""
    __tablename__ = "dm_reactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    dm_message_id = Column(Integer, ForeignKey("direct_messages.id"), nullable=False)
    emoji = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "dm_message_id", "emoji", name="uq_dm_reaction"),
    )

    user = relationship("User")
    dm_message = relationship("DirectMessage", back_populates="reactions")


# ── Friend System ──

class FriendRequest(Base):
    __tablename__ = "friend_requests"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="pending")  # pending, accepted, denied
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])


class Friend(Base):
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    friend_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="uq_friendship"),
    )

    user = relationship("User", foreign_keys=[user_id])
    friend = relationship("User", foreign_keys=[friend_id])


class DmReadState(Base):
    """Tracks when a user last read a DM conversation (for unread counts)."""
    __tablename__ = "dm_read_states"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    last_read_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "conversation_id", name="uq_dm_read"),
    )

    user = relationship("User", foreign_keys=[user_id])
    conversation = relationship("Conversation")


class BlockedUser(Base):
    __tablename__ = "blocked_users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    blocked_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "blocked_user_id", name="uq_block"),
    )

    user = relationship("User", foreign_keys=[user_id])
    blocked_user = relationship("User", foreign_keys=[blocked_user_id])


# ── Pinned Messages ──

class PinnedMessage(Base):
    __tablename__ = "pinned_messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    dm_message_id = Column(Integer, ForeignKey("direct_messages.id"), nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    pinned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    pinned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    message = relationship("Message")
    dm_message = relationship("DirectMessage")
    pinner = relationship("User")


# ── Server Invites ──

class ServerInvite(Base):
    __tablename__ = "server_invites"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=True)
    uses = Column(Integer, default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    server = relationship("Server")
    creator = relationship("User")


# ── Notifications ──

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(30), nullable=False)  # friend_request, mention, invite
    reference_id = Column(Integer, nullable=True)
    content = Column(String(255), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")


# ── Moderation ──

class BannedUser(Base):
    __tablename__ = "banned_users"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    banned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(String(255), nullable=True)
    banned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_ban"),
    )

    server = relationship("Server")
    user = relationship("User", foreign_keys=[user_id])
    banner = relationship("User", foreign_keys=[banned_by])
