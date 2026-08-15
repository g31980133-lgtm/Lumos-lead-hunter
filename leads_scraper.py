import time
import re
import os
import json
import phonenumbers
from urllib.parse import urlparse
from serpapi import GoogleSearch

SERPAPI_KEY = "499177367fb1a108b1deef404bba6bae8ee23d2525d6d8e90a5b0abe2fc05bdf"
CACHE_FILE = "leads_cache.json"

# كلمات ومصطلحات الحظر المباشر (تم حذف مصطلحات ويكيبيديا لتجنب الفلترة الخاطئة)
EXCLUDED_KEYWORDS = [
    "entertainment",
    "film",
    "films",
    "movie",
    "studio",
    "ministry",
    "government",
    "goverment"
]

# الامتدادات والنطاقات الممنوعة
EXCLUDED_EXTENSIONS = [".org", ".gov", ".edu", "wikipedia.org", "wikimedia.org"]

def load_cache():
    """تحميل النوتة (الكاش) لو موجودة"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache_data):
    """حفظ وحماية النوتة من الضياع"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def format_us_phone(phone_str):
    try:
        parsed = phonenumbers.parse(phone_str, "US")
        if phonenumbers.is_valid_number(parsed):
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
            clean_digits = re.sub(r'\D', '', formatted)
            if len(clean_digits) == 10:
                return f"{clean_digits[:3]}.{clean_digits[3:6]}.{clean_digits[6:]}"
            return formatted
    except Exception:
        pass
    return None

def get_clean_name(name):
    cities = ["san francisco", "austin", "denver", "bozeman", "cambridge", "san jose", "pleasanton", "block"]
    clean_name = name
    for city in cities:
        clean_name = re.sub(rf'\b{city}\b', '', clean_name, flags=re.IGNORECASE)
    return clean_name.strip()

def check_keyword_exclusion(text_to_check):
    """فحص مرن ومباشر يصطاد الكلمات الممنوعة مهما كانت حالتها"""
    if not text_to_check:
        return False, None
    
    text_lower = str(text_to_check).lower()
    for kw in EXCLUDED_KEYWORDS:
        kw_lower = kw.lower().strip()
        if kw_lower in text_lower:
            return True, kw
    return False, None

def is_official_domain_excluded(url):
    try:
        domain = urlparse(url).netloc.lower()
        for ext in EXCLUDED_EXTENSIONS:
            if domain.endswith(ext) or ext in domain:
                return True, ext
    except Exception:
        pass
    return False, None

