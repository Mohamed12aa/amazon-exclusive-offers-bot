import os
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# تهيئة عميل Gemini الجديد
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
TEXT_MODEL = os.getenv("TEXT_MODEL", "gemini-2.5-flash")

def get_amazon_product_details(asin_or_url):
    """دالة لسحب عنوان وصورة المنتج من أمازون بحماية Headers لتجنب الحظر"""
    if "http" in asin_or_url:
        url = asin_or_url
    else:
        url = f"https://www.amazon.eg/dp/{asin_or_url}"
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # استخراج العنوان
        title_elem = soup.find(id='productTitle')
        title = title_elem.get_text(strip=True) if title_elem else "منتج مميز من أمازون"
        
        # استخراج رابط الصورة الأساسية
        img_elem = soup.find(id='landingImage') or soup.find('img', {'class': 'a-dynamic-image'})
        image_url = img_elem.get('src') if img_elem else None
        
        return title, image_url
    except Exception as e:
        print(f"Error scraping product: {e}")
        return None, None

def generate_ad_content(product_title, affiliate_link):
    """توليد طرق إعلانية متغيرة ومبتكرة باستخدام Gemini"""
    prompt = f"""
    اكتب منشور إعلاني تسويقي جذاب ومتحول لقناة تليجرام تسويق بالعمولة لمنتج أمازون التالي:
    اسم المنتج: {product_title}
    رابط الشراء: {affiliate_link}
    
    اجعل الإعلان يحتوي على:
    - عنوان خطير وجذاب يشد الانتباه.
    - مميزات المنتج باختصار في نقاط مع إيموجي مناسبة.
    - دعوة قوية لاتخاذ إجراء (Call to Action) للشراء فوراً قبل نفاد الكمية.
    """
    
    try:
        response = client.models.generate_content(
            model=TEXT_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"تسوق الآن بأفضل سعر: {affiliate_link}"
