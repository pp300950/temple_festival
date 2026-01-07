from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
import uvicorn
import qrcode
from io import BytesIO
from base64 import b64encode
import uuid
import asyncio
import os

app = FastAPI()

# Game state
players = {}  # pid -> {"name": str, "energy": float, "ready": bool}
player_connections = {}  # pid -> WebSocket (สำหรับส่งข้อความส่วนตัว)
ready_count = 0
winner = None
main_ws = None
game_status = "waiting"  # "waiting" หรือ "playing"
target = 4.9

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
        h2 { font-size: 2em; color: #ff0; }
        #players { list-style: none; padding: 0; font-size: 1.5em; }
        #players li { padding: 10px; background: rgba(255,255,255,0.1); margin: 5px; border-radius: 10px; }
        #players li.ready { background: rgba(0,255,0,0.3); }
        canvas { border: 3px solid #0ff; background: #000; border-radius: 15px; margin: 20px 0; }
        #message { font-size: 2em; min-height: 60px; color: #f0f; }
        #winner { font-size: 3em; color: #ff0; text-shadow: 0 0 20px #ff0; margin: 20px; }
        #ready-count { font-size: 2.5em; color: #0f0; margin: 20px; }
        #game-status { font-size: 2em; color: #ff0; margin: 20px; }
        img { max-width: 300px; border: 5px solid #0ff; border-radius: 20px; margin: 20px; }
        .link { font-size: 1.5em; margin: 20px; padding: 15px; background: rgba(0,255,255,0.2); border-radius: 15px; word-break: break-all; }
        .copy-btn { padding: 10px 20px; font-size: 1.2em; background: #0f0; color: #000; border: none; border-radius: 10px; cursor: pointer; margin: 10px; }
        .btn { padding: 15px 30px; font-size: 1.5em; background: #00f; color: #fff; border: none; border-radius: 15px; cursor: pointer; margin: 20px; text-decoration: none; display: inline-block; }
        #start-round-btn { padding: 20px 40px; font-size: 2em; background: #f00; color: #fff; border: none; border-radius: 20px; cursor: pointer; margin: 30px; }
        #start-round-btn:disabled { background: #555; cursor: not-allowed; }
    </style>
</head>
<body>
    <h1>🎯 Atomic Shooting Gallery 🎯</h1>
    <h2>สแกน QR Code เพื่อเข้าร่วมเกม หรือเข้าหน้าควบคุมผู้เล่น</h2>
    
    <div style="display: flex; justify-content: center; gap: 40px; flex-wrap: wrap;">
        <div>
            <h2>QR Code เข้าร่วมเกม (ผู้เล่น)</h2>
            <img src="data:image/png;base64,{{QR_PLAYER_BASE64}}" alt="QR Code Player">
            <div class="link" id="join-link">{{JOIN_URL}}</div>
            <button class="copy-btn" onclick="copyLink()">คัดลอกลิงก์ผู้เล่น</button>
        </div>
        
        <div>
            <h2>QR Code จอใหญ่ (เซิร์ฟเวอร์/หน้าจอหลัก)</h2>
            <img src="data:image/png;base64,{{QR_MAIN_BASE64}}" alt="QR Code Main">
            <div class="link">{{MAIN_URL}}</div>
            <a href="{{MAIN_URL}}" class="btn" target="_blank">เปิดจอใหญ่ทันที</a>
        </div>
    </div>

    <h2>ผู้เล่นในห้องปัจจุบัน:</h2>
    <div id="ready-count">{{READY_COUNT}}/{{TOTAL_PLAYERS}} พร้อม</div>
    <div id="game-status">รอเริ่มรอบ</div>
    <ul id="players"></ul>
    
    <button id="start-round-btn" onclick="startRound()" disabled>🔥 เริ่มรอบยิง! 🔥</button>
    
    <canvas id="animation" width="900" height="500"></canvas>
    <div id="message"></div>
    <h2 id="winner"></h2>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/reconnecting-websocket/1.0.0/reconnecting-websocket.min.js"></script>
    <script>
        const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new ReconnectingWebSocket(`${protocol}://${location.host}/ws/main`);
        
        const canvas = document.getElementById('animation');
        const ctx = canvas.getContext('2d');
        const mercury = { x: canvas.width / 2, y: canvas.height / 2, r: 80 };

        function drawMercury() {
            ctx.beginPath();
            ctx.arc(mercury.x, mercury.y, mercury.r, 0, Math.PI * 2);
            ctx.fillStyle = '#c0c0c0';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 5;
            ctx.stroke();
        }

        ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'state') {
                const data = msg.data;
                document.getElementById('ready-count').textContent = `${data.ready_count}/${data.total_players} พร้อม`;
                document.getElementById('game-status').textContent = data.game_status === 'playing' ? 'กำลังยิง...' : 'รอเริ่มรอบ';
                document.getElementById('players').innerHTML = data.players.map(p => 
                    `<li class="${p.ready ? 'ready' : ''}">🔫 ${p.name} (${p.energy} eV) ${p.ready ? '✅' : ''}</li>`
                ).join('');
                document.getElementById('winner').textContent = data.winner ? `🏆 ชนะเลิศ: ${data.winner} 🏆` : '';
                
                const startBtn = document.getElementById('start-round-btn');
                if (data.total_players > 0 && data.game_status === 'waiting') {
                    startBtn.disabled = false;
                } else {
                    startBtn.disabled = true;
                }
            } else if (msg.type === 'shot') {
                document.getElementById('message').textContent = 
                    `${msg.data.player} ยิงอิเล็กตรอน ${msg.data.energy} eV ! ${msg.data.result === 'hit' ? '💥 ถูกต้อง!' : ''}`;
                animateShot(msg.data.energy, msg.data.result);
            } else if (msg.type === 'all_shots_done') {
                document.getElementById('message').textContent = 'รอบนี้จบแล้ว! ไม่มีผู้ชนะ รอรอบใหม่...';
            }
        };

        function animateShot(energy, result) {
            let x = 0;
            const y = mercury.y;
            const speed = 15;
            const interval = setInterval(() => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                drawMercury();

                ctx.beginPath();
                ctx.arc(x, y, 15, 0, Math.PI * 2);
                ctx.fillStyle = '#00f';
                ctx.fill();

                x += speed;

                if (x >= mercury.x - mercury.r - 15) {
                    clearInterval(interval);
                    if (result === 'hit') {
                        for (let i = 0; i < 5; i++) {
                            setTimeout(() => {
                                ctx.clearRect(0, 0, canvas.width, canvas.height);
                                drawMercury();
                                ctx.beginPath();
                                ctx.arc(mercury.x, mercury.y, mercury.r + i*20, 0, Math.PI * 2);
                                ctx.fillStyle = `rgba(255,255,${100-i*20},0.6)`;
                                ctx.fill();
                            }, i*200);
                        }
                        document.getElementById('message').textContent += ' 💥 เกิดการถ่ายเทพลังงาน!';
                    } else {
                        let bx = mercury.x + mercury.r + 15;
                        const bounceInt = setInterval(() => {
                            ctx.clearRect(0, 0, canvas.width, canvas.height);
                            drawMercury();
                            ctx.beginPath();
                            ctx.arc(bx, y, 15, 0, Math.PI * 2);
                            ctx.fillStyle = '#00f';
                            ctx.fill();
                            bx += 10;
                            if (bx > canvas.width + 50) clearInterval(bounceInt);
                        }, 30);
                        document.getElementById('message').textContent += ' 🔔 กระเด้ง!';
                    }
                }
            }, 30);
        }

        function startRound() {
            ws.send(JSON.stringify({type: "control", action: "start_round"}));
        }

        function copyLink() {
            const link = document.getElementById('join-link').textContent;
            navigator.clipboard.writeText(link).then(() => alert('คัดลอกลิงก์เรียบร้อย!'));
        }
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
        #energy { font-size: 3em; color: #ff0; }
        #status { font-size: 1.5em; margin: 20px; color: #f0f; min-height: 50px; }
    </style>
</head>
<body>
    <h1>🔫 ปืนอิเล็กตรอนของคุณ</h1>
    
    <div id="join-section">
        <input id="name" placeholder="ชื่อคุณ (เช่น แดนนี่)" />
        <button onclick="join()">เข้าร่วมเกม</button>
    </div>

    <div id="game" style="display:none;">
        <h2>ปรับพลังงานอิเล็กตรอน (เป้าหมาย ~4.9 eV)</h2>
        <div id="energy">4.5</div>
        <button onclick="adj(-0.1)">−0.1</button>
        <button onclick="adj(0.1)">+0.1</button>
        <br><br>
        <button id="ready-btn" onclick="setReady()">ยืนยันพร้อมยิง!</button>
        <p id="status">สถานะ: กำลังปรับพลังงาน...</p>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/reconnecting-websocket/1.0.0/reconnecting-websocket.min.js"></script>
    <script>
        let pid, energy = 4.5, ws, ready = false;

        async function join() {
            const name = document.getElementById('name').value.trim();
            if (!name) return alert('กรอกชื่อด้วยนะ!');
            const res = await fetch('/join', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
            const data = await res.json();
            pid = data.player_id;

            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            ws = new ReconnectingWebSocket(`${protocol}://${location.host}/ws/player/${pid}`);

            document.getElementById('join-section').style.display = 'none';
            document.getElementById('game').style.display = 'block';
            document.getElementById('status').textContent = 'ปรับพลังงานแล้วกดยืนยันเมื่อพร้อม';

            ws.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.type === 'round_start') {
                    document.getElementById('status').textContent = 'รอบเริ่มแล้ว! กำลังยิง...';
                } else if (msg.type === 'result') {
                    if (msg.hit) {
                        alert('🎉 ยิงถูกเป๊ะ 4.9 eV! คุณคือผู้ชนะ!!! 🏆');
                        document.getElementById('status').textContent = 'คุณชนะรอบนี้!';
                    } else {
                        alert(`พลาดไปนิดเดียว (${msg.energy} eV)! ปรับค่าใหม่ในรอบถัดไป`);
                        document.getElementById('status').textContent = 'พลาด! รอรอบใหม่...';
                    }
                    ready = false;
                    document.getElementById('ready-btn').textContent = 'ยืนยันพร้อมยิง!';
                }
            };
        }

        function adj(d) {
            energy = Math.round((Math.max(4.5, Math.min(5.5, energy + d))) * 10) / 10;
            document.getElementById('energy').textContent = energy;
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
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def main_screen(request: Request):
    base_url = str(request.base_url).rstrip("/")
    main_url = base_url + "/"
    join_url = base_url + "/player"
    
    qr_player = qrcode.QRCode(box_size=10, border=4)
    qr_player.add_data(join_url)
    qr_player.make(fit=True)
    img_player = qr_player.make_image(fill='black', back_color='white')
    buf_player = BytesIO()
    img_player.save(buf_player, format="PNG")
    qr_player_b64 = b64encode(buf_player.getvalue()).decode()
    
    qr_main = qrcode.QRCode(box_size=10, border=4)
    qr_main.add_data(main_url)
    qr_main.make(fit=True)
    img_main = qr_main.make_image(fill='black', back_color='white')
    buf_main = BytesIO()
    img_main.save(buf_main, format="PNG")
    qr_main_b64 = b64encode(buf_main.getvalue()).decode()
    
    current_ready = len([p for p in players.values() if p.get("ready", False)])
    total_players = len(players)
    
    html = MAIN_HTML.replace("{{QR_PLAYER_BASE64}}", qr_player_b64)\
                    .replace("{{QR_MAIN_BASE64}}", qr_main_b64)\
                    .replace("{{JOIN_URL}}", join_url)\
                    .replace("{{MAIN_URL}}", main_url)\
                    .replace("{{READY_COUNT}}", str(current_ready))\
                    .replace("{{TOTAL_PLAYERS}}", str(total_players))
    return HTMLResponse(html)

@app.get("/player", response_class=HTMLResponse)
async def player_screen():
    return HTMLResponse(PLAYER_HTML)

@app.post("/join")
async def join(request: Request):
    data = await request.json()
    name = data["name"].strip()
    pid = str(uuid.uuid4())
    players[pid] = {"name": name, "energy": 4.5, "ready": False}
    await broadcast_state()
    return {"player_id": pid}

@app.websocket("/ws/main")
async def ws_main(ws: WebSocket):
    global main_ws, game_status
    await ws.accept()
    main_ws = ws
    await broadcast_state()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "control" and msg.get("action") == "start_round":
                if game_status == "waiting" and len(players) > 0:
                    game_status = "playing"
                    await broadcast_state()
                    await process_round()
    except WebSocketDisconnect:
        main_ws = None

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
    if main_ws:
        player_list = [{"name": v["name"], "energy": v["energy"], "ready": v["ready"]} for v in players.values()]
        await main_ws.send_json({
            "type": "state",
            "data": {
                "players": player_list,
                "ready_count": ready_count,
                "total_players": len(players),
                "game_status": game_status,
                "winner": winner
            }
        })

async def process_round():
    global winner, ready_count, game_status
    # แจ้งผู้เล่นทุกรายว่ารอบเริ่ม
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
            winner = p["name"]
    
    # ยิงทีละคนบนจอใหญ่
    for _, name, energy, hit_result in results:
        await broadcast_shot(name, energy, "hit" if hit_result else "miss")
        await asyncio.sleep(4)
    
    if not winner:
        if main_ws:
            await main_ws.send_json({"type": "all_shots_done"})
    
    # แจ้งผลส่วนตัวให้ผู้เล่นแต่ละคน
    for pid, name, energy, hit in results:
        if pid in player_connections:
            try:
                await player_connections[pid].send_json({
                    "type": "result",
                    "hit": hit,
                    "energy": energy
                })
            except:
                pass
    
    # รีเซ็ตสถานะสำหรับรอบใหม่
    game_status = "waiting"
    ready_count = 0
    for p in players.values():
        p["ready"] = False
    await broadcast_state()
    
    if winner:
        await asyncio.sleep(8)
        winner = None
        await broadcast_state()

async def broadcast_shot(player_name, energy, result):
    if main_ws:
        await main_ws.send_json({
            "type": "shot",
            "data": {"player": player_name, "energy": energy, "result": result}
        })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)