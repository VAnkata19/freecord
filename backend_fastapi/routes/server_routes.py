from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Server, Channel, User, BannedUser
from schemas import ServerCreate, ServerOut
from auth import get_current_user

router = APIRouter(prefix="/servers", tags=["servers"])


@router.post("/", response_model=ServerOut, status_code=201)
def create_server(
    data: ServerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = Server(name=data.name, owner_id=user.id)
    server.members.append(user)
    db.add(server)
    db.commit()
    db.refresh(server)

    # Auto-create a #general channel
    general = Channel(name="general", server_id=server.id)
    db.add(general)
    db.commit()

    return server


@router.get("/", response_model=List[ServerOut])
def list_servers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return user.servers


@router.get("/browse", response_model=List[ServerOut])
def browse_servers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all servers so users can discover and join them."""
    return db.query(Server).all()


@router.post("/{server_id}/join", response_model=ServerOut)
def join_server(
    server_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Check if banned
    banned = db.query(BannedUser).filter(
        BannedUser.server_id == server_id, BannedUser.user_id == user.id
    ).first()
    if banned:
        raise HTTPException(status_code=403, detail="You are banned from this server")

    if user not in server.members:
        server.members.append(user)
        db.commit()
        db.refresh(server)
    return server
