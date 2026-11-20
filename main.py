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

Ab doosri file bhejta hoon, kyunki ek message mein saari fit nahi hogi.

aur is window ko bada krke bhi dekhna ho dekhske

Adding click-to-fullscreen for the video tiles.

Theek hai, ye bhi add kar dete hain — tile par click karne se screen bada (fullscreen modal) dikhega.

Ab doosri file — static/index.html (poora replace karna hai, login screen + bada view dono ke saath):

html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Live Screens</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{color-scheme:light dark}
  body{margin:0;font-family:Inter,system-ui,sans-serif;background:#F1F4F8;color:#0F172A}
  .wrap{display:flex;min-height:100vh}
  aside{width:220px;flex:none;background:#fff;border-right:1px solid #DDE3EA;padding:20px 12px;box-sizing:border-box}
  .logo{font-weight:700;font-size:18px;padding:0 12px 20px;color:#1D4ED8}
  main{flex:1;min-width:0;padding:24px 28px;box-sizing:border-box}
  .topbar{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:20px}
  h1{margin:0;font-size:22px;font-weight:700;flex:1}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}
  .tile{background:#fff;border:1px solid #DDE3EA;border-radius:10px;overflow:hidden}
  .scr{height:150px;position:relative;margin:10px 10px 0;border-radius:6px;overflow:hidden;background:#111;display:flex;align-items:center;justify-content:center;cursor:pointer}
  .scr img{width:100%;height:100%;object-fit:cover;display:block}
  .scr .placeholder{color:#94A3B8;font-size:12px}
  .badge{position:absolute;top:8px;left:8px;font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px}
  .live{background:#14532D;color:#fff}
  .off{background:#64748B;color:#fff}
  .who{display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:1px solid #E8ECF1}
  .av{width:34px;height:34px;border-radius:50%;background:#DBEAFE;color:#1E3A8A;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;flex:none}
  .nm{flex:1;min-width:0}
  .nm b{font-size:13px;font-weight:600;display:block}
  .nm small{font-size:11px;color:#475569}
  button.start{background:#15803D;color:#fff;border:0;border-radius:6px;font:600 13px Inter,sans-serif;padding:0 16px;min-height:40px;cursor:pointer}
  button.start.active{background:#B91C1C}
  button.start:disabled{background:#CBD5E1;color:#334155;cursor:not-allowed}

  /* Login screen */
  #loginScreen{position:fixed;inset:0;background:#F1F4F8;display:flex;align-items:center;justify-content:center;z-index:50}
  #loginBox{background:#fff;border:1px solid #DDE3EA;border-radius:12px;padding:32px;width:300px;box-shadow:0 10px 30px rgba(0,0,0,.08)}
  #loginBox h2{margin:0 0 16px;font-size:18px}
  #loginBox input{width:100%;box-sizing:border-box;margin-bottom:12px;padding:10px;border:1px solid #CBD5E1;border-radius:6px;font-size:14px}
  #loginBox button{width:100%;padding:10px;border:0;border-radius:6px;background:#1D4ED8;color:#fff;font-weight:600;cursor:pointer}
  #loginError{color:#B91C1C;font-size:13px;margin-bottom:8px;min-height:16px}

  /* Fullscreen viewer modal */
  #modal{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;z-index:40;flex-direction:column}
  #modal.open{display:flex}
  #modal img{max-width:92vw;max-height:80vh;border-radius:8px}
  #modal .modalTitle{color:#fff;font-weight:600;margin-bottom:12px}
  #modal .closeBtn{position:absolute;top:16px;right:20px;color:#fff;font-size:28px;cursor:pointer;background:none;border:0}
</style>
</head>
<body>

<div id="loginScreen">
  <div id="loginBox">
    <h2>Admin Login</h2>
    <div id="loginError"></div>
    <input id="loginUser" placeholder="Username" autocomplete="username">
    <input id="loginPass" type="password" placeholder="Password" autocomplete="current-password">
    <button id="loginBtn">Sign in</button>
  </div>
</div>

<div id="modal">
  <button class="closeBtn" id="closeModal">&times;</button>
  <div class="modalTitle" id="modalTitle"></div>
  <img id="modalImg">
</div>

<div class="wrap">
  <aside>
    <div class="logo">Your Company</div>
  </aside>
  <main>
    <div class="topbar">
      <h1>Live Screens</h1>
      <span id="conn" style="font-size:13px;color:#64748B"></span>
    </div>
    <div class="grid" id="grid"></div>
  </main>
</div>

<script>
const loginScreen = document.getElementById("loginScreen");
const loginBtn = document.getElementById("loginBtn");
const loginError = document.getElementById("loginError");
const modal = document.getElementById("modal");
const modalImg = document.getElementById("modalImg");
const modalTitle = document.getElementById("modalTitle");
const grid = document.getElementById("grid");
const connEl = document.getElementById("conn");
const employees = new Map();

loginBtn.onclick = async () => {
  const username = document.getElementById("loginUser").value;
  const password = document.getElementById("loginPass").value;
  loginError.textContent = "";
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    });
    const data = await res.json();
    if (data.ok) {
      loginScreen.style.display = "none";
      connect();
    } else {
      loginError.textContent = data.error || "Login failed";
    }
  } catch (e) {
    loginError.textContent = "Could not reach server";
  }
};

document.getElementById("closeModal").onclick = () => modal.classList.remove("open");
modal.onclick = (e) => { if (e.target === modal) modal.classList.remove("open"); };

function initials(name) {
  return name.split(" ").filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join("");
}

function openModal(e) {
  if (!e.imgUrl) return;
  modalImg.src = e.imgUrl;
  modalTitle.textContent = e.name || e.id;
  modal.classList.add("open");
}

function render() {
  grid.innerHTML = "";
  for (const [id, e] of employees) {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.innerHTML = `
      <div class="scr" data-id="${id}">
        ${e.imgUrl ? `<img src="${e.imgUrl}">` : `<span class="placeholder">${e.online ? "Waiting for frame…" : "No signal"}</span>`}
        <span class="badge ${e.online ? "live" : "off"}">${e.online ? (e.streaming ? "Live" : "Idle") : "Offline"}</span>
      </div>
      <div class="who">
        <span class="av">${initials(e.name || id)}</span>
        <div class="nm"><b>${e.name || id}</b><small>${e.role || ""}</small></div>
        <button class="start ${e.streaming ? "active" : ""}" data-id="${id}" ${e.online ? "" : "disabled"}>
          ${e.streaming ? "Stop" : "Start"}
        </button>
      </div>`;
    grid.appendChild(tile);
  }
  grid.querySelectorAll(".scr").forEach(div => {
    div.onclick = () => openModal(employees.get(div.dataset.id));
  });
  grid.querySelectorAll("button.start").forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.id;
      const e = employees.get(id);
      ws.send(JSON.stringify({ type: e.streaming ? "stop" : "start", id }));
    };
  });
}

let ws;
function connect() {
  const WS_PROTOCOL = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${WS_PROTOCOL}://${location.host}/ws/admin`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => { connEl.textContent = "Connected"; };
  ws.onclose = (ev) => {
    if (ev.code === 4401) {
      connEl.textContent = "";
      loginScreen.style.display = "flex";
      loginError.textContent = "Session expired, please sign in again";
      return;
    }
    connEl.textContent = "Disconnected — retrying…";
    setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      const data = JSON.parse(ev.data);
      if (data.type === "snapshot") {
        data.employees.forEach(e => employees.set(e.id, { ...e, imgUrl: null }));
        render();
      } else if (data.type === "status") {
        const prev = employees.get(data.id) || {};
        employees.set(data.id, {
          ...prev, id: data.id,
          name: data.name ?? prev.name, role: data.role ?? prev.role,
          online: data.online, streaming: data.online ? (data.streaming ?? prev.streaming) : false,
        });
        render();
      }
    } else {
      const bytes = new Uint8Array(ev.data);
      const nl = bytes.indexOf(10);
      const id = new TextDecoder().decode(bytes.slice(0, nl));
      const jpeg = bytes.slice(nl + 1);
      const blob = new Blob([jpeg], { type: "image/jpeg" });
      const url = URL.createObjectURL(blob);
      const prev = employees.get(id) || {};
      if (prev.imgUrl) URL.revokeObjectURL(prev.imgUrl);
      employees.set(id, { ...prev, id, imgUrl: url, online: true, streaming: true });
      render();
      if (modal.classList.contains("open") && modalTitle.textContent === (employees.get(id).name || id)) {
        modalImg.src = url;
      }
    }
  };
}
</script>
</body>
</html>