def run_lead_hunter(companies_list, start_idx=1, end_idx=None, status_callback=None):
    cache = load_cache()
    final_leads = []
    
    total_len = len(companies_list)
    start_pos = max(0, start_idx - 1)
    end_pos = end_idx if end_idx and end_idx <= total_len else total_len
    
    target_list = companies_list[start_pos:end_pos]

    phone_pattern = r'(?:\+?1[-.\s]?)?\(?([2-9]\d{2}|8[0-9]{2})\)?[-.\s]?([2-9]\d{2})[-.\s]?(\d{4})'
    medium_domains = ["linkedin.com", "crunchbase.com", "bloomberg.com", "zoominfo.com", "dnb.com"]
    low_domains = ["yelp.com", "yellowpages.com", "facebook.com", "instagram.com", "twitter.com", "news", "podcast", "bbb.org"]

    for idx, raw_company in enumerate(target_list, start=start_pos + 1):
        company_raw_str = str(raw_company).strip()
        clean_company = get_clean_name(company_raw_str)
        cache_key = clean_company.lower()
        
        if status_callback:
            status_callback(idx - start_pos, len(target_list), company_raw_str)
            
        # 🟢 الخطوة 1: الفحص بالفلتر الأول على اسم الشركة مباشرةً
        is_excluded, matched_kw = check_keyword_exclusion(company_raw_str)
        if is_excluded:
            filtered_entry = {
                "Company Name": company_raw_str,
                "Verification Status": f"Filtered: {matched_kw}",
                "Primary US Phone": "N/A",
                "Secondary US Phone": "N/A",
                "Contact Person / Role": "Excluded Sector",
                "Source / Reference": "Name Filtered"
            }
            final_leads.append(filtered_entry)
            continue  # اطلع فوراً واستبعدها من غير ما تقرأ الكاش ولا تستهلك API

        # 🟢 الخطوة 2: الفحص في الكاش (بعد ما تأكدنا إن الاسم مش ممنوع)
        if cache_key in cache:
            cached_entry = cache[cache_key].copy()
            cached_entry["Company Name"] = company_raw_str
            final_leads.append(cached_entry)
            continue

        primary_phone = "Not Found"
        secondary_phone = "N/A"
        confidence = "Needs Review"
        source_url = "N/A"
        found_phones = []
        filter_reason = None
        
        params = {
            "q": f"{clean_company} corporate headquarters phone number contact",
            "location": "United States",
            "hl": "en",
            "gl": "us",
            "api_key": SERPAPI_KEY
        }
        
        try:
            search = GoogleSearch(params)
            results = search.get_dict()
            
            # فحص الـ Knowledge Graph
            if "knowledge_graph" in results:
                kg = results["knowledge_graph"]
                kg_website = kg.get("website", "")
                kg_text = f"{kg.get('title', '')} {kg.get('type', '')} {kg.get('description', '')}"
                
                if kg_website:
                    is_ext_ex, ext_kw = is_official_domain_excluded(kg_website)
                    if is_ext_ex:
                        filter_reason = ext_kw
                
                if not filter_reason:
                    is_ex, kw = check_keyword_exclusion(kg_text)
                    if is_ex:
                        filter_reason = kw

            # فحص نتائج البحث العادية
            if not filter_reason and "organic_results" in results:
                for idx_res, item in enumerate(results["organic_results"]):
                    link = item.get("link", "").lower()
                    title = item.get("title", "").lower()
                    snippet = item.get("snippet", "").lower()
                    
                    # فحص الكلمات المفتاحية في العنوان والوصف بدون الرابط لتجنب حظر ويكيبيديا
                    text_content = f"{title} {snippet}"

                    is_ex_snip, kw_snip = check_keyword_exclusion(text_content)
                    if is_ex_snip:
                        filter_reason = kw_snip
                        break

                    if idx_res == 0:
                        is_ext_ex, ext_kw = is_official_domain_excluded(link)
                        if is_ext_ex:
                            filter_reason = ext_kw
                            break

                    matches = re.finditer(phone_pattern, snippet)
                    for match in matches:
                        valid_p = format_us_phone(match.group(0))
                        if valid_p and valid_p not in found_phones:
                            found_phones.append(valid_p)
                            
                            if confidence == "Needs Review":
                                if any(l_domain in link for l_domain in low_domains):
                                    confidence = "Low Confidence"
                                elif any(m_domain in link for m_domain in medium_domains):
                                    confidence = "Medium Confidence"
                                else:
                                    confidence = "High Confidence"
                                source_url = item.get("link", "Google Search Result")

                    if len(found_phones) >= 2:
                        break

        except Exception:
            pass

        if filter_reason:
            lead_entry = {
                "Company Name": company_raw_str,
                "Verification Status": f"Filtered: {filter_reason}",
                "Primary US Phone": "N/A",
                "Secondary US Phone": "N/A",
                "Contact Person / Role": "Excluded Sector",
                "Source / Reference": "Filtered"
            }
        else:
            if len(found_phones) >= 1:
                primary_phone = found_phones[0]
                if confidence == "Needs Review":
                    confidence = "High Confidence"
                    
            if len(found_phones) >= 2:
                secondary_phone = found_phones[1]

            lead_entry = {
                "Company Name": company_raw_str,
                "Verification Status": confidence,
                "Primary US Phone": primary_phone,
                "Secondary US Phone": secondary_phone,
                "Contact Person / Role": "N/A",
                "Source / Reference": source_url
            }
        
        # حفظ النتيجة الموثوقة فقط في الكاش
        cache[cache_key] = lead_entry
        save_cache(cache)
        
        final_leads.append(lead_entry)
        time.sleep(0.1)
        
    return final_leads