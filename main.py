from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
import uvicorn
import qrcode
from io import BytesIO
from base64 import b64encode
import uuid
import asyncio

app = FastAPI()

# Game state
players = {}      # {player_id: {'name': str, 'energy': float}}
queue = []        # list of player_ids
target = 4.9
winner = None
main_ws = None    # WebSocket ของจอหลัก
barrage_mode = False  # ถ้าอยากให้ยิงพร้อมกันทุกคน เปลี่ยนเป็น True

# HTML ทั้งหมดฝังใน Python เลย
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
        #queue { list-style: none; padding: 0; font-size: 1.5em; }
        #queue li { padding: 10px; background: rgba(255,255,255,0.1); margin: 5px; border-radius: 10px; }
        canvas { border: 3px solid #0ff; background: #000; border-radius: 15px; margin: 20px 0; }
        #message { font-size: 2em; min-height: 60px; color: #f0f; }
        #winner { font-size: 3em; color: #ff0; text-shadow: 0 0 20px #ff0; margin: 20px; }
        img { max-width: 300px; border: 5px solid #0ff; border-radius: 20px; margin: 20px; }
    </style>
</head>
<body>
    <h1>🎯 Atomic Shooting Gallery 🎯</h1>
    <h2>สแกน QR Code เพื่อยิงอิเล็กตรอนใส่ปรอท!</h2>
    <img src="data:image/png;base64,{{QR_BASE64}}" alt="QR Code">
    <h2>คิวผู้เล่น:</h2>
    <ul id="queue"></ul>
    <canvas id="animation" width="900" height="500"></canvas>
    <div id="message"></div>
    <h2 id="winner"></h2>

    <script src="https://cdn.jsdelivr.net/npm/reconnecting-websocket@4.4.0/dist/reconnecting-websocket.min.js"></script>
    <script>
        const ws = new ReconnectingWebSocket(`wss://${location.host}/ws/main`);
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
                document.getElementById('queue').innerHTML = msg.data.queue.map(n => `<li>🔫 ${n}</li>`).join('');
                document.getElementById('winner').textContent = msg.data.winner ? `🏆 ชนะเลิศ: ${msg.data.winner} 🏆` : '';
            } else if (msg.type === 'shot') {
                document.getElementById('message').textContent = 
                    `${msg.data.player} ยิงอิเล็กตรอน ${msg.data.energy} eV !`;
                animateShot(msg.data.energy, msg.data.result);
            }
        };

        function animateShot(energy, result) {
            let x = 0;
            const y = mercury.y;
            const speed = 15;
            const interval = setInterval(() => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                drawMercury();

                // อิเล็กตรอน
                ctx.beginPath();
                ctx.arc(x, y, 15, 0, Math.PI * 2);
                ctx.fillStyle = '#00f';
                ctx.fill();

                x += speed;

                if (x >= mercury.x - mercury.r - 15) {
                    clearInterval(interval);
                    if (result === 'hit') {
                        // ชนแล้วดูดกลืน + เรืองแสง
                        ctx.fillStyle = 'rgba(255,255,0,0.8)';
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
                        document.getElementById('message').textContent = '💥 เกิดการถ่ายเทพลังงาน! UV ปล่อยออกมาแล้ว!';
                    } else {
                        // กระเด้ง
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
                        document.getElementById('message').textContent = '🔔 กระเด้ง! ยังไม่มีอะไรเกิดขึ้น...';
                    }
                }
            }, 30);
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
        button:disabled { background: #555; }
        #energy { font-size: 3em; color: #ff0; }
        #status { font-size: 1.5em; margin: 20px; color: #f0f; }
    </style>
</head>
<body>
    <h1>🔫 ปืนอิเล็กตรอนของคุณ</h1>
    <input id="name" placeholder="ชื่อคุณ (เช่น แดนนี่)" />
    <button onclick="join()">เข้าร่วมเกม</button>

    <div id="game" style="display:none;">
        <h2>ปรับพลังงานอิเล็กตรอน</h2>
        <div id="energy">4.5</div>
        <button onclick="adj(-0.1)">−0.1</button>
        <button onclick="adj(0.1)">+0.1</button>
        <br><br>
        <button id="qbtn" onclick="joinQueue()">เข้าคิว</button>
        <button id="sbtn" onclick="shoot()" disabled>🔥 ยิง!</button>
        <p id="status">สถานะ: รอเข้าร่วม</p>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/reconnecting-websocket@4.4.0/dist/reconnecting-websocket.min.js"></script>
    <script>
        let pid, energy = 4.5, ws;

        async function join() {
            const name = document.getElementById('name').value.trim();
            if (!name) return alert('กรอกชื่อด้วยนะ!');
            const res = await fetch('/join', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
            const data = await res.json();
            pid = data.player_id;
            ws = new ReconnectingWebSocket(`wss://${location.host}/ws/player/${pid}`);
            document.getElementById('game').style.display = 'block';
            joinQueue();

            ws.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                document.getElementById('status').textContent = msg.status === 'shot' ? `ยิงแล้ว! ผล: ${msg.result.toUpperCase()}` : 'กำลังรอคิว...';
                if (msg.status === 'shot') {
                    document.getElementById('sbtn').disabled = true;
                    alert(msg.result === 'hit' ? '🎉 ยิงถูก 4.9 eV! คุณชนะ!!!' : 'พลาดไปนิดเดียว ลุ้นต่อนะ!');
                }
            };
        }

        function adj(d) {
            energy = Math.round((Math.max(4.5, Math.min(5.5, energy + d))) * 10) / 10;
            document.getElementById('energy').textContent = energy;
            ws.send(JSON.stringify({action:'adjust', energy}));
        }

        function joinQueue() {
            ws.send(JSON.stringify({action:'join_queue'}));
            document.getElementById('qbtn').disabled = true;
            document.getElementById('sbtn').disabled = false;
            document.getElementById('status').textContent = 'อยู่ในคิวแล้ว รอถึงคิวคุณ!';
        }

        function shoot() {
            ws.send(JSON.stringify({action:'shoot'}));
            document.getElementById('sbtn').disabled = true;
            document.getElementById('status').textContent = 'ยิงไปแล้ว... รอผลบนจอใหญ่!';
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def main_screen(request: Request):
    join_url = str(request.base_url) + "player"
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(join_url)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = b64encode(buf.getvalue()).decode()
    html = MAIN_HTML.replace("{{QR_BASE64}}", qr_b64)
    return HTMLResponse(html)

@app.get("/player", response_class=HTMLResponse)
async def player_screen():
    return HTMLResponse(PLAYER_HTML)

@app.post("/join")
async def join(request: Request):
    data = await request.json()
    name = data["name"].strip()
    pid = str(uuid.uuid4())
    players[pid] = {"name": name, "energy": 4.5}
    return {"player_id": pid}

@app.websocket("/ws/main")
async def ws_main(ws: WebSocket):
    global main_ws
    await ws.accept()
    main_ws = ws
    try:
        while True:
            await asyncio.sleep(1)
            await broadcast_state()
    except WebSocketDisconnect:
        main_ws = None

@app.websocket("/ws/player/{pid}")
async def ws_player(ws: WebSocket, pid: str):
    await ws.accept()
    if pid not in players:
        await ws.close()
        return
    try:
        while True:
            msg = await ws.receive_json()
            if msg["action"] == "adjust":
                e = round(float(msg["energy"]), 1)
                if 4.5 <= e <= 5.5:
                    players[pid]["energy"] = e
            elif msg["action"] == "join_queue" and pid not in queue:
                queue.append(pid)
            elif msg["action"] == "shoot" and (barrage_mode or queue and queue[0] == pid):
                energy = players[pid]["energy"]
                hit = abs(energy - target) <= 0.01
                result = "hit" if hit else "miss"
                if hit:
                   
                    winner = players[pid]["name"]
                if not barrage_mode:
                    queue.pop(0)
                await broadcast_shot(pid, energy, result)
                await ws.send_json({"status": "shot", "result": result})
    except WebSocketDisconnect:
        if pid in queue: queue.remove(pid)
        players.pop(pid, None)

async def broadcast_state():
    if main_ws:
        await main_ws.send_json({
            "type": "state",
            "data": {"queue": [players[p]["name"] for p in queue], "winner": winner}
        })

async def broadcast_shot(pid, energy, result):
    if main_ws:
        await main_ws.send_json({
            "type": "shot",
            "data": {"player": players[pid]["name"], "energy": energy, "result": result}
        })
    if winner:
        await asyncio.sleep(8)
        
        winner = None
        queue.clear()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)