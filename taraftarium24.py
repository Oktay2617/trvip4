import re
import sys
import time
from urllib.parse import urlparse, parse_qs, urljoin
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

# Taraftarium ana domain'i
TARAFTARIUM_DOMAIN = "https://taraftarium24.xyz/"

# Kullanılacak User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

# --- Varsayılan Kanal Bilgisini Alma Fonksiyonu (DEĞİŞİKLİK YOK) ---
def scrape_default_channel_info(page):
    print(f"\n📡 Varsayılan kanal bilgisi {TARAFTARIUM_DOMAIN} adresinden alınıyor...")
    try:
        # Ana sayfaya ilk gidiş. DOM'un yüklenmesini bekle.
        page.goto(TARAFTARIUM_DOMAIN, timeout=25000, wait_until='domcontentloaded')

        iframe_selector = "iframe#customIframe"
        print(f"-> Varsayılan iframe ('{iframe_selector}') aranıyor...")
        page.wait_for_selector(iframe_selector, timeout=15000) # Biraz daha bekle
        iframe_element = page.query_selector(iframe_selector)

        if not iframe_element:
            print("❌ Ana sayfada 'iframe#customIframe' bulunamadı.")
            return None, None

        iframe_src = iframe_element.get_attribute('src')
        if not iframe_src:
            print("❌ Iframe 'src' özniteliği boş.")
            return None, None

        event_url = urljoin(TARAFTARIUM_DOMAIN, iframe_src)
        parsed_event_url = urlparse(event_url)
        query_params = parse_qs(parsed_event_url.query)
        stream_id = query_params.get('id', [None])[0]

        if not stream_id:
            print(f"❌ Event URL'sinde ({event_url}) 'id' parametresi bulunamadı.")
            return None, None

        print(f"✅ Varsayılan kanal bilgisi alındı: ID='{stream_id}', EventURL='{event_url}'")
        return event_url, stream_id

    except Exception as e:
        print(f"❌ Ana sayfaya ulaşılamadı veya iframe bilgisi alınamadı: {e.__class__.__name__} - {e}")
        return None, None

# --- M3U8 Base URL Çıkarma Fonksiyonu (DEĞİŞİKLİK YOK) ---
def extract_base_m3u8_url(page, event_url):
    try:
        print(f"\n-> M3U8 Base URL'i almak için Event sayfasına gidiliyor: {event_url}")
        page.goto(event_url, timeout=20000, wait_until="domcontentloaded")
        content = page.content()
        base_url_match = re.search(r"['\"](https?://[^'\"]+/checklist/)['\"]", content)
        if not base_url_match:
             base_url_match = re.search(r"streamUrl\s*=\s*['\"](https?://[^'\"]+/checklist/)['\"]", content)
        if not base_url_match:
            print(" -> ❌ Event sayfası kaynağında '/checklist/' ile biten base URL bulunamadı.")
            return None
        base_url = base_url_match.group(1)
        print(f"-> ✅ M3U8 Base URL bulundu: {base_url}")
        return base_url
    except Exception as e:
        print(f"-> ❌ Event sayfası işlenirken hata oluştu: {e}")
        return None

# --- GÜNCELLENEN FONKSİYON: Tüm Kanal Listesini Kazıma ---
def scrape_all_channels(page):
    """
    Taraftarium ana sayfasında JS'in yüklenmesini bekler ve tüm kanalların
    isimlerini ve stream ID'lerini DATA-URL'den kazır.
    """
    print(f"\n📡 Tüm kanallar {TARAFTARIUM_DOMAIN} adresinden çekiliyor...")
    channels = []
    try:
        # Ana sayfa zaten yüklü, JS'in listeyi doldurmasını bekle
        list_container_selector = ".macListeWrapper" # Ana kapsayıcı
        # İlk kanalın görünmesini bekle (daha spesifik bir bekleme)
        first_channel_selector = f"{list_container_selector} .macListe#hepsi .mac[data-url]"
        print(f"-> Kanal listesi elemanlarının ('{first_channel_selector}') yüklenmesi bekleniyor...")
        page.wait_for_selector(first_channel_selector, timeout=25000, state="visible") # Daha uzun bekle
        print("-> ✅ Kanal listesi elemanları yüklendi.")
        
        # Ekstra bekleme, tüm listenin dolması için (bazen JS yavaş olabilir)
        page.wait_for_timeout(2000) 

        # Sadece görünür olan #hepsi listesindeki kanalları alalım
        channel_elements = page.query_selector_all(".macListe#hepsi .mac[data-url]")

        if not channel_elements:
            print("❌ '.macListe#hepsi' içinde [data-url] içeren '.mac' elemanı bulunamadı.")
            # Diğer sekmeleri de kontrol etmeyi deneyebiliriz ama şimdilik #hepsi yeterli olmalı
            return []

        print(f"-> {len(channel_elements)} adet potansiyel kanal elemanı bulundu. Bilgiler çıkarılıyor...")
        processed_ids = set()

        for element in channel_elements:
            # Kanal adını al
            name_element = element.query_selector(".takimlar")
            channel_name = name_element.inner_text().strip() if name_element else "İsimsiz Kanal"
            # İsimden "CANLI" etiketini temizle (varsa)
            channel_name = channel_name.replace('CANLI', '').strip()

            # --- DÜZELTME: Stream ID'yi DATA-URL'den al ---
            data_url = element.get_attribute('data-url')
            stream_id = None
            if data_url:
                try:
                    parsed_data_url = urlparse(data_url)
                    query_params = parse_qs(parsed_data_url.query)
                    stream_id = query_params.get('id', [None])[0]
                except Exception:
                    pass # Geçersiz data-url ise atla
            # --- DÜZELTME BİTTİ ---

            if stream_id and stream_id not in processed_ids:
                # Zaman bilgisini de ekleyelim (varsa)
                time_element = element.query_selector(".saat")
                time_str = time_element.inner_text().strip() if time_element else None
                if time_str and time_str != "CANLI":
                     final_channel_name = f"{channel_name} ({time_str})"
                else:
                     final_channel_name = channel_name

                channels.append({
                    'name': final_channel_name,
                    'id': stream_id
                })
                processed_ids.add(stream_id)
            # else:
            #     # ID bulunamayanları veya tekrarları loglamak isterseniz:
            #     print(f"-> Uyarı: '{channel_name}' için stream ID bulunamadı ('{data_url}') veya zaten işlendi.")
            #     pass


        print(f"✅ {len(channels)} adet benzersiz kanal bilgisi başarıyla çıkarıldı.")
        return channels

    except PlaywrightTimeoutError:
         print(f"❌ Zaman aşımı: Kanal listesi elemanları ({first_channel_selector}) belirtilen sürede yüklenmedi.")
         print("   Sayfanın yapısı değişmiş veya JS çok yavaş yükleniyor olabilir.")
         return []
    except Exception as e:
        print(f"❌ Kanal listesi işlenirken hata oluştu: {e}")
        return []

