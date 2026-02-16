import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "flask-secret-change-me")

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


@app.route("/")
def index():
    if "token" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        import requests as req
        username = request.form["username"]
        password = request.form["password"]

        resp = req.post(f"{API_URL}/auth/login", json={
            "username": username,
            "password": password,
        })

        if resp.status_code == 200:
            data = resp.json()
            session["token"] = data["access_token"]
            session["username"] = username

            # Fetch profile to store user_id in session
            profile_resp = req.get(
                f"{API_URL}/auth/profile",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
            if profile_resp.status_code == 200:
                session["user_id"] = profile_resp.json()["id"]

            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        import requests as req
        username = request.form["username"]
        password = request.form["password"]

        resp = req.post(f"{API_URL}/auth/register", json={
            "username": username,
            "password": password,
        })

        if resp.status_code == 201:
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            try:
                error = resp.json().get("detail", "Registration failed")
            except Exception:
                error = "Registration failed"
            flash(error, "error")

    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}
    resp = req.get(f"{API_URL}/servers/", headers=headers)

    servers = resp.json() if resp.status_code == 200 else []

    # Fetch all servers for the browse/discover list
    browse_resp = req.get(f"{API_URL}/servers/browse", headers=headers)
    all_servers = browse_resp.json() if browse_resp.status_code == 200 else []

    # Mark which ones the user already joined
    joined_ids = {s["id"] for s in servers}
    for s in all_servers:
        s["joined"] = s["id"] in joined_ids

    return render_template("dashboard.html", servers=servers, all_servers=all_servers, username=session.get("username"))


@app.route("/servers/create", methods=["POST"])
def create_server():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}
    name = request.form["name"]

    req.post(f"{API_URL}/servers/", json={"name": name}, headers=headers)
    return redirect(url_for("dashboard"))


@app.route("/servers/<int:server_id>/join", methods=["POST"])
def join_server(server_id):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}
    req.post(f"{API_URL}/servers/{server_id}/join", headers=headers)
    return redirect(url_for("server_page", server_id=server_id))


@app.route("/servers/<int:server_id>")
def server_page(server_id):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    # Get all user servers for the sidebar
    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    # Get channels for this server
    channels_resp = req.get(f"{API_URL}/servers/{server_id}/channels/", headers=headers)
    channels = channels_resp.json() if channels_resp.status_code == 200 else []

    # Find current server name
    current_server = next((s for s in servers if s["id"] == server_id), None)

    return render_template(
        "server.html",
        servers=servers,
        channels=channels,
        server_id=server_id,
        current_server=current_server,
        username=session.get("username"),
    )


@app.route("/servers/<int:server_id>/channels/create", methods=["POST"])
def create_channel(server_id):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}
    name = request.form["name"]

    req.post(f"{API_URL}/servers/{server_id}/channels/", json={"name": name}, headers=headers)
    return redirect(url_for("server_page", server_id=server_id))


@app.route("/servers/<int:server_id>/channels/<int:channel_id>")
def channel_page(server_id, channel_id):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    # Get all user servers for the sidebar
    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    # Get channels for this server
    channels_resp = req.get(f"{API_URL}/servers/{server_id}/channels/", headers=headers)
    channels = channels_resp.json() if channels_resp.status_code == 200 else []

    # Get messages for this channel
    messages_resp = req.get(
        f"{API_URL}/servers/{server_id}/channels/{channel_id}/messages/",
        headers=headers,
    )
    messages = messages_resp.json() if messages_resp.status_code == 200 else []

    current_server = next((s for s in servers if s["id"] == server_id), None)
    current_channel = next((c for c in channels if c["id"] == channel_id), None)

    current_user_id = session.get("user_id")
    is_server_owner = current_server and current_user_id == current_server.get("owner_id")

    return render_template(
        "channel.html",
        servers=servers,
        channels=channels,
        messages=messages,
        server_id=server_id,
        channel_id=channel_id,
        current_server=current_server,
        current_channel=current_channel,
        username=session.get("username"),
        token=session["token"],
        ws_url=f"ws://127.0.0.1:8000/ws/{channel_id}",
        api_url=API_URL,
        current_user_id=current_user_id,
        is_server_owner=is_server_owner,
    )


@app.route("/dms")
def dms_page():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    # Get user's servers for sidebar
    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    # Get friends with status and unread counts (replaces old all-users fetch)
    friends_resp = req.get(f"{API_URL}/dms/users", headers=headers)
    friends = friends_resp.json() if friends_resp.status_code == 200 else []

    # Get incoming friend requests
    incoming_resp = req.get(f"{API_URL}/friends/requests/incoming", headers=headers)
    incoming_requests = incoming_resp.json() if incoming_resp.status_code == 200 else []

    # Get outgoing friend requests
    outgoing_resp = req.get(f"{API_URL}/friends/requests/outgoing", headers=headers)
    outgoing_requests = outgoing_resp.json() if outgoing_resp.status_code == 200 else []

    return render_template(
        "dms.html",
        servers=servers,
        friends=friends,
        incoming_requests=incoming_requests,
        outgoing_requests=outgoing_requests,
        username=session.get("username"),
        token=session["token"],
        api_url=API_URL,
    )


