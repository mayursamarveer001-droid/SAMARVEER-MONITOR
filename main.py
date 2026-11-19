"""
Live Screen Monitoring - Backend Server
----------------------------------------
Run: pip install -r requirements.txt
     uvicorn main:app --host 0.0.0.0 --port 8000

Endpoints:
  WS   /ws/agent/{employee_id}      <- agent (exe) connects here, sends binary JPEG frames
  WS   /ws/admin                    <- admin panel (browser) connects here, receives live frames
  GET  /api/employees               -> list of employees + online/streaming status
  POST /api/employees/{id}/start    -> tell that agent to start streaming
  POST /api/employees/{id}/stop     -> tell that agent to stop streaming
  GET  /                            -> health check
"""

import asyncio
import json
import time
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Live Screen Monitoring Server")

# Allow your admin panel's domain to call this API / open websockets.
# Restrict this to your real admin panel domain before going fully live.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory state (swap for Redis/Postgres once you move past MVP)
# ---------------------------------------------------------------------------

class Employee:
    def __init__(self, employee_id: str, name: str = "", role: str = ""):
        self.id = employee_id
        self.name = name or employee_id
        self.role = role
        self.agent_ws: WebSocket | None = None   # the agent's live connection
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
    # Simple framing: "<employee_id>\n" header + raw JPEG bytes.
    # Admin panel JS splits on the first \n to know which tile to update.
    header = f"{employee_id}\n".encode("utf-8")
    return header + jpeg_bytes


# ---------------------------------------------------------------------------
# Agent connection (the .exe running on an employee's PC)
# ---------------------------------------------------------------------------

@app.websocket("/ws/agent/{employee_id}")
async def agent_socket(websocket: WebSocket, employee_id: str):
    await websocket.accept()
    emp = get_or_create_employee(employee_id)
    emp.agent_ws = websocket
    emp.last_seen = time.time()

    await broadcast_to_admins({"type": "status", "id": employee_id, "online": True})

    try:
        while True:
            message = await websocket.receive()
            emp.last_seen = time.time()

            if "bytes" in message and message["bytes"] is not None:
                # A captured frame (JPEG bytes) from the agent.
                emp.last_frame = message["bytes"]
                await broadcast_to_admins({}, binary=message["bytes"], employee_id=employee_id)

            elif "text" in message and message["text"] is not None:
                # Control / heartbeat messages from the agent as JSON.
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "hello":
                    emp.name = data.get("name", emp.name)
                    emp.role = data.get("role", emp.role)
                    await broadcast_to_admins({
                        "type": "status", "id": employee_id, "online": True,
                        "name": emp.name, "role": emp.role,
                    })

    except WebSocketDisconnect:
        pass
    finally:
        emp.agent_ws = None
        emp.streaming = False
        await broadcast_to_admins({"type": "status", "id": employee_id, "online": False})


# ---------------------------------------------------------------------------
# Admin panel connection (the browser UI)
# ---------------------------------------------------------------------------

@app.websocket("/ws/admin")
async def admin_socket(websocket: WebSocket):
    await websocket.accept()
    admin_connections.add(websocket)

    # Send current known state immediately on connect.
    snapshot = [
        {"id": e.id, "name": e.name, "role": e.role, "online": e.agent_ws is not None,
         "streaming": e.streaming}
        for e in employees.values()
    ]
    await websocket.send_text(json.dumps({"type": "snapshot", "employees": snapshot}))

    try:
        while True:
            # Admin can send {"type":"start","id":"emp1"} / {"type":"stop","id":"emp1"}
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


# ---------------------------------------------------------------------------
# Plain REST, in case your admin UI wants to poll instead of websocket
# ---------------------------------------------------------------------------

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


@app.post("/api/employees/{employee_id}/start")
async def start_employee(employee_id: str):
    await _handle_admin_command({"type": "start", "id": employee_id})
    return {"ok": True}


@app.post("/api/employees/{employee_id}/stop")
async def stop_employee(employee_id: str):
    await _handle_admin_command({"type": "stop", "id": employee_id})
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"status": "ok", "employees_known": len(employees)}


# Serves ./static/index.html at "/" - the admin panel UI.
# Mounted LAST so it never shadows the /api and /ws routes above.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
