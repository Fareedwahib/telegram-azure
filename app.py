
from flask import Flask, render_template_string, jsonify
import os
import threading
import subprocess
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from threading import Lock
import asyncio
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not found in .env file!")
    exit(1)

logger.info(f"Bot token loaded: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")

SAVE_FILENAME = 'messages.txt'
app = Flask(__name__)

# Thread-safe message storage
messages = []
lock = Lock()

# Global variable to store bot info
bot_info = {}

HTML_PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Telegram -> Notepad</title>
<style>
body { font-family: system-ui, -apple-system, sans-serif; background:#f8fafc; margin:0; padding:20px }
.container { max-width:1000px;margin:0 auto;background:white;padding:30px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
h1{margin-top:0;color:#1e293b}
.status{padding:15px;margin:15px 0;border-radius:8px;font-weight:500}
.status.success{background:#dcfce7;color:#166534;border:1px solid #bbf7d0}
.status.error{background:#fee2e2;color:#dc2626;border:1px solid #fecaca}
.status.info{background:#dbeafe;color:#1e40af;border:1px solid #bfdbfe}
#msgs{height:450px;overflow:auto;border:2px solid #e5e7eb;padding:15px;border-radius:8px;background:#fefefe;font-family:monospace}
.msg{padding:10px;border-bottom:1px solid #f1f5f9;margin-bottom:8px}
.msg:last-child{border-bottom:none}
.meta{font-size:12px;color:#64748b;margin-bottom:4px}
.text{color:#1e293b;line-height:1.4}
.controls{margin-top:20px;display:flex;gap:12px;flex-wrap:wrap}
button{background:#3b82f6;color:white;border:none;padding:12px 20px;border-radius:8px;cursor:pointer;font-weight:500}
button:hover{background:#2563eb}
button.secondary{background:#6b7280}
button.secondary:hover{background:#4b5563}
.empty{color:#64748b;font-style:italic;text-align:center;padding:40px}
</style>
</head>
<body>
<div class="container">
<h1>📱 Telegram → 📝 Notepad</h1>
<div id="status" class="status info">🔄 Checking bot status...</div>
<div id="bot-info" style="display:none" class="status info"></div>
<div id="msgs"></div>
<div class="controls">
<button onclick="save()">💾 Export</button>
<button class="secondary" onclick="clearServer()">🗑️ Clear</button>
<button class="secondary" onclick="refreshStatus()">🔄 Refresh </button>
</div>
</div>

<script>
let messageCount = 0;

async function fetchMsgs(){
  try {
    const res = await fetch('/api/messages');
    const data = await res.json();
    const container = document.getElementById('msgs');
    
    if (data.messages.length === 0) {
      container.innerHTML = '<div class="empty">No messages yet<br><br>📱 Go to Telegram and:<br>1. Find your bot<br>2. Click START<br>3. Send a message</div>';
    } else {
      if (data.messages.length !== messageCount) {
        messageCount = data.messages.length;
        console.log(`📨 ${messageCount} messages loaded`);
      }
      
      container.innerHTML = data.messages.map((m, i) => 
        `<div class="msg">
          <div class="meta">#${i+1} • ${m.time} • <strong>${m.from}</strong> (ID: ${m.from_id})</div>
          <div class="text">${m.text}</div>
        </div>`
      ).join('');
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) {
    console.error('❌ Error fetching messages:', e);
  }
}

async function refreshStatus(){
  const statusEl = document.getElementById('status');
  const botInfoEl = document.getElementById('bot-info');
  
  statusEl.innerHTML = '🔄 Checking...';
  statusEl.className = 'status info';
  
  try {
    const res = await fetch('/api/bot-status');
    const data = await res.json();
    
    if (data.connected) {
      statusEl.innerHTML = '✅ Bot is running and listening for messages';
      statusEl.className = 'status success';
      
      botInfoEl.innerHTML = `🤖 Bot: <strong>@${data.username}</strong> (${data.first_name}) • Messages: ${data.message_count}`;
      botInfoEl.style.display = 'block';
      botInfoEl.className = 'status info';
    } else {
      statusEl.innerHTML = `❌ Bot error: ${data.error}`;
      statusEl.className = 'status error';
      botInfoEl.style.display = 'none';
    }
  } catch (e) {
    statusEl.innerHTML = '❌ Cannot connect to server';
    statusEl.className = 'status error';
  }
}

async function save(){
  try {
    const res = await fetch('/save', {method:'POST'});
    const data = await res.json();
    alert(data.message);
  } catch (e) {
    alert('Error saving: ' + e.message);
  }
}

async function clearServer(){
  if(!confirm('Clear all messages? This cannot be undone.')) return;
  try {
    await fetch('/api/clear', {method:'POST'});
    messageCount = 0;
    await fetchMsgs();
    await refreshStatus();
  } catch (e) {
    alert('Error clearing: ' + e.message);
  }
}

// Auto-refresh every 2 seconds
setInterval(() => {
  fetchMsgs();
}, 2000);

// Initial load
refreshStatus();
fetchMsgs();
</script>
</body>
</html>'''

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/messages')
def api_messages():
    with lock:
        return jsonify({'messages': list(messages)})

@app.route('/api/bot-status')
def api_bot_status():
    """Check bot status"""
    try:
        with lock:
            msg_count = len(messages)
        
        if bot_info:
            return jsonify({
                'connected': True,
                'username': bot_info.get('username', 'Unknown'),
                'first_name': bot_info.get('first_name', 'Unknown'),
                'message_count': msg_count
            })
        else:
            return jsonify({
                'connected': False,
                'error': 'Bot not initialized yet'
            })
    except Exception as e:
        return jsonify({
            'connected': False,
            'error': str(e)
        })

@app.route('/api/clear', methods=['POST'])
def api_clear():
    with lock:
        messages.clear()
    logger.info("Messages cleared via web interface")
    return ('', 204)

@app.route('/save', methods=['POST'])
def save_and_open():
    with lock:
        if not messages:
            return jsonify({'message': 'No messages to save!'}), 400
            
        lines = [f"[{m['time']}] {m['from']} (ID: {m['from_id']}): {m['text']}\n" 
                for m in messages]

    try:
        with open(SAVE_FILENAME, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        logger.info(f"Saved {len(lines)} messages to {SAVE_FILENAME}")

        if os.name == 'nt':  # Windows
            subprocess.Popen(['notepad.exe', SAVE_FILENAME])
            return jsonify({'message': f'✅ Saved {len(lines)} messages and opened in Notepad'})
        else:
            return jsonify({'message': f'✅ Saved {len(lines)} messages to {SAVE_FILENAME}'})
    except Exception as e:
        logger.error(f"Failed to save: {e}")
        return jsonify({'message': f'❌ Error saving: {e}'}), 500

# Telegram message handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Telegram messages"""
    try:
        user = update.effective_user
        message_text = update.message.text if update.message and update.message.text else '<non-text>'
        
        logger.info(f"📨 Message from {user.full_name} (@{user.username}): {message_text}")
        
        item = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'from': user.full_name or 'Unknown',
            'from_id': user.id,
            'text': message_text
        }
        
        with lock:
            messages.append(item)
            total_messages = len(messages)
        
        logger.info(f"📝 Added to queue. Total messages: {total_messages}")
        
        # Save to persistent log
        try:
            with open('messages_log.txt', 'a', encoding='utf-8') as f:
                f.write(f"[{item['time']}] {item['from']} (ID: {item['from_id']}): {item['text']}\n")
        except Exception as e:
            logger.error(f"Failed to write log: {e}")
            
    except Exception as e:
        logger.error(f"Error handling message: {e}")

def run_telegram_bot():
    """Run the Telegram bot in a separate thread"""
    async def start_bot():
        try:
            logger.info("🚀 Starting Telegram bot...")
            
            # Create application
            app_bot = Application.builder().token(BOT_TOKEN).build()
            
            # Add message handler for ALL message types
            app_bot.add_handler(MessageHandler(filters.ALL, handle_message))
            
            # Initialize and start
            await app_bot.initialize()
            await app_bot.start()
            
            # Get bot info
            bot = await app_bot.bot.get_me()
            global bot_info
            bot_info = {
                'username': bot.username,
                'first_name': bot.first_name,
                'id': bot.id
            }
            
            logger.info(f"✅ Bot connected: @{bot.username} ({bot.first_name})")
            logger.info("📱 Bot is now listening for messages...")
            logger.info(f"💡 Go to https://t.me/{bot.username} to send messages")
            
            # Start polling
            await app_bot.updater.start_polling(drop_pending_updates=True)
            
            # Keep running
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("👋 Shutting down bot...")
            finally:
                await app_bot.updater.stop()
                await app_bot.stop()
                await app_bot.shutdown()
                
        except Exception as e:
            logger.error(f"❌ Bot failed to start: {e}")

    # Run the async function
    asyncio.run(start_bot())

if __name__ == '__main__':
    logger.info("🎬 Starting application...")
    
    # Start Telegram bot in background thread
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask web server
    logger.info("🌐 Starting web server at http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)