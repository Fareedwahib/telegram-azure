import os, json, logging, asyncio
from datetime import datetime
from threading import Lock
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# ---------- CONFIG -------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env-var missing")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"          # Telegram will POST here
SAVE_FILE = "messages.txt"
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------- FLASK --------------------------------------------------
app = Flask(__name__)
messages = []
lock = Lock()

# ---------- TELEGRAM HANDLERS --------------------------------------
async def on_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or "<non-text>"
    log.info("📨 %s (%s): %s", user.full_name, user.id, text)

    item = {
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "from": user.full_name or "Unknown",
        "from_id": user.id,
        "text": text,
    }
    with lock:
        messages.append(item)
    # optional persistent log
    with open("messages_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{item['time']}] {item['from']} ({item['from_id']}): {item['text']}\n")

# ---------- FLASK ROUTES -------------------------------------------
@app.route("/")                       # human UI
def index():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Telegram → Notepad</title>
<style>
body{font-family:system-ui;background:#f8fafc;margin:0;padding:20px}
.container{max-width:900px;margin:auto;background:white;padding:25px;border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.08)}
h1{margin-top:0}
#msgs{height:400px;border:1px solid #ddd;padding:10px;overflow:auto;font-family:monospace}
button{margin-top:15px;padding:10px 18px;border:none;border-radius:6px;background:#3b82f6;color:white;cursor:pointer}
</style>
</head>
<body>
<div class="container">
<h1>📱 Telegram → 📝 Notepad</h1>
<div id="msgs">Loading…</div>
<button onclick="saveTxt()">💾 Save to disk</button>
<button onclick="clearAll()">🗑️ Clear</button>
</div>
<script>
async function load(){ const r=await fetch("/api/messages"); const d=await r.json(); const box=document.getElementById("msgs"); box.innerHTML=d.messages.map((m,i)=>`<div><b>${i+1}.</b> [${m.time}] <b>${m.from}</b>: ${m.text}</div>`).join("")||"<em>No messages yet</em>"; }
async function saveTxt(){ await fetch("/save",{method:"POST"}); alert("Saved to messages.txt"); }
async function clearAll(){ if(!confirm("Clear all?"))return; await fetch("/api/clear",{method:"POST"}); load(); }
setInterval(load,2000); load();
</script>
</body>
</html>
"""

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    """Telegram delivers updates here"""
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        asyncio.run(on_msg(update, None))
        return "OK", 200
    except Exception as e:
        log.exception("webhook error")
        return "ERR", 500

@app.route("/api/messages")
def api_messages():
    with lock:
        return jsonify(messages=list(messages))

@app.route("/api/clear", methods=["POST"])
def api_clear():
    global messages
    with lock:
        messages = []
    return "", 204

@app.route("/save", methods=["POST"])
def save():
    with lock:
        if not messages:
            return jsonify(message="Nothing to save"), 400
        lines = [f"[{m['time']}] {m['from']} ({m['from_id']}): {m['text']}\n" for m in messages]
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return jsonify(message=f"Saved {len(lines)} lines to {SAVE_FILE}")

@app.route("/api/set-webhook", methods=["POST"])
def set_webhook():
    """One-click webhook registration"""
    url = request.url_root.rstrip("/") + WEBHOOK_PATH
    ok = asyncio.run(bot.set_webhook(url=url))
    if ok:
        log.info("✅ webhook registered → %s", url)
        return jsonify(success=True, webhook_url=url)
    return jsonify(success=False, error="Telegram refused"), 400

# ---------- START-UP ------------------------------------------------
bot = Application.builder().token(BOT_TOKEN).build().bot  # lightweight bot instance

# Azure App Service starts gunicorn with `--bind=0.0.0.0:$PORT`
if __name__ == "__main__":          # local dev only
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)