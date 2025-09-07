from flask import Flask, render_template_string, jsonify, request, Response
import os
import json
from datetime import datetime
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from threading import Lock
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
    logger.error("❌ BOT_TOKEN not found in environment variables!")
    exit(1)

logger.info(f"Bot token loaded: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")

SAVE_FILENAME = 'messages.txt'
app = Flask(__name__)

# Thread-safe message storage
messages = []
lock = Lock()

# Global variables
bot_info = {}
telegram_app = None
initialization_complete = False
initialization_error = None

# Initialize Telegram Application (but don't start polling)
async def init_telegram_app():
    global telegram_app, bot_info, initialization_complete, initialization_error
    try:
        logger.info("🔄 Initializing Telegram bot...")
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(MessageHandler(filters.ALL, handle_message))
        
        # Initialize the application
        await telegram_app.initialize()
        
        # Get bot info
        bot = await telegram_app.bot.get_me()
        bot_info = {
            'username': bot.username,
            'first_name': bot.first_name,
            'id': bot.id
        }
        
        initialization_complete = True
        initialization_error = None
        logger.info(f"✅ Bot initialized: @{bot.username} ({bot.first_name})")
        return True
    except Exception as e:
        initialization_error = str(e)
        initialization_complete = True  # Mark as complete even if failed
        logger.error(f"❌ Failed to initialize bot: {e}")
        return False

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
.status.warning{background:#fef3c7;color:#92400e;border:1px solid #fde68a}
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
button.danger{background:#dc2626}
button.danger:hover{background:#b91c1c}
.empty{color:#64748b;font-style:italic;text-align:center;padding:40px}
.webhook-info{background:#f3f4f6;padding:15px;border-radius:8px;margin:15px 0;font-family:monospace;font-size:14px}
</style>
</head>
<body>
<div class="container">
<h1>📱 Telegram → 📝 Notepad</h1>
<div id="status" class="status info">🔄 Checking bot status...</div>
<div id="bot-info" style="display:none" class="status info"></div>
<div id="webhook-info" style="display:none" class="webhook-info"></div>
<div id="msgs"></div>
<div class="controls">
<button onclick="save()">💾 Export</button>
<button class="secondary" onclick="clearServer()">🗑️ Clear</button>
<button class="secondary" onclick="refreshStatus()">🔄 Refresh</button>
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
  const webhookInfoEl = document.getElementById('webhook-info');
  const webhookBtn = document.getElementById('webhook-btn');
  
  statusEl.innerHTML = '🔄 Checking...';
  statusEl.className = 'status info';
  
  try {
    const res = await fetch('/api/bot-status');
    
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    
    const data = await res.json();
    
    if (data.initializing) {
      statusEl.innerHTML = '⏳ Bot is initializing... Please wait.';
      statusEl.className = 'status warning';
      botInfoEl.style.display = 'none';
      webhookInfoEl.style.display = 'none';
      
      // Retry in 2 seconds if still initializing
      setTimeout(refreshStatus, 2000);
      return;
    }
    
    if (data.connected) {
      statusEl.innerHTML = '✅ Bot is running and listening for messages';
      statusEl.className = 'status success';
      
      botInfoEl.innerHTML = `🤖 Bot: <strong>@${data.username}</strong> (${data.first_name}) • Messages: ${data.message_count}`;
      botInfoEl.style.display = 'block';
      botInfoEl.className = 'status info';
      
      if (data.webhook_info) {
        webhookInfoEl.innerHTML = `🔗 Webhook: ${data.webhook_info.url || 'Not set'}<br>📊 Pending updates: ${data.webhook_info.pending_update_count || 0}`;
        webhookInfoEl.style.display = 'block';
      }
      
      if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
        if (webhookBtn) webhookBtn.style.display = 'inline-block';
      }
    } else {
      statusEl.innerHTML = `❌ Bot error: ${data.error}`;
      statusEl.className = 'status error';
      botInfoEl.style.display = 'none';
      webhookInfoEl.style.display = 'none';
    }
  } catch (e) {
    console.error('Status check error:', e);
    statusEl.innerHTML = '❌ Cannot connect to server: ' + e.message;
    statusEl.className = 'status error';
    
    // Retry in 5 seconds
    setTimeout(refreshStatus, 5000);
  }
}

async function setWebhook(){
  const webhookBtn = document.getElementById('webhook-btn');
  const originalText = webhookBtn.innerHTML;
  webhookBtn.innerHTML = '⏳ Setting...';
  webhookBtn.disabled = true;
  
  try {
    const res = await fetch('/api/set-webhook', {method:'POST'});
    const data = await res.json();
    
    if (data.success) {
      alert('✅ Webhook set successfully! Your bot should now work.');
      refreshStatus();
    } else {
      alert('❌ Failed to set webhook: ' + data.error);
    }
  } catch (e) {
    alert('❌ Error setting webhook: ' + e.message);
  } finally {
    webhookBtn.innerHTML = originalText;
    webhookBtn.disabled = false;
  }
}

async function save(){
  try {
    const res = await fetch('/save');
    
    if (res.ok) {
      // Create a blob from the response and download it
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = 'messages.txt';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      alert('✅ Messages downloaded successfully!');
    } else {
      const errorData = await res.json();
      alert('❌ ' + errorData.message);
    }
  } catch (e) {
    alert('❌ Error downloading: ' + e.message);
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

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhooks from Telegram"""
    try:
        if not telegram_app or not initialization_complete:
            logger.error("Telegram app not ready yet")
            return "Bot not ready", 503
            
        # Get the JSON data
        json_data = request.get_json()
        if not json_data:
            return "No JSON data", 400
        
        logger.info(f"📨 Received webhook: {json_data}")
        
        # Create Update object
        update = Update.de_json(json_data, telegram_app.bot)
        
        # Process the update
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(telegram_app.process_update(update))
        finally:
            loop.close()
        
        return "OK", 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return f"Error: {str(e)}", 500

@app.route('/api/messages')
def api_messages():
    with lock:
        return jsonify({'messages': list(messages)})

@app.route('/setup-webhook')
def setup_webhook():
    """Manual webhook setup page"""
    try:
        if not telegram_app or not initialization_complete:
            return "Bot not initialized yet", 503
        
        webhook_url = request.url_root.rstrip('/') + '/webhook'
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Set webhook
            result = loop.run_until_complete(telegram_app.bot.set_webhook(url=webhook_url))
            
            if result:
                return f"✅ Webhook set successfully to: {webhook_url}"
            else:
                return "❌ Failed to set webhook"
        finally:
            loop.close()
            
    except Exception as e:
        return f"❌ Error: {str(e)}"

@app.route('/api/bot-status')
def api_bot_status():
    """Check bot status"""
    try:
        # Check if initialization is still in progress
        if not initialization_complete:
            return jsonify({
                'initializing': True,
                'connected': False,
                'message': 'Bot is still initializing...'
            })
        
        # Check if initialization failed
        if initialization_error:
            return jsonify({
                'connected': False,
                'error': f'Initialization failed: {initialization_error}',
                'initializing': False
            })
        
        # Get message count
        with lock:
            msg_count = len(messages)
        
        if bot_info and telegram_app:
            # Get webhook info
            webhook_info = {}
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    webhook_data = loop.run_until_complete(telegram_app.bot.get_webhook_info())
                    webhook_info = {
                        'url': webhook_data.url,
                        'pending_update_count': webhook_data.pending_update_count
                    }
                except Exception as webhook_error:
                    logger.warning(f"Could not get webhook info: {webhook_error}")
                    webhook_info = {'url': 'Unable to fetch', 'pending_update_count': 0}
                finally:
                    loop.close()
            except Exception as e:
                logger.error(f"Error getting webhook info: {e}")
                webhook_info = {'url': 'Error fetching', 'pending_update_count': 0}
            
            return jsonify({
                'connected': True,
                'username': bot_info.get('username', 'Unknown'),
                'first_name': bot_info.get('first_name', 'Unknown'),
                'message_count': msg_count,
                'webhook_info': webhook_info,
                'initializing': False
            })
        else:
            return jsonify({
                'connected': False,
                'error': 'Bot not initialized properly',
                'initializing': False
            })
            
    except Exception as e:
        logger.error(f"Error in bot status: {e}")
        return jsonify({
            'connected': False,
            'error': f'Status check failed: {str(e)}',
            'initializing': False
        }), 500

@app.route('/api/set-webhook', methods=['POST'])
def api_set_webhook():
    """Set webhook URL"""
    try:
        if not telegram_app or not initialization_complete:
            return jsonify({'success': False, 'error': 'Bot not initialized yet'})
        
        # Get the current host
        webhook_url = request.url_root.rstrip('/') + '/webhook'
        logger.info(f"Setting webhook to: {webhook_url}")
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Remove existing webhook first
            loop.run_until_complete(telegram_app.bot.delete_webhook())
            # Set new webhook
            result = loop.run_until_complete(telegram_app.bot.set_webhook(url=webhook_url))
            
            if result:
                logger.info(f"✅ Webhook set successfully to {webhook_url}")
                return jsonify({'success': True, 'webhook_url': webhook_url})
            else:
                return jsonify({'success': False, 'error': 'Failed to set webhook'})
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Error setting webhook: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear', methods=['POST'])
def api_clear():
    with lock:
        messages.clear()
    logger.info("Messages cleared via web interface")
    return ('', 204)

@app.route('/save', methods=['GET'])
def save_and_download():
    with lock:
        if not messages:
            return jsonify({'message': 'No messages to save!'}), 400
            
        lines = [f"[{m['time']}] {m['from']} (ID: {m['from_id']}): {m['text']}\n" 
                for m in messages]

    try:
        # Create the file content
        file_content = ''.join(lines)
        
        logger.info(f"Downloading {len(lines)} messages as messages.txt")

        # Return the file as a download
        return Response(
            file_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': 'attachment; filename=messages.txt',
                'Content-Type': 'text/plain; charset=utf-8'
            }
        )
    except Exception as e:
        logger.error(f"Failed to create download: {e}")
        return jsonify({'message': f'❌ Error creating download: {e}'}), 500

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

# Initialize the Telegram app when the module loads
import asyncio

def initialize_bot_sync():
    """Initialize bot synchronously for better startup handling"""
    global initialization_complete, initialization_error
    
    logger.info("🚀 Starting bot initialization...")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        success = loop.run_until_complete(init_telegram_app())
        if success:
            logger.info("✅ Telegram bot initialized successfully")
        else:
            logger.error("❌ Failed to initialize Telegram bot")
    except Exception as e:
        logger.error(f"❌ Initialization error: {e}")
        initialization_error = str(e)
        initialization_complete = True
    finally:
        loop.close()

# Initialize on startup
initialize_bot_sync()

if __name__ == '__main__':
    logger.info("🎬 Starting Flask application...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)