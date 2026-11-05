import os
import re
import random
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

MY_TAG = "iexclusiveoff-21"

# هيدرز متقدمة جداً لمحاكاة متصفح حقيقي وتجاوز حماية أمازون
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

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

def scrape_product_metadata(url: str):
    """استخراج العنوان والصورة الحقيقية باستخدام وسائط OpenGraph لتجنب الحظر"""
    try:
        clean_url = build_affiliate_url(url)
        response = requests.get(clean_url, headers=HEADERS, timeout=12)
        
        if response.status_code != 200:
            return {"title": "عروض حصرية مميزة من أمازون", "image": None, "link": clean_url}

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. البحث عن العنوان بطرق متعددة
        title = None
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title.get("content").strip()
        
        if not title:
            title_elem = soup.find(id="productTitle")
            if title_elem:
                title = title_elem.get_text().strip()
                
        if not title:
            title = "عرض خاص ومميز من أمازون"
            
        # تنظيف عنوان أمازون الطويل إذا لزم الأمر
        title = title.split("|")[0].strip()

        # 2. البحث عن الصورة الحقيقية بطرق متعددة (من ضمنها OpenGraph التي لا يحظرها أمازون)
        img_url = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_url = og_image.get("content").strip()
            
        if not img_url:
            img_elem = soup.find(id="landingImage")
            if img_elem:
                img_url = img_elem.get('data-old-hires') or img_elem.get('src')

        return {
            'title': title,
            'image': img_url,
            'link': clean_url
        }
    except Exception as e:
        print(f"Scraping error: {e}")
        return {
            'title': "عرض خاص ومميز من أمازون",
            'image': None,
            'link': build_affiliate_url(url)
        }

def extract_products_from_event_page(url: str):
    products = []
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        asins = list(set(re.findall(r'/dp/([A-Z0-9]{10})', response.text)))
        domain = urlparse(url).netloc or "www.amazon.eg"
        
        for asin in asins[:15]:
            prod_url = f"https://{domain}/dp/{asin}"
            prod_data = scrape_product_metadata(prod_url)
            products.append(prod_data)
    except Exception as e:
        print(f"Event page error: {e}")
    return products

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط منتج أو صفحة عروض، وسأقوم بإنشاء بوست احترافي بالصورة والعنوان ورابط الإحالة فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if "amazon." not in text.lower():
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    if not text.startswith('http'):
        text = 'https://' + text

    msg = await update.message.reply_text("⏳ جاري سحب بيانات المنتج والصورة وتجهيز البوست...")

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
        prod_data = scrape_product_metadata(text)
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
