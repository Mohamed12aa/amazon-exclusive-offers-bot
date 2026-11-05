import os
import re
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

MY_TAG = "iexclusiveoff-21"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
}

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

def scrape_single_product(url: str):
    """جلب تفاصيل المنتج الفردي بدقة (العنوان، الصورة، الرابط)"""
    try:
        clean_url = build_affiliate_url(url)
        res = requests.get(clean_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_elem = soup.find(id="productTitle")
        title = title_elem.get_text().strip() if title_elem else "منتج مميز من أمازون"
        
        img_url = None
        img_elem = soup.find(id="landingImage") or soup.find(id="imgBlkFront")
        if img_elem:
            img_url = img_elem.get('data-old-hires') or img_elem.get('src')
        
        return {
            'title': title,
            'image': img_url,
            'link': clean_url
        }
    except Exception as e:
        print(f"Error scraping product: {e}")
        return None

def extract_products_from_event_page(url: str):
    """استخراج جميع المنتجات من صفحة العروض مع جلب تفاصيلها الحقيقية"""
    products = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # البحث عن كل أكواد ASIN الفريدة في الصفحة بالكامل بدون تقييد بـ 10 فقط
        asins = list(set(re.findall(r'/dp/([A-Z0-9]{10})', res.text)))
        domain = urlparse(url).netloc or "www.amazon.eg"
        
        # نقوم بمعالجة المنتجات (نحدد حد أقصى أماناً 25 منتجاً حتى لا يتأخر البوت كثيراً في الرد)
        for asin in asins[:25]:
            prod_url = f"https://{domain}/dp/{asin}"
            # جلب تفاصيل كل منتج لضمان الحصول على اسمه الحقيقي
            prod_data = scrape_single_product(prod_url)
            if prod_data and prod_data['title'] != "منتج مميز من أمازون":
                products.append(prod_data)
            else:
                products.append({
                    'title': f"عرض مميز من أمازون",
                    'link': build_affiliate_url(prod_url),
                    'image': None
                })
    except Exception as e:
        print(f"Error scraping event page: {e}")
    return products

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط منتج فردي أو صفحة عروض، وسأقوم بتجهيز البوستات التسويقية فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if "amazon." not in text.lower():
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    if not text.startswith('http'):
        text = 'https://' + text

    msg = await update.message.reply_text("⏳ جاري قراءة الروابط وجلب تفاصيل المنتجات...")

    # التحقق مما إذا كانت صفحة عروض أو فعاليات
    if "/events/" in text or "promotions" in text or "ref_=nav_cs" in text:
        products = extract_products_from_event_page(text)
        await msg.delete()
        
        if not products:
            aff_link = build_affiliate_url(text)
            await update.message.reply_text(f"🔥 **رابط صفحة العروض:**\n\n{aff_link}")
            return
        
        await update.message.reply_text(اغرف={`✅ تم العثور على ${len(products)} منتج في الصفحة، جاري إرسالها:`})
        
        for prod in products:
            caption = f"🔥 **عرض خاص ومميز!**\n\n📌 {prod['title']}\n\n🛒 **اطلبه الآن من هنا:**\n`{prod['link']}`"
            
            if prod.get('image'):
                try:
                    await update.message.reply_photo(photo=prod['image'], caption=caption, parse_mode="Markdown")
                    continue
                except Exception:
                    pass
            await update.message.reply_text(caption, parse_mode="Markdown")
            
    else:
        prod_data = scrape_single_product(text)
        await msg.delete()
        
        if prod_data:
            caption = f"🔥 **عرض خاص ومميز!**\n\n📌 {prod_data['title']}\n\n🛒 **اطلبه الآن من هنا:**\n`{prod_data['link']}`"
            
            if prod_data['image']:
                try:
                    await update.message.reply_photo(photo=prod_data['image'], caption=caption, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(caption, parse_mode="Markdown")
            else:
                await update.message.reply_text(caption, parse_mode="Markdown")
        else:
            clean_link = build_affiliate_url(text)
            await update.message.reply_text(f"🔥 **إليك الرابط الترويجي:**\n\n{clean_link}")

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
