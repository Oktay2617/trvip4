import re
import sys
import time
from urllib.parse import urlparse, parse_qs, urljoin
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

# Taraftarium ana domain'i
TARAFTARIUM_DOMAIN = "https://taraftarium24.xyz/"

# Kullanılacak User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

# --- event.html'den M3U8 base URL'ini çıkarma fonksiyonu (DEĞİŞİKLİK YOK) ---
def extract_base_m3u8_url(page, event_url):
    """
    Verilen event.html URL'sine gider ve JavaScript içeriğinden base URL'i çıkarır.
    """
    try:
        print(f"\n-> M3U8 Base URL'i almak için Event sayfasına gidiliyor: {event_url}")
        page.goto(event_url, timeout=20000, wait_until="domcontentloaded")
        content = page.content()
        # Önceki kodda çalışan Regex'i kullanıyoruz
        base_url_match = re.search(r"['\"](https?://[^'\"]+/checklist/)['\"]", content)
        if not base_url_match:
             base_url_match = re.search(r"streamUrl\s*=\s*['\"](https?://[^'\"]+/checklist/)['\"]", content) # Alternatif
        if not base_url_match:
            print(" -> ❌ Event sayfası kaynağında '/checklist/' ile biten base URL bulunamadı.")
            return None
        base_url = base_url_match.group(1)
        print(f"-> ✅ M3U8 Base URL bulundu: {base_url}")
        return base_url
    except Exception as e:
        print(f"-> ❌ Event sayfası işlenirken hata oluştu: {e}")
        return None

# --- YENİ FONKSİYON: Tüm Kanal Listesini Kazıma ---
def scrape_all_channels(page):
    """
    Taraftarium ana sayfasını ziyaret eder, JS'in yüklenmesini bekler
    ve tüm kanalların isimlerini ve stream ID'lerini kazır.
    """
    print(f"\n📡 Tüm kanallar {TARAFTARIUM_DOMAIN} adresinden çekiliyor...")
    channels = []
    try:
        page.goto(TARAFTARIUM_DOMAIN, timeout=25000, wait_until='networkidle') # JS'in çalışması için 'networkidle' bekleyelim

        # Kanal listesi elemanlarının (JS tarafından oluşturulan) görünmesini bekle
        list_item_selector = ".macListe .mac"
        print(f"-> Kanal listesi elemanlarının ('{list_item_selector}') yüklenmesi bekleniyor...")
        page.wait_for_selector(list_item_selector, timeout=15000)
        print("-> ✅ Kanal listesi elemanları yüklendi.")

        # Sayfadaki tüm kanal elemanlarını bul
        channel_elements = page.query_selector_all(list_item_selector)

        if not channel_elements:
            print("❌ Ana sayfada '.macListe .mac' elemanı bulunamadı.")
            return []

        print(f"-> {len(channel_elements)} adet potansiyel kanal elemanı bulundu. Bilgiler çıkarılıyor...")
        
        processed_ids = set() # Aynı ID'li kanalları tekrar eklememek için

        for element in channel_elements:
            # Kanal adını al (.takimlar içindeki metin)
            name_element = element.query_selector(".takimlar")
            channel_name = name_element.inner_text().strip() if name_element else "İsimsiz Kanal"

            # Stream ID'sini al (Varsayım: JS 'data-stream-id' özniteliği ekliyor)
            # --- BU KISIM GEREKİRSE DEĞİŞTİRİLMELİ ---
            stream_id = element.get_attribute('data-stream-id') # VEYA 'data-id', 'data-channel' vb. olabilir
            
            # Eğer data-stream-id yoksa, tıklama olayından ID'yi çıkarmaya çalışalım (Daha karmaşık)
            # Bu kısım şimdilik YORUMDA, çünkü yapıyı bilmiyoruz
            # if not stream_id:
            #     onclick_attr = element.get_attribute('onclick')
            #     if onclick_attr:
            #         match = re.search(r"loadChannel\(['\"]([^'\"]+)['\"]\)", onclick_attr)
            #         if match:
            #             stream_id = match.group(1)

            if stream_id and stream_id not in processed_ids:
                channels.append({
                    'name': channel_name,
                    'id': stream_id
                })
                processed_ids.add(stream_id)
            # else:
            #     print(f"-> Uyarı: '{channel_name}' için stream ID bulunamadı veya zaten işlendi.")


        print(f"✅ {len(channels)} adet benzersiz kanal bilgisi başarıyla çıkarıldı.")
        return channels

    except PlaywrightTimeoutError:
         print(f"❌ Zaman aşımı: Kanal listesi elemanları ({list_item_selector}) belirtilen sürede yüklenmedi.")
         return []
    except Exception as e:
        print(f"❌ Ana sayfa işlenirken hata oluştu: {e}")
        return []

