import os
import re
import random
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

MY_TAG = "iexclusiveoff-21"

PROMO_TEMPLATES = [
    "🔥 **لقطة اليوم من أمازون!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن بسعر مميز من هنا:**\n{link}",
    "⚡ **عرض حصري لفترة محدودة!**\n\n📌 **{title}**\n\n🛒 **رابط الشراء المباشر:**\n{link}",
    "💎 **فرصة لا تعوض، الحق العرض!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن:**\n{link}",
    "🚀 **من الأفضل مبيعاً والأعلي تقييماً!**\n\n📌 **{title}**\n\n🛒 **رابط الطلب والتفاصيل:**\n{link}"
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

def fetch_product_info(url: str):
    """استخدام خدمة معاينة الروابط الموثوقة لجلب العنوان والصورة الحقيقية دون حظر"""
    clean_url = build_affiliate_url(url)
    try:
        # استخدام خدمة مجانية آمنة لجلب بيانات الرابط (OpenGraph)
        api_url = f"https://api.microlink.io?url={requests.utils.quote(clean_url)}"
        response = requests.get(api_url, timeout=10)
        data = response.json()
        
        if data.get("status") == "success":
            item = data.get("data", {})
            title = item.get("title") or "عرض حصري مميز من أمازون"
            # تنظيف العنوان
            title = title.split("|")[0].strip()
            
            image_info = item.get("image")
            image_url = image_info.get("url") if image_info else None
            
            return {
                "title": title,
                "image": image_url,
                "link": clean_url
            }
    except Exception as e:
        print(f"API Error: {e}")
        
    return {
        "title": "عرض حصري ومميز من أمازون",
        "image": None,
        "link": clean_url
    }

def extract_products_from_event_page(url: str):
    products = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, timeout=15)
        asins = list(set(re.findall(r'/dp/([A-Z0-9]{10})', response.text)))
        domain = urlparse(url).netloc or "www.amazon.eg"
        
        for asin in asins[:12]:
            prod_url = f"https://{domain}/dp/{asin}"
            prod_data = fetch_product_info(prod_url)
            products.append(prod_data)
    except Exception as e:
        print(f"Event page error: {e}")
    return products

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط منتج أو صفحة عروض، وسأقوم بإنشاء البوست التسويقي بالصورة والعنوان فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if "amazon." not in text.lower():
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    if not text.startswith('http'):
        text = 'https://' + text

    msg = await update.message.reply_text("⏳ جاري سحب تفاصيل المنتج والصورة بدقة...")

    if "/events/" in text or "promotions" in text or "ref_=nav_cs" in text:
        products = extract_products_from_event_page(text)
        await msg.delete()
        
        if not products:
            aff_link = build_affiliate_url(text)
            await update.message.reply_text(f"🔥 **رابط صفحة العروض:**\n\n{aff_link}")
            return
        
        await update.message.reply_text(f"✅ تم العثور على {len(products)} منتج، إليك البوستات:")
        
        for prod in products:
            template = random.choice(PROMO_TEMPLATES)
            caption = template.format(title=prod['title'], link=prod['link'])
            
            if prod.get('image'):
                try:
                    await update.message.reply_photo(photo=prod['image'], caption=caption, parse_mode="Markdown")
                    continue
                except Exception:
                    pass
            await update.message.reply_text(caption, parse_mode="Markdown")
            
    else:
        prod_data = fetch_product_info(text)
        await msg.delete()
        
        template = random.choice(PROMO_TEMPLATES)
        caption = template.format(title=prod_data['title'], link=prod_data['link'])
        
        if prod_data.get('image'):
            try:
                await update.message.reply_photo(photo=prod_data['image'], caption=caption, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(caption, parse_mode="Markdown")
        else:
            await update.message.reply_text(caption, parse_mode="Markdown")

if __name__ == '__main__':
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN environment variable is missing.")
        exit(1)
    
    t = threading.Thread(target=run_web_server)
    t.daemon = True
    t.start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running...")
    app.run_polling()
