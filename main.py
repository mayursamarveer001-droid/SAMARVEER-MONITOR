"""
Live Screen Monitoring - Backend Server
----------------------------------------
Run: pip install -r requirements.txt
     uvicorn main:app --host 0.0.0.0 --port 8000

Login: Railway > Variables mein ADMIN_USERNAME aur ADMIN_PASSWORD set kar
sakte hain (permanent default). Admin panel ke andar se bhi password badla
ja sakta hai, lekin wo change tab tak rehta hai jab tak server restart na
ho jaye (free hosting par restart hona normal hai) - restart hone par wapas
Variables wali value par chala jayega. Permanent rakhne ke liye Railway
Variables hi update karein.
"""

import json
import os
import secrets
import time
from datetime import date
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

# ---------------------------------------------------------------------------
# Login credentials (in-memory, can be changed from the admin panel)
# ---------------------------------------------------------------------------
current_username = os.environ.get("ADMIN_USERNAME", "admin")
current_password = os.environ.get("ADMIN_PASSWORD", "changeme123")
valid_sessions: Set[str] = set()


class Employee:
    def __init__(self, employee_id: str, name: str = "", role: str = ""):
        self.id = employee_id
        self.name = name or employee_id
        self.role = role
        self.agent_ws: WebSocket | None = None
        self.streaming: bool = False
        self.last_seen: float = 0.0
        self.last_frame: bytes | None = None

        self.online_since: float | None = None
        self.offline_since: float | None = None
        self.idle_since: float | None = None
        self.online_today: str | None = None


def today_str() -> str:
    return date.today().isoformat()


employees: Dict[str, Employee] = {}
admin_connections: Set[WebSocket] = set()


def get_or_create_employee(employee_id: str) -> Employee:
    if employee_id not in employees:
        employees[employee_id] = Employee(employee_id)
    return employees[employee_id]


def employee_snapshot(e: Employee) -> dict:
    return {
        "id": e.id, "name": e.name, "role": e.role,
        "online": e.agent_ws is not None, "streaming": e.streaming,
        "online_since": e.online_since, "offline_since": e.offline_since,
        "idle_since": e.idle_since, "online_today": e.online_today == today_str(),
    }


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


async def broadcast_status(emp: Employee):
    await broadcast_to_admins({"type": "status", **employee_snapshot(emp)})


# ---------------------------------------------------------------------------
# Login / password
# ---------------------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    if username == current_username and password == current_password:
        token = secrets.token_hex(16)
        valid_sessions.add(token)
        resp = JSONResponse({"ok": True})
        resp.set_cookie("admin_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
        return resp
    return JSONResponse({"ok": False, "error": "Username ya password galat hai"}, status_code=401)


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_token")
    valid_sessions.discard(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("admin_token")
    return resp


@app.post("/api/change-password")
async def change_password(request: Request):
    global current_password
    token = request.cookies.get("admin_token")
    if not token or token not in valid_sessions:
        return JSONResponse({"ok": False, "error": "Login nahi hai"}, status_code=401)

    form = await request.form()
    current = form.get("current_password", "")
    new = form.get("new_password", "")

    if current != current_password:
        return JSONResponse({"ok": False, "error": "Current password galat hai"}, status_code=400)
    if not new or len(new) < 4:
        return JSONResponse({"ok": False, "error": "Naya password kam se kam 4 characters ka hona chahiye"}, status_code=400)

    current_password = new
    return JSONResponse({"ok": True})


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
                    if not emp.name or emp.name == emp.id:
                        emp.name = data.get("name", emp.name)
                    if not emp.role:
                        emp.role = data.get("role", emp.role)

                    now = time.time()
                    emp.online_since = now
                    emp.offline_since = None
                    emp.online_today = today_str()

                    emp.streaming = True
                    emp.idle_since = None
                    await websocket.send_text(json.dumps({"type": "start"}))

                    await broadcast_status(emp)

    except WebSocketDisconnect:
        pass
    finally:
        emp.agent_ws = None
        emp.streaming = False
        emp.offline_since = time.time()
        emp.online_since = None
        emp.idle_since = None
        await broadcast_status(emp)


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

    snapshot = [employee_snapshot(e) for e in employees.values()]
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
    if not emp:
        return

    if cmd == "start" and emp.agent_ws:
        emp.streaming = True
        emp.idle_since = None
        await emp.agent_ws.send_text(json.dumps({"type": "start"}))
        await broadcast_status(emp)

    elif cmd == "stop" and emp.agent_ws:
        emp.streaming = False
        emp.idle_since = time.time()
        await emp.agent_ws.send_text(json.dumps({"type": "stop"}))
        await broadcast_status(emp)

    elif cmd == "rename":
        new_name = (data.get("name") or "").strip()
        new_role = (data.get("role") or "").strip()
        if new_name:
            emp.name = new_name
        if new_role:
            emp.role = new_role
        await broadcast_status(emp)


@app.get("/api/employees")
async def list_employees():
    return JSONResponse([employee_snapshot(e) for e in employees.values()])


@app.get("/api/health")
async def health():
    return {"status": "ok", "employees_known": len(employees)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
