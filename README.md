# Freecord

A Discord-style encrypted chat application with end-to-end encryption using AES-256-GCM. Built with a microservices architecture featuring a Rust encryption service, FastAPI backend, and Flask frontend.

## Short Demo

https://github.com/user-attachments/assets/83d48c52-d49c-4c82-8860-59e1c425caf3

## Features

✨ **Server & Channel Management** — Create servers and channels to organize conversations

💬 **Real-time Messaging** — WebSocket-powered live chat with instant message delivery

🔐 **End-to-End Encryption** — AES-256-GCM encryption for all messages

👥 **Direct Messages** — Private conversations with encrypted DM support

🔑 **User Authentication** — JWT-based auth with bcrypt password hashing

👤 **User Profiles** — Customize usernames and avatars

📁 **File Attachments** — Upload and share files in channels and DMs

🎨 **Dark Theme UI** — Modern, responsive design

## Architecture

```
Flask Frontend (5000)
    ↓ HTTP/REST
FastAPI Backend (8000)
    ↓ HTTP
Rust Encryption Service (8001)
```

### Message Flow

**Sending:**
```
Browser —WebSocket→ FastAPI —HTTP→ Rust /encrypt —→ Store in DB —HTTP→ Broadcast to clients
```

**Receiving:**
```
FastAPI —HTTP→ Rust /decrypt —→ Return plaintext to client
```

### Encryption

- **Method:** AES-256-GCM (Galois/Counter Mode)
- **Key Derivation:** `SHA256(MASTER_SECRET + channel_id)` for channels
- **DM Conversations:** Use `conversation_id + 1_000_000` to avoid key collisions

## Prerequisites

- **Python 3.8+** (for FastAPI and Flask services)
- **Rust 1.70+** (for encryption service)
- **pip** and **virtualenv**
- **cargo** (Rust package manager)

## Quick Start

### 1. Clone & Setup Environment

```bash
cd freecord
cp .env.example .env
```

Edit `.env` and configure required variables:
```
MASTER_SECRET=your-secret-key-here
JWT_SECRET=your-jwt-secret
FLASK_SECRET=your-flask-secret
RUST_SERVICE_URL=http://127.0.0.1:8001
API_URL=http://127.0.0.1:8000
RUST_LOG=info
```

### 2. Run All Services

**macOS:**
```bash
./scripts/run_mac.sh
```

**Linux:**
```bash
./scripts/run_linux.sh
```

**Windows:**
```bash
./scripts/run_windows.bat
```

This starts all three services:
- Rust service on `http://127.0.0.1:8001`
- FastAPI backend on `http://127.0.0.1:8000`
- Flask frontend on `http://127.0.0.1:5000`

### 3. Access the App

Open your browser and navigate to:
```
http://127.0.0.1:5000
```

Create an account and start chatting!

## Running Services Individually

### Rust Encryption Service

```bash
cd rust_encryption_service
cargo run --release
```

Requires `MASTER_SECRET` environment variable.

### FastAPI Backend

```bash
cd backend_fastapi
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### Flask Frontend

```bash
cd frontend_flask
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Building Rust Service

```bash
cd rust_encryption_service
cargo build --release
```

Output binary: `target/release/rust_encryption_service`

## Project Structure

```
freecord/
├── backend_fastapi/          # FastAPI REST API + WebSocket
│   ├── models.py             # SQLAlchemy DB models
│   ├── schemas.py            # Pydantic schemas
│   ├── auth.py               # JWT & bcrypt authentication
│   ├── database.py           # Database setup
│   ├── ws_manager.py         # WebSocket connection management
│   ├── main.py               # FastAPI app setup
│   └── routes/               # API endpoints
│       ├── auth_routes.py
│       ├── server_routes.py
│       ├── channel_routes.py
│       ├── message_routes.py
│       ├── dm_routes.py
│       ├── friend_routes.py
│       ├── invite_routes.py
│       ├── notification_routes.py
│       └── moderation_routes.py
│
├── frontend_flask/           # Flask web interface
│   ├── app.py                # Flask routes
│   ├── templates/            # Jinja2 templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── server.html
│   │   ├── channel.html
│   │   ├── dms.html
│   │   ├── dm_chat.html
│   │   ├── login.html
│   │   ├── register.html
│   │   ├── friends.html
│   │   └── settings.html
│   └── static/               # CSS, JS assets
│       └── style.css         # Dark theme styling
│
├── rust_encryption_service/  # AES-256-GCM encryption
│   ├── src/main.rs           # Actix-web server
│   └── Cargo.toml
│
├── scripts/                  # Startup/shutdown scripts
│   ├── run_mac.sh
│   ├── run_linux.sh
│   ├── run_windows.bat
│   ├── stop_mac.sh
│   ├── stop_linux.sh
│   └── stop_windows.bat
│
└── README.md
```

