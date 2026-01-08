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
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Game state
players = {}  # pid -> {"name": str, "energy": float, "ready": bool}
player_connections = {}  # pid -> WebSocket
ready_count = 0
winners = []  # list of winner names (รองรับหลายคน)
main_connections = set()
game_status = "waiting"  # "waiting" หรือ "playing"
target = 4.9
MAX_PLAYERS = 10  # จำนวนผู้เล่นสูงสุด (ปรับได้)

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
   #control-btn {
    padding: 20px 40px;
    font-size: 2em;
    background: #0f0; /* เขียวสำหรับ "เริ่มเกมส์" (lobby) */
    color: #000;
    border: none;
    border-radius: 20px;
    cursor: pointer;
    margin: 30px;
    min-width: 300px;
    box-shadow: 0 0 20px #0f0;
    transition: all 0.3s;
}

#control-btn:hover {
    background: #0d0;
    box-shadow: 0 0 30px #0ff;
}

#control-btn:disabled {
    background: #555;
    color: #aaa;
    cursor: not-allowed;
    box-shadow: none;
}

/* เมื่อเป็น "active" (เริ่มรอบยิงใหม่) เปลี่ยนเป็นแดง */
#control-btn.active-phase {
    background: #f00; /* แดงสำหรับ "เริ่มรอบยิงใหม่" */
    color: #fff;
    box-shadow: 0 0 20px #f00;
}