# --- Gruplama Fonksiyonu (DEĞİŞİKLİK YOK - Gerekirse güncellenir) ---
def get_channel_group(channel_name):
    channel_name_lower = channel_name.lower()
    group_mappings = {
        'BeinSports': ['bein sports', 'beın sports', ' bs', ' bein '], # Kısaltmalar eklendi
        'S Sports': ['s sport'],
        'Tivibu': ['tivibu spor', 'tivibu'],
        'Exxen': ['exxen'],
        'Ulusal Kanallar': ['a spor', 'trt spor', 'trt 1', 'tv8', 'atv', 'kanal d', 'show tv', 'star tv'],
        'Diğer Spor': ['smart spor', 'nba tv', 'eurosport', 'sport tv', 'premier sports'],
        'Belgesel': ['national geographic', 'nat geo', 'discovery', 'dmax', 'bbc earth', 'history'],
        'Film & Dizi': ['bein series', 'bein movies', 'movie smart', 'filmbox', 'sinema tv']
    }
    for group, keywords in group_mappings.items():
        for keyword in keywords:
            if keyword in channel_name_lower:
                return group
    # ID'lere göre ek kontrol (Taraftarium'a özel olabilir)
    if 'bs' in channel_name_lower: return 'BeinSports'
    if 'ss' in channel_name_lower: return 'S Sports'
    if 'ts' in channel_name_lower: return 'Tivibu'
    if 'ex' in channel_name_lower: return 'Exxen'

    return "Diğer Kanallar" # Varsayılan grup

# --- Ana Fonksiyon ---
def main():
    with sync_playwright() as p:
        print("🚀 Playwright ile Taraftarium24 M3U8 Kanal İndirici Başlatılıyor (Tüm Liste)...")

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        # 1. Adım: Varsayılan kanaldan event URL'sini ve ID'sini al (Base URL'i bulmak için)
        default_event_url, default_stream_id = scrape_default_channel_info(page)
        if not default_event_url:
            print("❌ UYARI: Varsayılan kanal bilgisi alınamadı, M3U8 Base URL bulunamıyor. İşlem sonlandırılıyor.")
            browser.close()
            sys.exit(1)

        # 2. Adım: event.html'den M3U8 Base URL'ini çıkar
        base_m3u8_url = extract_base_m3u8_url(page, default_event_url)
        if not base_m3u8_url:
            print("❌ UYARI: M3U8 Base URL alınamadı. İşlem sonlandırılıyor.")
            browser.close()
            sys.exit(1)

        # 3. Adım: Ana sayfaya tekrar gidip (veya aynı sayfada kalarak) tüm kanalları kazı
        channels = scrape_all_channels(page)
        if not channels:
            print("❌ UYARI: Hiçbir kanal bulunamadı, işlem sonlandırılıyor.")
            browser.close()
            sys.exit(1)

        m3u_content = []
        output_filename = "taraftarium24_kanallar.m3u8"
        print(f"\n📺 {len(channels)} kanal için M3U8 linkleri oluşturuluyor...")
        created = 0

        # --- Global Başlıklar için Referer ---
        # event.html'nin değil, ana sayfanın referer olması daha mantıklı olabilir
        player_origin_host = TARAFTARIUM_DOMAIN.rstrip('/')
        player_referer = TARAFTARIUM_DOMAIN

        m3u_header_lines = [
            "#EXTM3U",
            f"#EXT-X-USER-AGENT:{USER_AGENT}",
            f"#EXT-X-REFERER:{player_referer}",
            f"#EXT-X-ORIGIN:{player_origin_host}"
        ]
        # --- Bitti ---

        for i, channel_info in enumerate(channels, 1):
            channel_name = channel_info['name']
            stream_id = channel_info['id']
            group_name = get_channel_group(channel_name if channel_name != "İsimsiz Kanal" else stream_id) # Gruplama için ID'yi de kullan

            # M3U8 linkini oluştur
            m3u8_link = f"{base_m3u8_url}{stream_id}.m3u8"

            print(f"[{i}/{len(channels)}] {channel_name} (ID: {stream_id}, Grup: {group_name}) -> {m3u8_link}")

            m3u_content.append(f'#EXTINF:-1 tvg-name="{channel_name}" group-title="{group_name}",{channel_name}')
            m3u_content.append(m3u8_link)
            created += 1

        browser.close()

        if created > 0:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_header_lines))
                f.write("\n")
                f.write("\n".join(m3u_content))
            print(f"\n\n📂 {created} kanal başarıyla '{output_filename}' dosyasına kaydedildi.")
        else:
            print("\n\nℹ️  Geçerli hiçbir M3U8 linki oluşturulamadığı için dosya oluşturulmadı.")

        print("\n🎉 İşlem tamamlandı!")

if __name__ == "__main__":
    main()
