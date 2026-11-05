import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

MY_TAG = "iexclusiveoff-21"

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي أي رابط أمازون وسأقوم بتنظيفه وإضافة كود الإحالة الخاص بك فوراً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "amazon." in text.lower():
        try:
            if not text.startswith('http'):
                text = 'https://' + text
            
            if "dp/" in text or "gp/product/" in text:
                asin_match = text.split("/dp/")[1].split("/")[0] if "/dp/" in text else text.split("/gp/product/")[1].split("/")[0]
                asin = asin_match[:10]
                domain = text.split("/")[2]
                clean_link = f"https://{domain}/dp/{asin}?tag={MY_TAG}"
            else:
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                parsed_url = urlparse(text)
                query_params = parse_qs(parsed_url.query)
                query_params['tag'] = [MY_TAG]
                if 'ascsubtag' in query_params: del query_params['ascsubtag']
                
                new_query = urlencode(query_params, doseq=True)
                parsed_url = parsed_url._replace(query=new_query)
                clean_link = urlunparse(parsed_url)

            response_text = f"🔥 **إليك الرابط الترويجي الجاهز:**\n\n`{clean_link}`\n\n🏷 تم دمج كود التتبع: `{MY_TAG}`"
            await update.message.reply_text(response_text, parse_mode="Markdown")
            
        except Exception as e:
            await update.message.reply_text("عذراً، لم أستطع معالجة هذا الرابط، تأكد أنه رابط أمازون صحيح.")
    else:
        await update.message.reply_text("من فضلك أرسل رابط أمازون صالح لتوليد رابط الإحالة.")

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
