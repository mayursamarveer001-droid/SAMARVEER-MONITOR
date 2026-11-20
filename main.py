"""
Live Screen Monitoring - Backend Server
----------------------------------------
Run: pip install -r requirements.txt
     uvicorn main:app --host 0.0.0.0 --port 8000

Login: set ADMIN_USERNAME and ADMIN_PASSWORD as environment variables
on your host (Railway > Variables tab). Defaults to admin / changeme123
if not set - CHANGE THIS before real use.
"""

import asyncio
import json
import os
import secrets
import time
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Live Screen Monitoring Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme123")
valid_sessions: Set[str] = set()

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

class Employee:
    def __init__(self, employee_id: str, name: str = "", role: str = ""):
        self.id = employee_id
        self.name = name or employee_id
        self.role = role
        self.agent_ws: WebSocket | None = None
        self.streaming: bool = False
        self.last_seen: float = 0.0
        self.last_frame: bytes | None = None


employees: Dict[str, Employee] = {}
admin_connections: Set[WebSocket] = set()


def get_or_create_employee(employee_id: str) -> Employee:
    if employee_id not in employees:
        employees[employee_id] = Employee(employee_id)
    return employees[employee_id]


async def broadcast_to_admins(message: dict, binary: bytes | None = None, employee_id: str | None = None):
    dead = []
    for ws in admin_connections:
        try:
            if binary is not None:
                await ws.send_bytes(_frame_envelope(employee_id, binary))
            else:
                await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        admin_connections.discard(ws)


def _frame_envelope(employee_id: str, jpeg_bytes: bytes) -> bytes:
    header = f"{employee_id}\n".encode("utf-8")
    return header + jpeg_bytes


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = secrets.token_hex(16)
        valid_sessions.add(token)
        resp = JSONResponse({"ok": True})
        resp.set_cookie("admin_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 12)
        return resp
    return JSONResponse({"ok": False, "error": "Invalid username or password"}, status_code=401)


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_token")
    valid_sessions.discard(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("admin_token")
    return resp


# ---------------------------------------------------------------------------
# Agent connection (the .exe running on an employee's PC)
# ---------------------------------------------------------------------------

@app.websocket("/ws/agent/{employee_id}")
async def agent_socket(websocket: WebSocket, employee_id: str):
    await websocket.accept()
    emp = get_or_create_employee(employee_id)
    emp.agent_ws = websocket
    emp.last_seen = time.time()

    try:
        while True:
            message = await websocket.receive()
            emp.last_seen = time.time()

            if "bytes" in message and message["bytes"] is not None:
                emp.last_frame = message["bytes"]
                await broadcast_to_admins({}, binary=message["bytes"], employee_id=employee_id)

            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "hello":
                    emp.name = data.get("name", emp.name)
                    emp.role = data.get("role", emp.role)
                    # Auto-start streaming as soon as the agent connects -
                    # no need for the admin to click "Start" manually.
                    emp.streaming = True
                    await websocket.send_text(json.dumps({"type": "start"}))
                    await broadcast_to_admins({
                        "type": "status", "id": employee_id, "online": True,
                        "name": emp.name, "role": emp.role, "streaming": True,
                    })

    except WebSocketDisconnect:
        pass
    finally:
        emp.agent_ws = None
        emp.streaming = False
        await broadcast_to_admins({"type": "status", "id": employee_id, "online": False})


# ---------------------------------------------------------------------------
# Admin panel connection (requires login)
# ---------------------------------------------------------------------------

@app.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket):
    token = websocket.cookies.get("admin_token")
    if not token or token not in valid_sessions:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    admin_connections.add(websocket)

    snapshot = [
        {"id": e.id, "name": e.name, "role": e.role, "online": e.agent_ws is not None,
         "streaming": e.streaming}
        for e in employees.values()
    ]
    await websocket.send_text(json.dumps({"type": "snapshot", "employees": snapshot}))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_admin_command(data)
    except WebSocketDisconnect:
        pass
    finally:
        admin_connections.discard(websocket)


async def _handle_admin_command(data: dict):
    cmd = data.get("type")
    emp_id = data.get("id")
    emp = employees.get(emp_id)
    if not emp or not emp.agent_ws:
        return
    if cmd == "start":
        emp.streaming = True
        await emp.agent_ws.send_text(json.dumps({"type": "start"}))
    elif cmd == "stop":
        emp.streaming = False
        await emp.agent_ws.send_text(json.dumps({"type": "stop"}))


@app.get("/api/employees")
async def list_employees():
    return JSONResponse([
        {
            "id": e.id, "name": e.name, "role": e.role,
            "online": e.agent_ws is not None, "streaming": e.streaming,
            "last_seen": e.last_seen,
        }
        for e in employees.values()
    ])


@app.get("/api/health")
async def health():
    return {"status": "ok", "employees_known": len(employees)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
