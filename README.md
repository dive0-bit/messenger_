# Messenger - Real-time Chat Backend

A one-to-one chat app built with **Python, Django, Django REST Framework, Django Channels
(WebSockets) and Redis**. The backend has session login, a REST API and two WebSocket
endpoints. The web page (`backend/ui/`) is plain **HTML, CSS and JavaScript** served by Django.

## Features

- **Accounts:** register, login (username **or** email), logout, password reset
- **Profile (after login):** upload a profile photo, change your name, write a bio
- **Live chat:** one-to-one conversations, messages are delivered instantly over WebSocket
  (Redis is the channel layer); if the socket is down, messages are sent over normal HTTP
- **Notifications:** a **sound**, a **desktop notification** and an **unread counter** (also in
  the tab title) when a message arrives in a chat you are not looking at
- **Add friends** with a **Unique ID**, delete conversations
- **Account rules:** Gmail-only unique email, password pattern, Argon2 hashing, account lock after
  5 wrong passwords
- **Authorization:** only members can read a conversation or connect to its WebSocket
- **Ready to deploy:** Docker, Docker Compose (app + Redis), Render Blueprint (Postgres + Redis)

## Tech stack

| Part | Technology |
|------|------------|
| Backend | Python 3.12+, Django 6, Django REST Framework |
| Real time | Django Channels, Daphne (ASGI server), Redis (channel layer) |
| Database | SQLite locally, PostgreSQL on Render (`DATABASE_URL`) |
| Auth | Django sessions + CSRF, Argon2 password hashing |
| Frontend | HTML, CSS, plain JavaScript|
| Tests | Django test runner + Channels `WebsocketCommunicator` (40 tests) |
| Deployment | Docker, Docker Compose, Render |

**Try a chat:** register two users (use a normal window and a private window), copy the
"Your ID" of one user and add it from the other. Send a message while the other user is
looking at a different screen to hear the notification sound. Click **Edit profile** to change
the photo, name and bio.

### Manual commands (PowerShell, VS Code terminal)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd backend
copy .env.example .env
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```
If PowerShell says "running scripts is disabled", run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Tests

```
cd backend
python manage.py test
```
40 tests: registration rules, login by email, account lock, password reset, profile update
(name, bio, picture), permissions (non-members get 404), messages, deleting conversations and
the WebSocket flow.

## Redis (optional locally)

Channels needs a *channel layer* so different WebSocket connections can reach each other. By
default an in-memory layer is used (one server process only). To use Redis, set in
`backend/.env`: `USE_REDIS=True` and `REDIS_URL=redis://127.0.0.1:6379`, then restart.
Docker Compose and Render do this automatically.

## Docker
```
docker compose up --build        # then open http://localhost:8000
```

## Architecture

```
 Browser (HTML + CSS + JS)
   |  HTTP /api/...                      WebSocket /ws/...
   v                                          v
 +--------------------------------------------------------+
 |  Daphne (ASGI)  ->  config/asgi.py  ProtocolTypeRouter   |
 |     http       -> Django views (DRF)   accounts / chats  |
 |     websocket  -> Channels consumers   ChatConsumer      |
 |                                        NotificationConsumer|
 +--------------------------------------------------------+
        |                                  |
        v                                  v
   Database (SQLite / Postgres)     Channel layer (Redis or in-memory)
```

## Database schema

| Table | Fields |
|-------|--------|
| `User` (Django built-in) | username (the name shown in chats), email, password (hash) |
| `Profiles` | user (one-to-one), bio, profile_picture, unique_id (unique), created_at |
| `Conversation` | created_at |
| `ConversationMember` | conversation (FK), user (FK), joined_at - unique together |
| `Message` | conversation (FK), sender (FK), content, created_at, is_read |

## REST API

