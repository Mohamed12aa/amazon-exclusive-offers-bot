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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
}

# قوالب تسويقية متنوعة ومتجددة باستمرار لتغيير أسلوب الإعلان
PROMO_TEMPLATES = [
    "🔥 **لقطة اليوم من أمازون!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن بسعر مميز من هنا:**\n`{link}`",
    "⚡ **عرض حصري لفترة محدودة!**\n\n📌 **{title}**\n\n🛒 **رابط الشراء المباشر:**\n`{link}`",
    "💎 **فرصة لا تعوض، الحق العرض!**\n\n📌 **{title}**\n\n🛒 **اطلبه الآن:**\n`{link}`",
    "🚀 **من الأفضل مبيعاً والأعلي تقييماً!**\n\n📌 **{title}**\n\n🛒 **رابط الطلب والتفاصيل:**\n`{link}`"
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

def scrape_single_product(url: str):
    """جلب تفاصيل المنتج بدقة تامة (العنوان والصورة والرابط)"""
    try:
        clean_url = build_affiliate_url(url)
        res = requests.get(clean_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # استخراج العنوان
        title_elem = soup.find(id="productTitle")
        title = title_elem.get_text().strip() if title_elem else "منتج مميز من أمازون"
        
        # استخراج الصورة بدقة من أمازون
        img_url = None
        img_elem = soup.find(id="landingImage") or soup.find(id="imgBlkFront")
        if img_elem:
            img_url = img_elem.get('data-old-hires') or img_elem.get('src')
        else:
            # طريقة بديلة للبحث عن الصورة إذا لم تكن في العناصر السابقة
            dynamic_img = soup.select_Fills if hasattr(soup, 'select_one') else None
            img_tag = soup.select_one("#landingImage")
            if img_tag:
                img_url = img_tag.get('src')
                
        return {
            'title': title,
            'image': img_url,
            'link': clean_url
        }
    except Exception as e:
        print(f"Error scraping product: {e}")
        return None

def extract_products_from_event_page(url: str):
    """استخراج المنتجات من صفحة العروض بدقة"""
    products = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        asins = list(set(re.findall(r'/dp/([A-Z0-9]{10})', res.text)))
        domain = urlparse(url).netloc or "www.amazon.eg"
        
        for asin in asins[:15]:
            prod_url = f"https://{domain}/dp/{asin}"
            prod_data = scrape_single_product(prod_url)
            if prod_data and prod_data['title'] != "منتج مميز من أمازون":
                products.append(prod_data)
    except Exception as e:
        print(f"Error scraping event page: {e}")
    return products

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط منتج أو صفحة عروض، وسأقوم بإنشاء البوستات التسويقية المتجددة فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if "amazon." not in text.lower():
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح.")
        return

    if not text.startswith('http'):
        text = 'https://' + text

    msg = await update.message.reply_text("⏳ جاري قراءة الرابط وسحب الصور وتجهيز البوست...")

    if "/events/" in text or "promotions" in text or "ref_=nav_cs" in text:
        products = extract_products_from_event_page(text)
        await msg.delete()
        
        if not products:
            aff_link = build_affiliate_url(text)
            await update.message.reply_text(f"🔥 **رابط صفحة العروض:**\n\n{aff_link}")
            return
        
        await update.message.reply_text(f"✅ تم العثور على {len(products)} منتج، إليك البوستات بتصميم متجدد:")
        
        for prod in products:
            # اختيار قالب عشوائي ليتغير الأسلوب والأسلوب الإعلاني باستمرار
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
        prod_data = scrape_single_product(text)
        await msg.delete()
        
        if prod_data:
            template = random.choice(PROMO_TEMPLATES)
            caption = template.format(title=prod_data['title'], link=prod_data['link'])
            
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