# --- Gruplama Fonksiyonu (Güncellendi: Daha fazla anahtar kelime) ---
def get_channel_group(channel_name):
    channel_name_lower = channel_name.lower()
    group_mappings = {
        'BeinSports': ['bein sports', 'beın sports', ' bs', ' bein '],
        'S Sports': ['s sport'],
        'Tivibu': ['tivibu spor', 'tivibu'],
        'Exxen': ['exxen'],
        'Ulusal Kanallar': ['a spor', 'trt spor', 'trt 1', 'tv8', 'atv', 'kanal d', 'show tv', 'star tv', 'trt yıldız', 'a2'],
        'Spor': ['smart spor', 'nba tv', 'eurosport', 'sport tv', 'premier sports', 'ht spor', 'sports tv'],
        'Yarış': ['tjk tv'],
        'Belgesel': ['national geographic', 'nat geo', 'discovery', 'dmax', 'bbc earth', 'history'],
        'Film & Dizi': ['bein series', 'bein movies', 'movie smart', 'filmbox', 'sinema tv'],
        'Haber': ['haber', 'cnn', 'ntv'],
        'Diğer': ['gs tv', 'fb tv', 'cbc sport'] # Eşleşmeyenler ve kulüp kanalları
    }
    for group, keywords in group_mappings.items():
        for keyword in keywords:
            if keyword in channel_name_lower:
                return group

    # Maç isimlerini ayıklama (Lig bilgisine göre daha iyi olabilir ama şimdilik basit)
    if re.search(r'\d{2}:\d{2}', channel_name): # İçinde saat varsa maçtır
        return "Maç Yayınları"
    if ' - ' in channel_name: # Takım ismi gibi görünüyorsa
        return "Maç Yayınları"

    return "Diğer Kanallar" # Kalanlar için varsayılan

# --- Ana Fonksiyon ---
def main():
    with sync_playwright() as p:
        print("🚀 Playwright ile Taraftarium24 M3U8 Kanal İndirici Başlatılıyor (Tüm Liste)...")

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        # 1. Adım: Varsayılan kanaldan event URL'sini ve ID'sini al
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

        # 3. Adım: Ana sayfadaki tüm kanalları kazı
        channels = scrape_all_channels(page)
        if not channels:
            print("❌ UYARI: Hiçbir kanal bulunamadı, işlem sonlandırılıyor.")
            browser.close()
            sys.exit(1)

        m3u_content = []
        output_filename = "taraftarium24_kanallar.m3u8"
        print(f"\n📺 {len(channels)} kanal için M3U8 linkleri oluşturuluyor...")
        created = 0

        player_origin_host = TARAFTARIUM_DOMAIN.rstrip('/')
        player_referer = TARAFTARIUM_DOMAIN

        m3u_header_lines = [
            "#EXTM3U",
            f"#EXT-X-USER-AGENT:{USER_AGENT}",
            f"#EXT-X-REFERER:{player_referer}",
            f"#EXT-X-ORIGIN:{player_origin_host}"
        ]

        for i, channel_info in enumerate(channels, 1):
            channel_name = channel_info['name']
            stream_id = channel_info['id']
            # Gruplamayı ID'ye göre değil, isme göre yapalım
            group_name = get_channel_group(channel_name)

            m3u8_link = f"{base_m3u8_url}{stream_id}.m3u8"

            # Konsola yazdırmayı azaltalım, sadece başarılı/başarısız yazsın
            # print(f"[{i}/{len(channels)}] {channel_name} (ID: {stream_id}, Grup: {group_name}) -> {m3u8_link}")

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
