from flask import Flask, render_template, request, redirect, session, abort
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.security import generate_password_hash, check_password_hash
from Models import db, User, ChatRoom, RoomUser, Message
import random, os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
db.init_app(app)

socketio = SocketIO(app)
os.makedirs("logs", exist_ok=True)

with app.app_context():
    db.create_all()

def random_color():
    return f"#{random.randint(0, 0xFFFFFF):06x}"

def require_login():
    if "user_id" not in session:
        abort(403)

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if not user:
            user = User(
                username=username,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
        else:
            if not check_password_hash(user.password_hash, password):
                return "Wrong password"

        session["user_id"] = user.id
        session["username"] = user.username
        session["color"] = random_color()

        return redirect("/rooms")

    return render_template("login.html")

@app.route("/rooms", methods=["GET", "POST"])
def rooms():
    require_login()

    if request.method == "POST":
        room_name = request.form["room_name"]
        existing = ChatRoom.query.filter_by(name=room_name).first()
        if existing:
            return "Room with this name already exists"

        room = ChatRoom(
            name=room_name,
            owner_id=session["user_id"]
        )
        db.session.add(room)
        db.session.commit()

        ru = RoomUser(
            room_id=room.id,
            user_id=session["user_id"]
        )
        db.session.add(ru)
        db.session.commit()

    owned = ChatRoom.query.filter_by(owner_id=session["user_id"]).all()
    joined = (
        ChatRoom.query
        .join(RoomUser, RoomUser.room_id == ChatRoom.id)
        .filter(RoomUser.user_id == session["user_id"])
        .all()
    )
    return render_template("rooms.html", owned=owned, joined=joined)

@app.route("/invite/<int:room_id>", methods=["POST"])
def invite(room_id):
    require_login()

    room = ChatRoom.query.get_or_404(room_id)
    if room.owner_id != session["user_id"]:
        abort(403)

    username = request.form["username"]
    user = User.query.filter_by(username=username).first()
    if not user:
        return "User not found"

    exists = RoomUser.query.filter_by(room_id=room.id, user_id=user.id).first()
    if not exists:
        db.session.add(RoomUser(room_id=room.id, user_id=user.id))
        db.session.commit()

    return redirect("/rooms")

@app.route("/chat/<int:room_id>")
def chat(room_id):
    require_login()

    allowed = RoomUser.query.filter_by(
        room_id=room_id,
        user_id=session["user_id"]
    ).first()
    if not allowed:
        abort(403)

    room = ChatRoom.query.get_or_404(room_id)

    messages = (
        Message.query
        .filter_by(room_id=room_id)
        .order_by(Message.timestamp)
        .all()
    )

    return render_template(
        "chat.html",
        room_id=room.id,
        room_name=room.name,
        username=session["username"],
        color=session["color"],
        messages=messages
    )


@socketio.on("join")
def ws_join(data):
    room_id = data["room_id"]
    join_room(str(room_id))

    text = f"{session['username']} joined the room"

    msg = Message(
        room_id=room_id,
        username="SYSTEM",
        text=text
    )
    db.session.add(msg)
    db.session.commit()

    emit("status", {
        "msg": text
    }, room=str(room_id))


@socketio.on("leave")
def ws_leave(data):
    room_id = data["room_id"]
    leave_room(str(room_id))

    text = f"{session['username']} left the room"

    msg = Message(
        room_id=room_id,
        username="SYSTEM",
        text=text
    )
    db.session.add(msg)
    db.session.commit()

    emit("status", {
        "msg": text
    }, room=str(room_id))


@socketio.on("message")
def ws_message(data):
    room_id = data["room_id"]
    text = data["msg"]

    msg = Message(
        room_id=room_id,
        username=session["username"],
        text=text
    )
    db.session.add(msg)
    db.session.commit()

    room = ChatRoom.query.get(room_id)
    safe_name = room.name.replace(" ", "_")
    log_file = f"logs/{safe_name}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{msg.timestamp}] {session['username']}: {text}\n")

    emit("message", {
        "user": session["username"],
        "msg": text,
        "color": session["color"],
        "time": msg.timestamp.strftime("%H:%M")
    }, room=str(room_id))


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
