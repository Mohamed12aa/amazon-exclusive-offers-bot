import os
import random
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

MY_TAG = "iexclusiveoff-21"

# 10 أساليب إعلانية مختلفة ومتجددة كلياً يتم اختيارها عشوائياً
PROMO_TEMPLATES = [
    "🔥 **لقطة اليوم من أمازون!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن بسعر مميز من هنا:**\n{link}",
    "⚡ **عرض حصري لفترة محدودة! لا تفوت الفرصة.**\n\n📌 **{title}**\n\n🛒 **رابط الشراء المباشر:**\n{link}",
    "💎 **صفقة ممتازة تستحق التجربة!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن من هنا:**\n{link}",
    "🚀 **المنتج الأكثر طلباً والأعلى تقييماً!**\n\n📌 **{title}**\n\n🛒 **رابط الطلب والتفاصيل:**\n{link}",
    "🎯 **اغتنم الفرصة ووفّر الآن!**\n\n📌 **{title}**\n\n🛒 **للتسوق والشراء:**\n{link}",
    "🌟 **عرض جديد ومميز أضيف حديثاً!**\n\n📌 **{title}**\n\n🛒 **اضغط هنا لطلبه:**\n{link}",
    "💡 **منتج ذكي وعملي لا غنى عنه!**\n\n📌 **{title}**\n\n🛒 **رابط العرض المباشر:**\n{link}",
    "👑 **اخترنا لك الأفضل اليوم!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن من أمازون:**\n{link}",
    "💥 **خصم قوي وتخفيض رائع!**\n\n📌 **{title}**\n\n🛒 **رابط الشراء:**\n{link}",
    "✨ **اجعل حياتك أسهل مع هذا المنتج الرائع!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن من هنا:**\n{link}"
]

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

def build_affiliate_url(url: str) -> str:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    query_params['tag'] = [MY_TAG]
    if 'ascsubtag' in query_params:
        del query_params['ascsubtag']
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))

def fetch_details_via_proxy(url: str):
    clean_url = build_affiliate_url(url)
    try:
        api_url = f"https://api.microlink.io?url={requests.utils.quote(clean_url)}"
        response = requests.get(api_url, timeout=12)
        data = response.json()
        
        if data.get("status") == "success":
            item = data.get("data", {})
            # جلب العنوان بالكامل بدون قص أو حذف
            title = item.get("title") or "عرض حصري مميز من أمازون"
            
            image_url = None
            if item.get("image"):
                image_url = item["image"].get("url")
            elif item.get("logo"):
                image_url = item["logo"].get("url")
                
            return {
                "title": title,
                "image": image_url,
                "link": clean_url
            }
    except Exception as e:
        print(f"Fetch Error: {e}")
        
    return {
        "title": "عرض خاص ومميز من أمازون",
        "image": None,
        "link": clean_url
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط أمازون، وسأقوم بإنشاء بوست تسويقي متجدد بالصورة والعنوان الكامل فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if "amazon." not in text.lower():
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    if not text.startswith('http'):
        text = 'https://' + text

    msg = await update.message.reply_text("⏳ جاري قراءة المنتج بالكامل وتجهيز البوست...")

    prod_data = fetch_details_via_proxy(text)
    await msg.delete()
    
    # اختيار قالب إعلاني عشوائي من الـ 10 طرق المختلفة
    template = random.choice(PROMO_TEMPLATES)
    caption = template.format(title=prod_data['title'], link=prod_data['link'])
    
    if prod_data.get('image'):
        try:
            await update.message.reply_photo(photo=prod_data['image'], caption=caption, parse_mode="Markdown")
            return
        except Exception as e:
            print(f"Photo send error: {e}")
            
    await update.message.reply_text(caption, parse_mode="Markdown")

if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN variable missing.")
        exit(1)
    
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running...")
    app.run_polling()