All URLs are JSON. Everything except register / login / me / password reset needs a login.
Write requests need the CSRF token in the `X-CSRFToken` header (it is the `csrftoken` cookie).

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/auth/me/` | current user or `{"user": null}`; also sets the CSRF cookie |
| POST | `/api/auth/register/` | create account |
| POST | `/api/auth/login/` | login with username or email |
| POST | `/api/auth/logout/` | logout |
| POST | `/api/auth/profile/` | update name (`username`), `bio`, `profile_picture` (multipart form) |
| POST | `/api/auth/password-reset/` | create a reset link (email is printed in the terminal) |
| POST | `/api/auth/password-reset-confirm/` | set a new password with `uid` + `token` |
| GET | `/api/conversations/` | my conversations, newest first |
| POST | `/api/conversations/add/` | start a chat with a Unique ID (`201` new, `200` already existed) |
| DELETE | `/api/conversations/<id>/` | delete a conversation (`204`) |
| GET / POST | `/api/conversations/<id>/messages/` | read / send messages |

Examples:

```
POST /api/auth/register/
{"username": "dev", "email": "dev123@gmail.com", "password": "@dev12345#dee2",
 "confirm_password": "@dev12345#dee2", "unique_id": "dev_01"}
-> 201 {"user": {"id": 1, "username": "dev", "email": "dev123@gmail.com", "bio": "",
                 "unique_id": "dev_01", "profile_picture": ""}}

POST /api/auth/profile/        (multipart: username, bio, profile_picture)
-> 200 {"user": {..., "username": "new-name", "bio": "Hello", "profile_picture": "/media/profile_pictures/me.png"}}
-> 400 {"detail": "Username already exists."}      (a bad picture or name saves nothing)

POST /api/auth/login/            {"username": "dev", "password": "wrong"}
-> 400 {"detail": "Invalid username or password. 4 attempts left."}
   (after 5 wrong attempts -> 429 "Too many wrong attempts. Account locked ...")

POST /api/conversations/<id>/messages/    {"content": "Hello"}
-> 201 {"id": 7, "conversation": 3, "sender": 1, "sender_username": "dev",
        "content": "Hello", "created_at": "2026-09-30T10:15:00Z", "is_read": false}

GET /api/conversations/999/messages/      (not a member)
-> 404 {"detail": "Conversation not found."}
```

Status codes: `200 201 204` success, `400` validation error, `403` not logged in,
`404` unknown user / not your conversation, `429` account locked.

## WebSocket API

| URL | Who can connect | Purpose |
|-----|-----------------|---------|
| `/ws/conversations/<id>/` | members of the conversation | send and receive live messages |
| `/ws/notifications/` | any logged-in user | "you got a new message" events |

The login cookie is sent with the handshake, so the server knows the user. A refused
connection is closed with code `4403` (not a member) or `4401` (not logged in).

```
client -> server   {"type": "message", "content": "Hello"}
server -> client   {"type": "message", "message": {...same JSON as the REST message...}}
server -> client   {"type": "error", "detail": "Message cannot be empty."}
server -> client   {"type": "notification", "message": {...}}      (notifications socket)
```

## Project structure

```
messenger_project/
└── backend/
    ├── manage.py, requirements.txt, .env.example
    ├── config/              settings, urls, asgi (HTTP + WebSocket entry), view for the web page
    ├── accounts/            register, login, profile, password reset
    │                        validators.py (email / password rules), login_limit.py (5 attempts)
    ├── chats/               models, REST views, serializers, consumers.py, routing.py, services.py
    └── ui/                  the web page: index.html, app.js, style.css
```

## Known limitations / future work

- One-to-one chats only (the tables already allow group chats)
- `is_read` exists but there are no read receipts yet (the unread counter lives in the browser)
- Notifications work while the page is open; for a closed tab you would need Web Push
- No pagination for old messages; the conversation list runs a few queries per chat
- No rate limiting except the login lock (the lock counter is kept in server memory)
- Pictures are stored on the server disk (S3 or similar would be used in production)
