from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Server, Channel, User
from schemas import ChannelCreate, ChannelOut
from auth import get_current_user

router = APIRouter(prefix="/servers/{server_id}/channels", tags=["channels"])


@router.post("/", response_model=ChannelOut, status_code=201)
def create_channel(
    server_id: int,
    data: ChannelCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member of this server")

    channel = Channel(name=data.name, server_id=server_id)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/", response_model=List[ChannelOut])
def list_channels(
    server_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if user not in server.members:
        raise HTTPException(status_code=403, detail="Not a member of this server")

    return server.channels