@app.route("/dms/start", methods=["POST"])
def start_dm():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}
    target_username = request.form["username"]

    resp = req.post(f"{API_URL}/dms/", json={"username": target_username}, headers=headers)
    if resp.status_code in (200, 201):
        convo = resp.json()
        return redirect(url_for("dm_chat_page", conversation_id=convo["id"]))
    else:
        flash(resp.json().get("detail", "Could not start DM"), "error")
        return redirect(url_for("dms_page"))


@app.route("/dms/<int:conversation_id>")
def dm_chat_page(conversation_id):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    # Servers for sidebar
    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    # Get friends with status and unread counts for DM sidebar
    friends_resp = req.get(f"{API_URL}/dms/users", headers=headers)
    friends = friends_resp.json() if friends_resp.status_code == 200 else []

    # Messages for this conversation
    msgs_resp = req.get(f"{API_URL}/dms/{conversation_id}/messages", headers=headers)
    messages = msgs_resp.json() if msgs_resp.status_code == 200 else []

    # Mark this conversation as read
    req.post(f"{API_URL}/dms/{conversation_id}/read", headers=headers)

    # Find the friend info for the current conversation
    current_friend = next((f for f in friends if f.get("conversation_id") == conversation_id), None)
    # Build a current_convo-like dict for template compatibility
    current_convo = None
    if current_friend:
        current_convo = {
            "id": conversation_id,
            "other_username": current_friend["username"],
            "other_display_name": current_friend.get("display_name"),
            "other_user_id": current_friend["user_id"],
        }
    else:
        # Fallback: fetch conversations list to find the other user
        convos_resp = req.get(f"{API_URL}/dms/", headers=headers)
        conversations = convos_resp.json() if convos_resp.status_code == 200 else []
        current_convo = next((c for c in conversations if c["id"] == conversation_id), None)

    return render_template(
        "dm_chat.html",
        servers=servers,
        friends=friends,
        messages=messages,
        conversation_id=conversation_id,
        current_convo=current_convo,
        username=session.get("username"),
        token=session["token"],
        ws_url=f"ws://127.0.0.1:8000/ws/dm/{conversation_id}",
        api_url=API_URL,
        current_user_id=session.get("user_id"),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    if request.method == "POST":
        # Update display name
        display_name = request.form.get("display_name", "").strip()
        req.put(f"{API_URL}/auth/profile", json={"display_name": display_name or None}, headers=headers)

        # Upload avatar if provided
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename:
            resp = req.post(
                f"{API_URL}/auth/avatar",
                headers=headers,
                files={"file": (avatar_file.filename, avatar_file.stream, avatar_file.content_type)},
            )
            if resp.status_code != 200:
                flash(resp.json().get("detail", "Avatar upload failed"), "error")
                return redirect(url_for("settings"))

        flash("Profile updated!", "success")
        return redirect(url_for("settings"))

    # GET: fetch current profile
    profile_resp = req.get(f"{API_URL}/auth/profile", headers=headers)
    profile = profile_resp.json() if profile_resp.status_code == 200 else {}

    # Get servers for sidebar
    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    return render_template(
        "settings.html",
        servers=servers,
        profile=profile,
        username=session.get("username"),
        api_url=API_URL,
    )


@app.route("/friends")
def friends_page():
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    servers_resp = req.get(f"{API_URL}/servers/", headers=headers)
    servers = servers_resp.json() if servers_resp.status_code == 200 else []

    friends_resp = req.get(f"{API_URL}/friends/", headers=headers)
    friends = friends_resp.json() if friends_resp.status_code == 200 else []

    incoming_resp = req.get(f"{API_URL}/friends/requests/incoming", headers=headers)
    incoming = incoming_resp.json() if incoming_resp.status_code == 200 else []

    outgoing_resp = req.get(f"{API_URL}/friends/requests/outgoing", headers=headers)
    outgoing = outgoing_resp.json() if outgoing_resp.status_code == 200 else []

    blocked_resp = req.get(f"{API_URL}/friends/blocked", headers=headers)
    blocked = blocked_resp.json() if blocked_resp.status_code == 200 else []

    return render_template(
        "friends.html",
        servers=servers,
        friends=friends,
        incoming_requests=incoming,
        outgoing_requests=outgoing,
        blocked_users=blocked,
        username=session.get("username"),
        token=session["token"],
        api_url=API_URL,
    )


@app.route("/invite/<code>")
def invite_page(code):
    if "token" not in session:
        return redirect(url_for("login"))

    import requests as req
    headers = {"Authorization": f"Bearer {session['token']}"}

    info_resp = req.get(f"{API_URL}/invites/info/{code}", headers=headers)
    if info_resp.status_code != 200:
        flash("Invalid or expired invite", "error")
        return redirect(url_for("dashboard"))

    invite = info_resp.json()

    # Auto-join
    join_resp = req.post(f"{API_URL}/invites/join", json={"code": code}, headers=headers)
    if join_resp.status_code == 200:
        server = join_resp.json()
        return redirect(url_for("server_page", server_id=server["id"]))
    else:
        try:
            error = join_resp.json().get("detail", "Could not join server")
        except Exception:
            error = "Could not join server"
        flash(error, "error")
        return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
