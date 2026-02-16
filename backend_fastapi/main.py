import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt

from database import engine, Base, SessionLocal
from ws_manager import manager, dm_manager, connected_users
from routes.auth_routes import router as auth_router
from routes.server_routes import router as server_router
from routes.channel_routes import router as channel_router
from routes.message_routes import router as message_router, encrypt_message
from routes.dm_routes import router as dm_router, dm_encrypt, DM_KEY_OFFSET
from routes.friend_routes import router as friend_router
from routes.invite_routes import router as invite_router
from routes.notification_routes import router as notification_router
from routes.moderation_routes import router as moderation_router


BASE_DIR = os.path.dirname(__file__)

# Ensure upload directories exist before StaticFiles mounts
os.makedirs(os.path.join(BASE_DIR, "uploads", "channels"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "uploads", "dms"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "attachments"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "avatars"), exist_ok=True)


# ── Create tables on startup ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="Freecord API", lifespan=lifespan)

# CORS — allow the Flask frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve static files ──
app.mount("/avatars", StaticFiles(directory=os.path.join(BASE_DIR, "avatars")), name="avatars")
app.mount("/attachments", StaticFiles(directory=os.path.join(BASE_DIR, "attachments")), name="attachments")
app.mount("/uploads/channels", StaticFiles(directory=os.path.join(BASE_DIR, "uploads", "channels")), name="uploads_channels")
app.mount("/uploads/dms", StaticFiles(directory=os.path.join(BASE_DIR, "uploads", "dms")), name="uploads_dms")

# ── Register routers ──
app.include_router(auth_router)
app.include_router(server_router)
app.include_router(channel_router)
app.include_router(message_router)
app.include_router(dm_router)
app.include_router(friend_router)
app.include_router(invite_router)
app.include_router(notification_router)
app.include_router(moderation_router)


JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-key")


def _update_user_status(user_id: int, status: str):
    """Update user status in database."""
    db = SessionLocal()
    try:
        from models import User
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.status = status
            user.last_activity = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@app.websocket("/ws/{channel_id}")
async def websocket_endpoint(websocket: WebSocket, channel_id: int, token: str = Query(...)):
    # Authenticate the WebSocket connection via JWT
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
        username = payload["username"]
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, channel_id, user_id, username)
    connected_users[user_id].add(websocket)

    # Set user online
    _update_user_status(user_id, "online")
    await manager.broadcast_except(channel_id, {
        "type": "status_update",
        "user_id": user_id,
        "username": username,
        "status": "online",
    }, user_id)

    try:
        while True:
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            msg_type = msg_data.get("type", "message")

            # ── Typing indicator ──
            if msg_type in ("typing_start", "typing_stop"):
                await manager.broadcast_except(channel_id, {
                    "type": msg_type,
                    "user_id": user_id,
                    "username": username,
                }, user_id)
                continue

            # ── Regular message ──
            content = msg_data.get("content", "")
            if not content.strip():
                continue

            from models import Message, User

            encrypted = await encrypt_message(channel_id, content)
            db = SessionLocal()
            try:
                msg = Message(
                    encrypted_content=encrypted,
                    channel_id=channel_id,
                    user_id=user_id,
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)
                msg_id = msg.id
                created_at = msg.created_at.isoformat()
                sender = db.query(User).filter(User.id == user_id).first()
                display_name = sender.display_name if sender else None
                avatar_url = f"/avatars/{sender.avatar}" if sender and sender.avatar else None
            finally:
                db.close()

            await manager.broadcast(channel_id, {
                "type": "message",
                "id": msg_id,
                "content": content,
                "channel_id": channel_id,
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "avatar_url": avatar_url,
                "attachment_url": None,
                "attachment_name": None,
                "attachment_size": None,
                "attachment_mime": None,
                "is_deleted": False,
                "edited_at": None,
                "reactions": [],
                "created_at": created_at,
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)
        connected_users[user_id].discard(websocket)
        # Only set offline if no other connections remain
        if not connected_users[user_id]:
            _update_user_status(user_id, "offline")
            await manager.broadcast(channel_id, {
                "type": "status_update",
                "user_id": user_id,
                "username": username,
                "status": "offline",
            })


# ── DM WebSocket ──

@app.websocket("/ws/dm/{conversation_id}")
async def dm_websocket_endpoint(websocket: WebSocket, conversation_id: int, token: str = Query(...)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
        username = payload["username"]
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Verify user is a participant in this conversation
    from models import Conversation
    db = SessionLocal()
    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo or user_id not in (convo.user1_id, convo.user2_id):
        db.close()
        await websocket.close(code=4003, reason="Not a participant")
        return
    db.close()

    await dm_manager.connect(websocket, conversation_id, user_id, username)
    connected_users[user_id].add(websocket)

    _update_user_status(user_id, "online")
    await dm_manager.broadcast_except(conversation_id, {
        "type": "status_update",
        "user_id": user_id,
        "username": username,
        "status": "online",
    }, user_id)

    try:
        while True:
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            msg_type = msg_data.get("type", "message")

            # ── Typing indicator ──
            if msg_type in ("typing_start", "typing_stop"):
                await dm_manager.broadcast_except(conversation_id, {
                    "type": msg_type,
                    "user_id": user_id,
                    "username": username,
                }, user_id)
                continue

            # ── Regular message ──
            content = msg_data.get("content", "")
            if not content.strip():
                continue

            from models import DirectMessage, User

            encrypted = await dm_encrypt(conversation_id, content)
            db = SessionLocal()
            try:
                msg = DirectMessage(
                    encrypted_content=encrypted,
                    conversation_id=conversation_id,
                    sender_id=user_id,
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)
                msg_id = msg.id
                created_at = msg.created_at.isoformat()
                sender = db.query(User).filter(User.id == user_id).first()
                display_name = sender.display_name if sender else None
                avatar_url = f"/avatars/{sender.avatar}" if sender and sender.avatar else None
            finally:
                db.close()

            await dm_manager.broadcast(conversation_id, {
                "type": "message",
                "id": msg_id,
                "content": content,
                "conversation_id": conversation_id,
                "sender_id": user_id,
                "sender_username": username,
                "sender_display_name": display_name,
                "sender_avatar_url": avatar_url,
                "attachment_url": None,
                "attachment_name": None,
                "attachment_size": None,
                "attachment_mime": None,
                "is_deleted": False,
                "edited_at": None,
                "reactions": [],
                "created_at": created_at,
            })
    except WebSocketDisconnect:
        dm_manager.disconnect(websocket, conversation_id)
        connected_users[user_id].discard(websocket)
        if not connected_users[user_id]:
            _update_user_status(user_id, "offline")
            await dm_manager.broadcast(conversation_id, {
                "type": "status_update",
                "user_id": user_id,
                "username": username,
                "status": "offline",
            })


# ── User Status endpoint ──

@app.put("/status")
async def update_status(
    status_data: dict,
    token: str = Query(None),
):
    """Update user status manually (online, idle, dnd, offline)."""
    from fastapi import Header
    # This is handled via the auth_routes status endpoint instead
    pass


@app.get("/")
def root():
    return {"message": "Securecord API is running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
