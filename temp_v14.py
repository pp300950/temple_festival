from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import qrcode
from io import BytesIO
from base64 import b64encode
import uuid
import asyncio
import os
import random

app = FastAPI()

# Game state
players = {}  # pid -> {"name": str, "energy": float, "ready": bool}
player_connections = {}  # pid -> WebSocket
ready_count = 0
winners = []  # list of winner names (รองรับหลายคน)
main_connections = set()
game_status = "waiting"  # "waiting" หรือ "playing"
target = 4.9
MAX_PLAYERS = 20  # จำนวนผู้เล่นสูงสุด (ปรับได้)

MAIN_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Atomic Shooting Gallery!</title>
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; text-align: center; background: #111; color: #fff; margin: 0; padding: 20px; }
        h1 { font-size: 3em; margin: 20px; color: #0ff; text-shadow: 0 0 10px #0ff; }
        #players-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 15px; margin: 30px; }
        .player-card { background: rgba(255,255,255,0.1); padding: 20px; border-radius: 15px; font-size: 1.4em; }
        .player-card.ready { background: rgba(0,255,0,0.3); }
        .player-name { font-weight: bold; font-size: 1.2em; }
        canvas { border: 3px solid #0ff; background: #000; border-radius: 15px; margin: 20px 0; position: relative; }
        #message { font-size: 2em; min-height: 60px; color: #f0f; }
        #winner { font-size: 3em; color: #ff0; text-shadow: 0 0 20px #ff0; margin: 20px; }
        #ready-count { font-size: 2.5em; color: #0f0; margin: 20px; }
        #game-status { font-size: 2em; color: #ff0; margin: 20px; }
        img { max-width: 300px; border: 5px solid #0ff; border-radius: 20px; margin: 20px; }
        .link { font-size: 1.5em; margin: 20px; padding: 15px; background: rgba(0,255,255,0.2); border-radius: 15px; word-break: break-all; }
        .copy-btn, .open-player-btn { padding: 12px 24px; font-size: 1.3em; margin: 10px; border: none; border-radius: 10px; cursor: pointer; }
        .copy-btn { background: #0f0; color: #000; }
        .open-player-btn { background: #00f; color: #fff; text-decoration: none; }
        #start-round-btn { padding: 20px 40px; font-size: 2em; background: #f00; color: #fff; border: none; border-radius: 20px; cursor: pointer; margin: 30px; }
        #start-round-btn:disabled { background: #555; cursor: not-allowed; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; z-index: 100; }
        .modal-content { background: #222; padding: 30px; border-radius: 20px; text-align: center; max-width: 80%; }
        .modal-content h2 { color: #ff0; }
        .close-modal { padding: 10px 20px; background: #f00; color: #fff; border: none; border-radius: 10px; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>🎯 Atomic Shooting Gallery 🎯</h1>
    <h2>สแกน QR Code หรือคลิกลิงก์เพื่อเข้าร่วมเกม</h2>
    
    <img src="data:image/png;base64,{{QR_PLAYER_BASE64}}" alt="QR Code Player">
    <div class="link" id="join-link">{{JOIN_URL}}</div>
    <button class="copy-btn" onclick="copyLink()">คัดลอกลิงก์ผู้เล่น</button>
    <a href="{{JOIN_URL}}" class="open-player-btn" target="_blank">เปิดหน้าผู้เล่นทันที</a>

    <h2>ผู้เล่นในห้องปัจจุบัน:</h2>
    <div id="ready-count">0/0 พร้อม</div>
    <div id="game-status">รอเริ่มรอบ</div>
    <div id="players-grid"></div>
    
    <button id="start-round-btn" onclick="startRound()" disabled>🔥 เริ่มรอบยิง! 🔥</button>
    
    <canvas id="animation" width="900" height="600"></canvas>
    <div id="message"></div>
    <h2 id="winner"></h2>

    <div id="modal" class="modal">
        <div class="modal-content">
            <h2 id="modal-title"></h2>
            <p id="modal-message"></p>
            <button class="close-modal" onclick="closeModal()">ปิด</button>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/reconnecting-websocket/1.0.0/reconnecting-websocket.min.js"></script>
    <script>
        const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new ReconnectingWebSocket(`${protocol}://${location.host}/ws/main`);
        
        const canvas = document.getElementById('animation');
        const ctx = canvas.getContext('2d');
        const mercury = { x: canvas.width / 2, y: canvas.height / 2 + 50, r: 80 };

        function drawScene() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            // อะตอมปรอท
            ctx.beginPath();
            ctx.arc(mercury.x, mercury.y, mercury.r, 0, Math.PI * 2);
            ctx.fillStyle = '#c0c0c0';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 5;
            ctx.stroke();
            ctx.fillStyle = '#fff';
            ctx.font = '20px Arial';
            ctx.fillText('อะตอมปรอท (Mercury Atom)', mercury.x - 120, mercury.y + mercury.r + 40);

            // ป้ายปืน
            ctx.fillStyle = '#0ff';
            ctx.font = '24px Arial';
            ctx.fillText('ปืนอิเล็กตรอน →', 50, mercury.y);
        }

        function animateShot(energy, result, playerName) {
            drawScene();
            let x = 0;
            const y = mercury.y;
            const speed = 10;
            let interval = setInterval(() => {
                drawScene();
                ctx.beginPath();
                ctx.arc(x, y, 18, 0, Math.PI * 2);
                ctx.fillStyle = '#00f';
                ctx.fill();
                ctx.strokeStyle = '#0ff';
                ctx.lineWidth = 3;
                ctx.stroke();
                ctx.fillStyle = '#ff0';
                ctx.font = '18px Arial';
                ctx.fillText(`${playerName} : ${energy} eV`, x - 60, y - 30);

                x += speed;

                if (x >= mercury.x - mercury.r - 18) {
                    clearInterval(interval);
                    document.getElementById('message').textContent = `${playerName} ยิง ${energy} eV`;
                    if (result === 'hit') {
                        document.getElementById('message').textContent += ' → 💥 ถูกเป๊ะ! 💥';
                        for (let i = 0; i < 10; i++) {
                            setTimeout(() => {
                                drawScene();
                                ctx.beginPath();
                                ctx.arc(mercury.x, mercury.y, mercury.r + i*15, 0, Math.PI * 2);
                                ctx.fillStyle = `rgba(255, ${255-i*25}, 0, 0.5)`;
                                ctx.fill();
                            }, i*150);
                        }
                    } else {
                        let bx = mercury.x + mercury.r + 18;
                        let bounceInt = setInterval(() => {
                            drawScene();
                            ctx.beginPath();
                            ctx.arc(bx, y, 18, 0, Math.PI * 2);
                            ctx.fillStyle = '#00f';
                            ctx.fill();
                            bx += 12;
                            if (bx > canvas.width + 100) clearInterval(bounceInt);
                        }, 40);
                        document.getElementById('message').textContent += ' → 🔔 พลาด! กระเด้ง';
                    }
                }
            }, 40);
        }

        ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'state') {
                const data = msg.data;
                document.getElementById('ready-count').textContent = `${data.ready_count}/${data.total_players} พร้อม`;
                document.getElementById('game-status').textContent = data.game_status === 'playing' ? 'กำลังยิง...' : 'รอเริ่มรอบ';
                document.getElementById('winner').textContent = data.winners.length > 0 ? `🏆 ผู้ชนะ: ${data.winners.join(', ')} 🏆` : '';
                
                const grid = document.getElementById('players-grid');
                grid.innerHTML = data.players.map(p => 
                    `<div class="player-card ${p.ready ? 'ready' : ''}">
                        <div class="player-name">🔫 ${p.name}</div>
                        <div>พลังงาน: ${p.energy} eV</div>
                        ${p.ready ? '<div style="color:#0f0;">✅ พร้อม</div>' : ''}
                    </div>`
                ).join('');

                const startBtn = document.getElementById('start-round-btn');
                startBtn.disabled = !(data.total_players > 0 && data.game_status === 'waiting');
            } else if (msg.type === 'shot') {
                animateShot(msg.data.energy, msg.data.result, msg.data.player);
            } else if (msg.type === 'winners_announce') {
                showModal('ผู้ชนะรอบนี้!', msg.data.winners.join(', '));
            } else if (msg.type === 'start_failed') {
                showModal('ยังไม่สามารถเริ่มได้!', `ยังมี ${msg.data.missing} คนที่ยังไม่กดพร้อม`);
            } else if (msg.type === 'all_shots_done') {
            document.getElementById('message').textContent = 'รอบนี้จบแล้ว! ไม่มีผู้ชนะ รอรอบใหม่...';
            drawScene();  // clear animation
        }
        };

        function showModal(title, message) {
            document.getElementById('modal-title').textContent = title;
            document.getElementById('modal-message').textContent = message;
            document.getElementById('modal').style.display = 'flex';
        }

        function closeModal() {
            document.getElementById('modal').style.display = 'none';
        }

        function startRound() {
            ws.send(JSON.stringify({type: "control", action: "start_round"}));
        }

        function copyLink() {
            const link = document.getElementById('join-link').textContent;
            navigator.clipboard.writeText(link).then(() => {
                showModal('สำเร็จ!', 'คัดลอกลิงก์เรียบร้อยแล้ว');
            });
        }
        
        drawScene();
        document.getElementById('message').textContent = '';
        document.getElementById('winner').textContent = '';
    </script>
</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ปืนอิเล็กตรอน</title>
    <style>
        body { font-family: Arial, sans-serif; background: linear-gradient(#111, #003); color: #fff; text-align: center; padding: 20px; }
        h1 { color: #0ff; text-shadow: 0 0 10px #0ff; }
        input { padding: 15px; font-size: 1.2em; width: 80%; margin: 20px; border-radius: 10px; border: none; }
        button { padding: 15px 25px; font-size: 1.5em; margin: 10px; border: none; border-radius: 15px; background: #0f0; color: #000; cursor: pointer; }
        button:disabled { background: #555; cursor: not-allowed; }
        #energy-display { font-size: 4em; color: #ff0; margin: 30px; }
        #scale { font-size: 1.5em; display: flex; justify-content: space-between; width: 80%; margin: 0 auto; }
        #status { font-size: 1.5em; margin: 20px; color: #f0f; min-height: 50px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; z-index: 100; }
        .modal-content { background: #222; padding: 40px; border-radius: 20px; text-align: center; max-width: 80%; }
        .modal-content h2 { color: #ff0; font-size: 2.5em; }
        .close-modal { padding: 10px 20px; background: #f00; color: #fff; border: none; border-radius: 10px; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>🔫 ปืนอิเล็กตรอนของคุณ</h1>
    
    <div id="join-section">
        <input id="name" placeholder="ชื่อคุณ (เช่น แดนนี่)" />
        <button onclick="join()">เข้าร่วมเกม</button>
    </div>

    <div id="game" style="display:none;">
        <h2>ปรับพลังงานอิเล็กตรอน</h2>
        <div id="scale"><span>4.5 eV</span><span>5.5 eV</span></div>
        <div id="energy-display">4.5</div>
        <button onclick="adj(-0.1)">−0.1</button>
        <button onclick="adj(0.1)">+0.1</button>
        <br><br>
        <button id="ready-btn" onclick="setReady()">ยืนยันพร้อมยิง!</button>
        <p id="status">สถานะ: กำลังปรับพลังงาน...</p>
    </div>

    <div id="modal" class="modal">
        <div class="modal-content">
            <h2 id="modal-title"></h2>
            <p id="modal-message"></p>
            <button class="close-modal" onclick="closeModal()">ปิด</button>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/reconnecting-websocket/1.0.0/reconnecting-websocket.min.js"></script>
    <script>
        let pid, energy = 4.5, ws, ready = false;

        async function join() {
            const name = document.getElementById('name').value.trim();
            if (!name) return showModal('ผิดพลาด', 'กรอกชื่อด้วยนะ!');
            const res = await fetch('/join', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
            const data = await res.json();
            if (data.error) {
                showModal('ไม่สามารถเข้าร่วมได้', data.error);
                return;
            }
            pid = data.player_id;

            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new ReconnectingWebSocket(`${protocol}://${location.host}/ws/player/${pid}`);

            ws.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.type === 'round_start') {
                    document.getElementById('status').textContent = 'รอบเริ่มแล้ว! กำลังยิง...';
                } else if (msg.type === 'result') {
                    if (msg.is_winner) {
                        showModal('🎉 ยินดีด้วย! 🎉', 'คุณยิงถูกเป๊ะ!\\nไปหมุนกงล้อรางวัลกัน!', () => {
                            location.href = '/wheel';
                        });
                    } else {
                        showModal('พลาด!', `คุณยิง ${msg.energy} eV (พลาดไปนิดเดียว)\\nรอรอบใหม่เพื่อลุ้นต่อ`, () => {
                            location.href = '/player';
                        });
                    }
                } else if (msg.type === 'please_ready') {
                    showModal('โปรดกดพร้อม!', 'หัวห้องต้องการเริ่มเกม แต่คุณยังไม่ได้กดยืนยันพร้อม');
                } else if (msg.type === 'round_end') {
                    ready = false;
                    document.getElementById('ready-btn').textContent = 'ยืนยันพร้อมยิง!';
                    document.getElementById('status').textContent = 'ปรับพลังงานแล้วกดยืนยันเมื่อพร้อม';
                }
            };

            document.getElementById('join-section').style.display = 'none';
            document.getElementById('game').style.display = 'block';
            document.getElementById('status').textContent = 'ปรับพลังงานแล้วกดยืนยันเมื่อพร้อม';
        }

        function adj(d) {
            energy = Math.round((Math.max(4.5, Math.min(5.5, energy + d))) * 10) / 10;
            document.getElementById('energy-display').textContent = energy;
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action: 'adjust', energy}));
            }
        }

        function setReady() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ready = !ready;
                ws.send(JSON.stringify({action: 'ready', ready}));
                document.getElementById('ready-btn').textContent = ready ? 'ยกเลิกพร้อม' : 'ยืนยันพร้อมยิง!';
                document.getElementById('status').textContent = ready ? 'พร้อมยิงแล้ว! รอหัวห้องเริ่ม...' : 'กำลังปรับพลังงาน...';
            }
        }

        function showModal(title, message, callback = null) {
            document.getElementById('modal-title').textContent = title;
            document.getElementById('modal-message').textContent = message;
            document.getElementById('modal').style.display = 'flex';
            const closeBtn = document.querySelector('.close-modal');
            closeBtn.onclick = () => {
                closeModal();
                if (callback) callback();
            };
        }

        function closeModal() {
            document.getElementById('modal').style.display = 'none';
        }
    </script>
</body>
</html>
"""

WHEEL_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>หมุนกงล้อรางวัล!</title>
    <style>
        body { font-family: Arial, sans-serif; background: linear-gradient(#003, #111); color: #fff; text-align: center; padding: 20px; }
        h1 { color: #ff0; text-shadow: 0 0 15px #ff0; }
        canvas { border: 5px solid #0ff; border-radius: 50%; margin: 30px; }
        button { padding: 15px 30px; font-size: 1.8em; background: #f00; color: #fff; border: none; border-radius: 15px; cursor: pointer; }
        #result { font-size: 3em; margin: 40px; color: #ff0; }
        .close-btn { position: absolute; top: 20px; right: 20px; font-size: 2em; cursor: pointer; }
    </style>
</head>
<body>
    <div class="close-btn" onclick="location.href='/player'">✖</div>
    <h1>🎡 หมุนกงล้อรางวัล 🎡</h1>
    <canvas id="wheel" width="400" height="400"></canvas>
    <br>
    <button id="spin-btn" onclick="spin()">หมุน!</button>
    <div id="result"></div>

    <script>
        const canvas = document.getElementById('wheel');
        const ctx = canvas.getContext('2d');
        const sectors = ['1 ลูกอม', '2 ลูกอม', '3 ลูกอม', '4 ลูกอม', '5 ลูกอม', 'รางวัลปริศนา'];
        const colors = ['#ff0', '#0f0', '#0ff', '#f0f', '#ff5', '#f80'];
        let currentAngle = 0;
        let spinning = false;

        function drawWheel() {
            const angleStep = (Math.PI * 2) / sectors.length;
            sectors.forEach((text, i) => {
                ctx.beginPath();
                ctx.fillStyle = colors[i];
                ctx.moveTo(200, 200);
                ctx.arc(200, 200, 200, currentAngle + i*angleStep, currentAngle + (i+1)*angleStep);
                ctx.fill();
                ctx.save();
                ctx.translate(200, 200);
                ctx.rotate(currentAngle + i*angleStep + angleStep/2);
                ctx.fillStyle = '#000';
                ctx.font = 'bold 24px Arial';
                ctx.fillText(text, 80, 10);
                ctx.restore();
            });
            // Pointer
            ctx.beginPath();
            ctx.moveTo(380, 200);
            ctx.lineTo(340, 180);
            ctx.lineTo(340, 220);
            ctx.fillStyle = '#f00';
            ctx.fill();
        }

        function spin() {
            if (spinning) return;
            spinning = true;
            document.getElementById('spin-btn').disabled = true;
            const spinAngle = 3600 + Math.random() * 3600;
            let startAngle = currentAngle;
            let time = 0;
            const duration = 5000;
            const anim = setInterval(() => {
                time += 30;
                const progress = Math.min(time / duration, 1);
                const ease = 1 - Math.pow(1 - progress, 3);
                currentAngle = startAngle + spinAngle * ease;
                drawWheel();
                if (progress >= 1) {
                    clearInterval(anim);
                    const finalSector = Math.floor(((360 - (currentAngle % 360)) / 360) * sectors.length);
                    document.getElementById('result').textContent = `เย่! คุณได้ ${sectors[finalSector]} 🍬`;
                    spinning = false;
                }
            }, 30);
        }

        drawWheel();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def main_screen(request: Request):
    base_url = str(request.base_url).rstrip("/")
    join_url = base_url + "/player"
    
    qr_player = qrcode.QRCode(box_size=10, border=4)
    qr_player.add_data(join_url)
    qr_player.make(fit=True)
    img_player = qr_player.make_image(fill='black', back_color='white')
    buf_player = BytesIO()
    img_player.save(buf_player, format="PNG")
    qr_player_b64 = b64encode(buf_player.getvalue()).decode()
    
    html = MAIN_HTML.replace("{{QR_PLAYER_BASE64}}", qr_player_b64)\
                    .replace("{{JOIN_URL}}", join_url)
    return HTMLResponse(html)

@app.get("/player", response_class=HTMLResponse)
async def player_screen():
    return HTMLResponse(PLAYER_HTML)

@app.get("/wheel", response_class=HTMLResponse)
async def wheel_screen():
    return HTMLResponse(WHEEL_HTML)

@app.post("/join")
async def join(request: Request):
    if game_status == "playing":
        return JSONResponse({"error": "เกมกำลังดำเนินอยู่ โปรดรอรอบใหม่"})
    if len(players) >= MAX_PLAYERS:
        return JSONResponse({"error": "ห้องเต็มแล้ว โปรดรอสักครู่"})
    
    data = await request.json()
    name = data["name"].strip()
    if not name:
        return JSONResponse({"error": "กรุณากรอกชื่อ"})
    pid = str(uuid.uuid4())
    players[pid] = {"name": name, "energy": 4.5, "ready": False}
    await broadcast_state()
    return {"player_id": pid}

@app.websocket("/ws/main")
async def ws_main(ws: WebSocket):
    global game_status
    await ws.accept()
    main_connections.add(ws)
    await broadcast_state()  # ส่ง state ปัจจุบันให้จอที่ connect ใหม่ทันที
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "control" and msg.get("action") == "start_round":
                if game_status == "waiting" and len(players) > 0:
                    if ready_count < len(players):
                        missing = len(players) - ready_count
                        # ส่ง start_failed ให้ทุกจอใหญ่
                        for conn in main_connections.copy():
                            try:
                                await conn.send_json({"type": "start_failed", "data": {"missing": missing}})
                            except:
                                main_connections.remove(conn)
                        # แจ้งผู้เล่นที่ยังไม่พร้อม
                        for pid, p in players.items():
                            if not p["ready"] and pid in player_connections:
                                try:
                                    await player_connections[pid].send_json({"type": "please_ready"})
                                except:
                                    pass
                    else:
                        game_status = "playing"
                        await broadcast_state()
                        await process_round()
    except WebSocketDisconnect:
        main_connections.remove(ws)

@app.websocket("/ws/player/{pid}")
async def ws_player(ws: WebSocket, pid: str):
    global ready_count, player_connections
    if pid not in players:
        await ws.close()
        return
    await ws.accept()
    player_connections[pid] = ws
    try:
        while True:
            msg = await ws.receive_json()
            if msg["action"] == "adjust":
                e = round(float(msg["energy"]), 1)
                if 4.5 <= e <= 5.5:
                    players[pid]["energy"] = e
                    await broadcast_state()
            elif msg["action"] == "ready":
                was_ready = players[pid]["ready"]
                players[pid]["ready"] = msg["ready"]
                if msg["ready"] and not was_ready:
                    ready_count += 1
                elif not msg["ready"] and was_ready:
                    ready_count -= 1
                await broadcast_state()
    except WebSocketDisconnect:
        if players[pid]["ready"]:
            ready_count -= 1
        players.pop(pid, None)
        player_connections.pop(pid, None)
        await broadcast_state()

async def broadcast_state():
    player_list = [{"name": v["name"], "energy": v["energy"], "ready": v["ready"]} for v in players.values()]
    data = {
        "type": "state",
        "data": {
            "players": player_list,
            "ready_count": ready_count,
            "total_players": len(players),
            "game_status": game_status,
            "winners": winners
        }
    }
    for conn in main_connections.copy():
        try:
            await conn.send_json(data)
        except:
            main_connections.remove(conn)
            
async def process_round():
    global winners, ready_count, game_status
    winners = []
    
    for pws in player_connections.values():
        try:
            await pws.send_json({"type": "round_start"})
        except:
            pass
    
    await asyncio.sleep(2)
    
    results = []
    for pid, p in players.items():
        energy = p["energy"]
        hit = abs(energy - target) <= 0.01
        results.append((pid, p["name"], energy, hit))
        if hit:
            winners.append(p["name"])
    
    for _, name, energy, hit_result in results:
        await broadcast_shot(name, energy, "hit" if hit_result else "miss")
        await asyncio.sleep(6)
    
    if winners:
        for conn in main_connections.copy():
            try:
                await conn.send_json({"type": "winners_announce", "data": {"winners": winners}})
            except:
                main_connections.remove(conn)
    
    if not winners:
        for conn in main_connections.copy():
            try:
                await conn.send_json({"type": "all_shots_done"})
            except:
                main_connections.remove(conn)
                
    for pid, name, energy, is_winner in results:
        if pid in player_connections:
            try:
                await player_connections[pid].send_json({
                    "type": "result",
                    "is_winner": is_winner,
                    "energy": energy
                })
            except:
                pass
    
    for pws in player_connections.values():
        try:
            await pws.send_json({"type": "round_end"})
        except:
            pass
    
    game_status = "waiting"
    ready_count = 0
    for p in players.values():
        p["ready"] = False
    await broadcast_state()
    
    if winners:
        await asyncio.sleep(10)
        winners = []
        await broadcast_state()

async def broadcast_shot(player_name, energy, result):
    data = {
        "type": "shot",
        "data": {"player": player_name, "energy": energy, "result": result}
    }
    for conn in main_connections.copy():
        try:
            await conn.send_json(data)
        except:
            main_connections.remove(conn)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)