#control-btn.active-phase:hover {
    background: #d00;
    box-shadow: 0 0 30px #ff0;
}
#warning {
    font-size: 2em;
    color: #ff0000;
    margin: 20px 0;
    min-height: 60px;
    font-weight: bold;
}
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
    
    <button id="control-btn" onclick="controlAction()">เริ่มเกมส์</button>
    
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

                const btn = document.getElementById('control-btn');
                btn.classList.remove('active-phase');
            if (data.game_phase === 'lobby') {
                btn.textContent = 'เริ่มเกมส์';
                btn.onclick = () => ws.send(JSON.stringify({action: 'start_game'}));
                btn.disabled = data.total_players === 0;
            } else if (data.game_phase === 'active') {
                btn.textContent = 'เริ่มรอบยิงใหม่';
                btn.onclick = () => ws.send(JSON.stringify({action: 'start_round'}));
                btn.disabled = false;
                btn.classList.add('active-phase');
            } else if (data.game_phase === 'ended') {
                btn.disabled = true;
            }
                
                document.getElementById('message').textContent = '';
                drawScene();
                
            } else if (msg.type === 'shot') {
                animateShot(msg.data.energy, msg.data.result, msg.data.player);
            } else if (msg.type === 'winners_announce') {
                showModal('ผู้ชนะรอบนี้!', msg.data.winners.join(', '));
            } else if (msg.type === 'start_failed') {
                showModal('ยังไม่สามารถเริ่มได้!', `ยังมี ${msg.data.missing} คนที่ยังไม่กดพร้อม`);
            } else if (msg.type === 'all_shots_done') {
            document.getElementById('message').textContent = 'รอบนี้จบแล้ว! ไม่มีผู้ชนะ รอรอบใหม่...';
            drawScene();  // clear animation
        } else if (msg.type === 'clear_display') {
                document.getElementById('message').textContent = '';
                document.getElementById('winner').textContent = '';
                drawScene();
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
    <link rel="preload" href="/static/videos/background1.mp4" as="video" type="video/mp4">

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
    
    <div id="countdown" style="display:none; font-size:2em; color:#f00;"></div>

    <div id="game" style="display:none;">
        <h2>ปรับพลังงานอิเล็กตรอน</h2>
        <div id="scale"><span>4.5 eV</span><span>5.5 eV</span></div>
        <div id="energy-display">4.5</div>
        <div id="warning"></div>
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
    function showWarning(message) {
    const warning = document.getElementById('warning');
    warning.textContent = message;
    setTimeout(() => {
        warning.textContent = '';
    }, 2000);  // หายไปอัตโนมัติหลัง 2 วินาที
}

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
                    // ผู้ชนะ → แสดง modal แล้ว redirect ไปหมุนกงล้อ
                    showModal('🎉 ยินดีด้วย! 🎉', 'คุณยิงถูกเป๊ะเลย!\\nไปสอยดาวรับรางวัลกัน!', () => {
                        location.href = '/wheel';
                    });
                } else {
                    if (msg.has_winner_in_round) {
                        // มีผู้ชนะในรอบนี้ (แต่ไม่ใช่คุณ) → แจ้งแล้ว kick ออกจากห้อง
                        showModal('รอบนี้จบแล้ว!', 'มีผู้ชนะแล้ว รอรอบใหม่นะ\\nระบบจะพาคุณกลับหน้าเข้าร่วม', () => {
                            location.href = '/player';
                        });
                    } else {
                        // ไม่มีผู้ชนะ → แสดงพลาด แต่ไม่ redirect อยู่ต่อเล่นรอบถัดไป
                        showModal('พลาด!', `คุณยิง ${msg.energy} eV (พลาดไปนิดเดียว)\\nปรับค่าแล้วลุ้นรอบใหม่ได้เลย`);
                    }
                }
            } else if (msg.type === 'please_ready') {
                    showModal('โปรดกดพร้อม!', 'หัวห้องต้องการเริ่มเกม แต่คุณยังไม่ได้กดยืนยันพร้อม');
                } else if (msg.type === 'round_end') {
                    ready = false;
                    document.getElementById('ready-btn').textContent = 'ยืนยันพร้อมยิง!';
                    document.getElementById('status').textContent = 'ปรับพลังงานแล้วกดยืนยันเมื่อพร้อม';
                } else if (msg.type === 'game_started') {
            document.getElementById('status').textContent = 'เกมส์เริ่มแล้ว! ปรับพลังงานแล้วกดยืนยันพร้อม';
            document.getElementById('ready-btn').style.display = 'inline-block'; // แสดงปุ่มพร้อม
        } else if (msg.type === 'countdown_start') {
            document.getElementById('countdown').style.display = 'block';
            document.getElementById('countdown').textContent = `โปรดกดพร้อม! เหลือ ${msg.seconds} วินาที`;
        } else if (msg.type === 'countdown_update') {
            document.getElementById('countdown').textContent = `โปรดกดพร้อม! เหลือ ${msg.seconds} วินาที`;
        } else if (msg.type === 'kicked_not_ready') {
            showModal('ถูกเตะออก!', 'คุณไม่กดพร้อมภายในเวลา ระบบรีเซ็ตหน้า');
            setTimeout(() => location.href = '/player', 2000);
        }
        
       
            };

            document.getElementById('join-section').style.display = 'none';
            document.getElementById('game').style.display = 'block';
            document.getElementById('status').textContent = 'ปรับพลังงานแล้วกดยืนยันเมื่อพร้อม';
        }

        function adj(d) {
    const attempted = energy + d;
    const clamped = Math.max(4.5, Math.min(5.5, attempted));

    // ถ้าพยายามปรับเกินขอบเขต → แสดงเตือน
    if (attempted < 4.5) {
        showWarning('ไม่สามารถลดต่ำกว่า 4.5 eV ได้!');
    } else if (attempted > 5.5) {
        showWarning('ไม่สามารถเพิ่มสูงกว่า 5.5 eV ได้!');
    }

    energy = Math.round(clamped * 10) / 10;
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
        
         // ซ่อนปุ่มพร้อมตอนแรก
        document.getElementById('ready-btn').style.display = 'none';
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
    <link rel="preload" href="/static/videos/background1.mp4" as="video" type="video/mp4">

    <title>สอยดาวลุ้นรางวัล!</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: 'Arial', sans-serif;
            background: #111; /* ใส่สีพื้นหลังกันไว้กรณียังไม่โหลดวิดีโอ */
            color: #fff;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            min-height: 100vh;
            position: relative;
            z-index: 1;
            overflow-x: hidden; /* ป้องกันเลื่อนซ้ายขวาเกิน */
        }

        /* Video Background */
        .video-bg {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -2;
            overflow: hidden;
        }

        .video-bg video {
            width: 100%;
            height: 100%;
            object-fit: cover;
            filter: blur(12px);
            transform: scale(1.1);
        }

        .video-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.4); /* มืดขึ้นอีกนิดให้อ่านง่าย */
            z-index: -1;
        }

        .close-btn {
            position: absolute;
            top: 15px;
            right: 15px;
            font-size: 3em;
            color: #ff3366;
            text-shadow: 0 0 15px #ff3366;
            cursor: pointer;
            z-index: 10;
        }

        h1 {
            margin: 30px 0 10px;
            font-size: 3.5em;
            color: #ffff00;
            text-shadow: 0 0 20px #ffff00, 0 0 40px #ffff00;
            animation: glow 2s infinite alternate;
            text-align: center;
            line-height: 1.2;
            padding: 0 10px;
        }

        @keyframes glow {
            from { text-shadow: 0 0 20px #ffff00; }
            to { text-shadow: 0 0 40px #ffff00, 0 0 60px #ffaa00; }
        }

        .instruction {
            font-size: 1.8em;
            margin: 10px 20px 30px; /* เพิ่มระยะห่างด้านล่าง */
            text-shadow: 0 0 15px #ff00ff;
            text-align: center;
        }

        /* --- ส่วนที่แก้ไข Layout --- */
        #stars-container {
            display: flex; /* เปลี่ยนเป็น Flex เพื่อให้คุมง่ายขึ้นในกรณีดาวน้อย */
            flex-wrap: wrap; /* ให้ปัดตกบรรทัด */
            justify-content: center; /* จัดกึ่งกลางจอเสมอ */
            gap: 20px; /* ลดช่องว่างระหว่างดาวลง */
            padding: 20px;
            max-width: 1200px;
            width: 100%;
            box-sizing: border-box;
        }

        .star-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-bottom: 20px; /* ระยะห่างระหว่างแถว */
            width: 160px; /* กำหนดความกว้าง wrapper ให้แน่นอน */
        }
        /* ----------------------- */

        .string {
            width: 4px;
            height: 100px; /* ลดความยาวเชือกลงนิดหน่อยให้สมดุล */
            background: linear-gradient(to bottom, #ffffff, #aaaaaa);
            box-shadow: 0 0 10px #ffff00;
        }

        .star {
            width: 120px;
            height: 120px;
            background: linear-gradient(145deg, #ffff66, #ffaa00);
            clip-path: polygon(50% 0%, 61% 35%, 98% 35%, 68% 57%, 79% 91%, 50% 70%, 21% 91%, 32% 57%, 2% 35%, 39% 35%);
            cursor: pointer;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
            box-shadow: 0 0 30px #ffff00, 0 0 50px #ff6600;
            animation: pulse 3s infinite ease-in-out;
            position: relative; /* เพื่อให้ z-index ทำงาน */
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }

        .star:hover {
            transform: scale(1.15);
            box-shadow: 0 0 50px #ffff00, 0 0 80px #ff6600;
        }

        .star.soied {
            animation: drop 1.5s forwards ease-in; /* เร่งความเร็วตกนิดหน่อย */
            z-index: 100;
            pointer-events: none;
        }

        @keyframes drop {
            0% { transform: translateY(0) rotate(0deg); opacity: 1; }
            100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
        }

        /* Responsive สำหรับมือถือ */
        @media (max-width: 768px) {
            h1 { font-size: 2.2em; margin-top: 20px; }
            .instruction { font-size: 1.4em; margin-bottom: 20px; }
            #stars-container { gap: 10px; padding: 10px; }
            .star-wrapper { width: 110px; margin-bottom: 10px; }
            .string { height: 60px; width: 2px; }
            .star { width: 90px; height: 90px; }
        }

        @media (max-width: 480px) {
            .close-btn { font-size: 2em; top: 10px; right: 10px; }
            /* จัดให้มือถือเล็กๆ เห็น 2-3 ดวงต่อแถวได้สวยขึ้น */
            .star-wrapper { width: 30%; } 
            .star { width: 70px; height: 70px; }
        }
    </style>
</head>
<body>

    <div class="video-bg">
        <video autoplay loop muted playsinline>

            
            <video autoplay loop muted playsinline preload="auto">
    <source src="/static/videos/background1.mp4" type="video/mp4">
</video>


            </video>
    </div>
    <div class="video-overlay"></div>

    <div class="close-btn" onclick="location.href='/player'">✖</div>

    <h1>สอยดาวลุ้นรางวัล 🎆🎪</h1>
    <p class="instruction">คลิกสอยดาว 1 ดวง เพื่อลุ้นรางวัล!</p>

    <div id="stars-container">
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
        <div class="star-wrapper"><div class="string"></div><div class="star" onclick="soi(this)"></div></div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>

    <script>
        let selected = false;

        function soi(star) {
            if (selected) return;
            selected = true;

            document.querySelector('.instruction').textContent = 'กำลังสอยดาว... 🎯';

            const prizes = [
                'ลูกอม 1 เม็ด',
                'ลูกอม 2 เม็ด',
                'ลูกอม 3 เม็ด',
                'ลูกอม 4 เม็ด',
                'ลูกอม 5 เม็ด',
                'รางวัลปริศนา!'
            ];
            const prize = prizes[Math.floor(Math.random() * prizes.length)];

            // ทำให้ดาวอื่นๆ มัว
            document.querySelectorAll('.star').forEach(s => {
                if (s !== star) {
                    s.style.opacity = '0.3';
                    s.style.pointerEvents = 'none';
                    s.style.filter = 'grayscale(100%)'; // เพิ่มสีเทาให้ดูชัดว่าจบแล้ว
                }
            });

            // เริ่มแอนิเมชันตก
            star.classList.add('soied');

            // --- แก้ไขตรงนี้: เรียกใช้ฟังก์ชันให้ถูกชื่อ ---
            // ของเดิม: canvasConfetti(...) -> ผิด
            // ของใหม่: confetti(...) -> ถูก
            try {
                confetti({
                    particleCount: 200,
                    spread: 120,
                    origin: { y: 0.6 },
                    zIndex: 2000 // ให้เอฟเฟกต์อยู่เหนือทุกอย่าง
                });
            } catch (e) {
                console.error("Confetti error:", e);
            }

            // แสดงผลรางวัล
            setTimeout(() => {
                let isMystery = prize.includes('ปริศนา');
                let extraEmoji = isMystery ? '🎁😲' : '🍬🍬';
                let titleText = isMystery ? 'โอ้โห! รางวัลปริศนา!' : 'เย่! ได้รางวัล!';
                
                Swal.fire({
                    title: titleText,
                    html: `<strong style="font-size: 3em; color: #ffff00; text-shadow: 0 0 20px #ff00ff; display:block; margin: 10px 0;">${prize}</strong><span style="font-size: 2.5em;">${extraEmoji}</span>`,
                    icon: isMystery ? 'question' : 'success',
                    confirmButtonText: 'รับรางวัล',
                    background: 'rgba(20, 20, 50, 0.95)', // พื้นหลังโปร่งแสงนิดๆ
                    color: '#fff',
                    allowOutsideClick: false,
                    backdrop: `
                        rgba(0,0,123,0.4)
                        url("https://sweetalert2.github.io/images/nyan-cat.gif")
                        left top
                        no-repeat
                    `
                }).then(() => {
                    document.querySelector('.instruction').innerHTML = `คุณสอยได้ <strong style="color:#ffff00;">${prize}</strong> 🎉`;
                });
            }, 1200); // ลดเวลาลงนิดหน่อยให้ไม่ต้องรอนานเกินไป
        }
    </script>
</body>
</html>
"""

game_phase = "lobby"  # "lobby" (รอเริ่มเกมส์), "active" (เล่นหลายรอบ), "ended" (มีผู้ชนะ)

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
    if game_phase in ["active", "ended"]:
        return JSONResponse({"error": "เกมกำลังเล่นอยู่ โปรดรอรอบใหม่"})
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
    global game_status, game_phase
    await ws.accept()
    main_connections.add(ws)
    await broadcast_state()  # ส่ง state ปัจจุบันให้จอที่ connect ใหม่ทันที
    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")
            if action == "start_game" and game_phase == "lobby" and len(players) > 0:
                game_phase = "active"
                # แจ้งผู้เล่นทุกคนว่าเกมเริ่ม + แสดงปุ่มพร้อม
                for pws in player_connections.values():
                    try:
                        await pws.send_json({"type": "game_started"})
                    except:
                        pass
                await broadcast_state()
            elif action == "start_round" and game_phase == "active":
                if ready_count < len(players):
                    # เริ่ม countdown 10 วินาที + เตะคนไม่พร้อม
                    asyncio.create_task(start_round_with_timeout())
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
    global game_phase, game_status, winners, ready_count
    if len(players) == 0 and game_phase != "lobby":
        game_phase = "lobby"
        game_status = "waiting"
        winners = []
        ready_count = 0
        
    player_list = [{"name": v["name"], "energy": v["energy"], "ready": v["ready"]} for v in players.values()]
    data = {
        "type": "state",
        "data": {
            "players": player_list,
            "ready_count": ready_count,
            "total_players": len(players),
            "game_status": game_status,
            "game_phase": game_phase,
            "winners": winners
        }
    }
    
    for conn in main_connections.copy():
        try:
            await conn.send_json(data)
        except:
            main_connections.remove(conn)

async def start_round_with_timeout():
    # แจ้ง countdown ให้ผู้เล่นที่ไม่พร้อม
    not_ready_pids = [pid for pid, p in players.items() if not p["ready"]]
    for pid in not_ready_pids:
        if pid in player_connections:
            try:
                await player_connections[pid].send_json({"type": "countdown_start", "seconds": 10})
            except:
                pass
    
    # นับถอยหลัง 10 วินาที
    for remaining in range(10, 0, -1):
        await asyncio.sleep(1)
        # อัปเดต countdown
        for pid in not_ready_pids[:]:  # copy เพื่อ remove ระหว่าง loop
            if pid in players and not players[pid]["ready"] and pid in player_connections:
                try:
                    await player_connections[pid].send_json({"type": "countdown_update", "seconds": remaining})
                except:
                    not_ready_pids.remove(pid)
    
    # ครบเวลา → เตะคนที่ยังไม่พร้อม
    still_not_ready = [pid for pid in not_ready_pids if pid in players and not players[pid]["ready"]]
    for pid in still_not_ready:
        if pid in player_connections:
            try:
                await player_connections[pid].send_json({"type": "kicked_not_ready"})
                await player_connections[pid].close()
            except:
                pass
        players.pop(pid, None)
        player_connections.pop(pid, None)
        
    await broadcast_state()
    
    # ถ้ายังมีผู้เล่นเหลือ → เริ่มรอบ
    if len(players) > 0 and ready_count == len(players):
        game_status = "playing"
        await broadcast_state()
        await process_round()
        
async def process_round():
    global winners, ready_count, game_status, game_phase  # ย้ายมาบนสุด
    
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
    
    has_winner = len(winners) > 0
    
    if has_winner:
        game_phase = "ended"  # ลบ global ที่นี่
        
        await asyncio.sleep(10)
        winners = []
        for conn in main_connections.copy():
            try:
                await conn.send_json({"type": "clear_display"})
            except:
                main_connections.remove(conn)
        await broadcast_state()
    
    if not has_winner:
        for conn in main_connections.copy():
            try:
                await conn.send_json({"type": "all_shots_done"})
            except:
                main_connections.remove(conn)
    
    # ส่งผลให้ผู้เล่นแต่ละคน
    for pid, name, energy, is_winner in results:
        if pid in player_connections:
            try:
                await player_connections[pid].send_json({
                    "type": "result",
                    "is_winner": is_winner,
                    "energy": energy,
                    "has_winner_in_round": has_winner  # flag ใหม่เพื่อให้ JS รู้ว่ารอบนี้มีผู้ชนะไหม
                })
            except:
                pass
    
    # ส่ง round_end เสมอ เพื่อรีเซ็ตปุ่มพร้อม
    for pws in player_connections.values():
        try:
            await pws.send_json({"type": "round_end"})
        except:
            pass
    
    # รีเซ็ต ready เสมอ (เล่นรอบใหม่ได้ทันทีถ้ายังไม่มีผู้ชนะ)
    ready_count = 0
    for p in players.values():
        p["ready"] = False
    
    game_status = "waiting"
    await broadcast_state()
    
    # ถ้ามีผู้ชนะ → รอแสดงผลสักพัก แล้ว clear winners (ไม่ clear players เพราะ redirect จะ disconnect เอง)
    if has_winner:
        await asyncio.sleep(3)
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