## Key Components

### Database (SQLite)

Located at `backend_fastapi/freecord.db`

**Models:**
- `User` — User accounts with bcrypt-hashed passwords
- `Server` — Server instances with ownership
- `Channel` — Channels within servers
- `Message` — Encrypted messages in channels
- `Conversation` — Direct message conversations
- `DirectMessage` — Encrypted DM content
- `UserServer` — User-server membership

### Authentication

- JWT tokens stored in Flask server-side sessions
- WebSocket auth uses JWT as query parameter: `?token=...`
- Passwords hashed with bcrypt before storage

### WebSocket

- **Channels:** Real-time message broadcasting to all channel members
- **DMs:** One-to-one message delivery
- Two separate `ConnectionManager` instances in FastAPI

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `MASTER_SECRET` | Encryption master key (Rust) | `your-secret-key` |
| `JWT_SECRET` | JWT signing secret (FastAPI) | `jwt-secret-key` |
| `FLASK_SECRET` | Flask session secret | `flask-secret` |
| `RUST_SERVICE_URL` | Rust service URL | `http://127.0.0.1:8001` |
| `API_URL` | FastAPI backend URL | `http://127.0.0.1:8000` |
| `RUST_LOG` | Rust logging level | `info`, `debug`, `error` |

## API Endpoints

### Authentication
- `POST /auth/register` — Create new user account
- `POST /auth/login` — Login and receive JWT
- `POST /auth/logout` — Logout (invalidate session)

### Servers & Channels
- `GET /servers` — List user's servers
- `POST /servers` — Create server
- `GET /servers/{id}/channels` — List channels in server
- `POST /servers/{id}/channels` — Create channel

### Messages
- `GET /channels/{id}/messages` — Get channel messages (paginated)
- `POST /channels/{id}/messages` — Send message (encrypted)
- `GET /channels/{id}/messages/{msg_id}` — Get single message (decrypted)

### Direct Messages
- `GET /conversations` — List DM conversations
- `GET /conversations/{id}` — Get DM thread
- `POST /conversations/{id}/messages` — Send DM (encrypted)

### Users & Friends
- `GET /users/{id}` — Get user profile
- `POST /friends/add` — Send friend request
- `GET /friends` — List friends

## WebSocket Events

### Channels
```
/ws/channel/{channel_id}?token={jwt_token}
```

**Events:**
- `message` — New message received
- `user_typing` — User typing indicator
- `user_joined` — User joined channel
- `user_left` — User left channel

### Direct Messages
```
/ws/dm/{conversation_id}?token={jwt_token}
```

**Events:**
- `message` — New DM received
- `user_typing` — User typing in DM

## Stopping Services

**macOS/Linux:**
```bash
./scripts/stop_mac.sh
# or
./scripts/stop_linux.sh
```

**Windows:**
```bash
./scripts/stop_windows.bat
```

## Database Reset

To reset the database (delete all data):

```bash
rm backend_fastapi/freecord.db
# Restart FastAPI to recreate schema
```

> ⚠️ **Warning:** This will delete all users, servers, channels, and messages. No backup is created.

## Development Notes

- **Migrations:** No migration system used. Schema changes require deleting the DB file.
- **Frontend session:** JWT stored in Flask server-side sessions, not localStorage
- **Sidebar:** Duplicated across templates (dashboard, server, channel, dms, dm_chat)
- **File uploads:** Stored in `backend_fastapi/uploads/` and `attachments/` directories
- **Development mode:** Use Flask with `--reload` and FastAPI with `--reload` for auto-restart

## Troubleshooting

### Services won't start
- Check all ports (5000, 8000, 8001) are available
- Verify environment variables in `.env`
- Check logs in terminal output

### Messages not encrypting
- Ensure Rust service is running on port 8001
- Verify `MASTER_SECRET` is set and consistent
- Check server logs for encryption errors

### WebSocket connection failed
- Verify JWT token is valid
- Check that fastAPI is accepting WebSocket connections
- Review browser console for specific error messages

### Database locked error
- Stop all services
- Delete `Freecord.db`
- Restart services

## Technologies Used

- **Backend:** FastAPI, SQLAlchemy, Uvicorn
- **Frontend:** Flask, Jinja2
- **Encryption:** Rust, Actix-web, AES-256-GCM
- **Database:** SQLite
- **Auth:** JWT, bcrypt
- **Real-time:** WebSockets (asyncio + websockets library)

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/YourFeature`
3. Commit changes: `git commit -m 'Add YourFeature'`
4. Push to branch: `git push origin feature/YourFeature`
5. Open a Pull Request

## License

This project is provided as-is. Modify and distribute as needed.

## Support

For issues, questions, or suggestions, please open an issue on the repository.

---

**Happy chatting! 🎉**
