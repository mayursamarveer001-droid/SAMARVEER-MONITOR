"""
Live Screen Monitoring - Backend Server
----------------------------------------
Run: pip install -r requirements.txt
     uvicorn main:app --host 0.0.0.0 --port 8000
"""

import json
import time
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


@app.websocket("/ws/agent/{employee_id}")
async def agent_socket(websocket: WebSocket, employee_id: str):
    await websocket.accept()
    emp = get_or_create_employee(employee_id)
    emp.agent_ws = websocket
    emp.last_seen = time.time()

    await broadcast_to_admins({
        "type": "status", "id": employee_id, "online": True,
        "name": emp.name, "role": emp.role, "streaming": emp.streaming,
    })

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
                    # Only use the name/role the agent sends if the admin
                    # hasn't already set a custom name for this employee.
                    if not emp.name or emp.name == emp.id:
                        emp.name = data.get("name", emp.name)
                    if not emp.role:
                        emp.role = data.get("role", emp.role)
                    await broadcast_to_admins({
                        "type": "status", "id": employee_id, "online": True,
                        "name": emp.name, "role": emp.role, "streaming": emp.streaming,
                    })

    except WebSocketDisconnect:
        pass
    finally:
        emp.agent_ws = None
        emp.streaming = False
        await broadcast_to_admins({"type": "status", "id": employee_id, "online": False})


@app.websocket("/ws/admin")
async def
