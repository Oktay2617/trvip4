import re
import sys
import time
from urllib.parse import urlparse, parse_qs, urljoin
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

# Taraftarium ana domain'i
TARAFTARIUM_DOMAIN = "https://taraftarium24.xyz/"

# Kullanılacak User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

# --- EKSİK OLAN FONKSİYON GERİ EKLENDİ ---
def scrape_default_channel_info(page):
    """
    Taraftarium ana sayfasını ziyaret eder ve varsayılan iframe'den
    event.html URL'sini ve stream ID'sini alır.
    """
    print(f"\n📡 Varsayılan kanal bilgisi {TARAFTARIUM_DOMAIN} adresinden alınıyor...")
    try:
        page.goto(TARAFTARIUM_DOMAIN, timeout=25000, wait_until='domcontentloaded')

        iframe_selector = "iframe#customIframe"
        print(f"-> Varsayılan iframe ('{iframe_selector}') aranıyor...")
        page.wait_for_selector(iframe_selector, timeout=10000)
        iframe_element = page.query_selector(iframe_selector)

        if not iframe_element:
            print("❌ Ana sayfada 'iframe#customIframe' bulunamadı.")
            return None, None

        iframe_src = iframe_element.get_attribute('src')
        if not iframe_src:
            print("❌ Iframe 'src' özniteliği boş.")
            return None, None

        # event.html URL'sini oluştur (eğer src relativ ise)
        event_url = urljoin(TARAFTARIUM_DOMAIN, iframe_src)

        # event.html URL'sinden 'id' parametresini (streamId) al
        parsed_event_url = urlparse(event_url)
        query_params = parse_qs(parsed_event_url.query)
        stream_id = query_params.get('id', [None])[0]

        if not stream_id:
            print(f"❌ Event URL'sinde ({event_url}) 'id' parametresi bulunamadı.")
            return None, None

        print(f"✅ Varsayılan kanal bilgisi alındı: ID='{stream_id}', EventURL='{event_url}'")
        return event_url, stream_id

    except Exception as e:
        print(f"❌ Ana sayfaya ulaşılamadı veya iframe bilgisi alınamadı: {e.__class__.__name__}")
        return None, None
# --- DÜZELTME BİTTİ ---

# --- event.html'den M3U8 base URL'ini çıkarma fonksiyonu (DEĞİŞİKLİK YOK) ---
def extract_base_m3u8_url(page, event_url):
    """
    Verilen event.html URL'sine gider ve JavaScript içeriğinden base URL'i çıkarır.
    """
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

# --- Tüm Kanal Listesini Kazıma Fonksiyonu (DEĞİŞİKLİK YOK) ---
def scrape_all_channels(page):
    """
    Taraftarium ana sayfasını ziyaret eder, JS'in yüklenmesini bekler
    ve tüm kanalların isimlerini ve stream ID'lerini kazır.
    """
    print(f"\n📡 Tüm kanallar {TARAFTARIUM_DOMAIN} adresinden çekiliyor...")
    channels = []
    try:
        # Ana sayfaya tekrar gitmek yerine mevcut sayfada kalabiliriz,
        # çünkü scrape_default_channel_info zaten oradaydı.
        # page.goto(TARAFTARIUM_DOMAIN, timeout=25000, wait_until='networkidle') # Tekrar gitmeye gerek yok

        list_item_selector = ".macListe .mac"
        print(f"-> Kanal listesi elemanlarının ('{list_item_selector}') yüklenmesi bekleniyor...")
        # Sayfa zaten yüklü olduğu için bekleme süresini biraz daha kısa tutabiliriz
        page.wait_for_selector(list_item_selector, timeout=20000, state="visible")
        print("-> ✅ Kanal listesi elemanları yüklendi.")

        channel_elements = page.query_selector_all(list_item_selector)

        if not channel_elements:
            print("❌ Ana sayfada '.macListe .mac' elemanı bulunamadı.")
            return []

        print(f"-> {len(channel_elements)} adet potansiyel kanal elemanı bulundu. Bilgiler çıkarılıyor...")
        processed_ids = set()

        for element in channel_elements:
            name_element = element.query_selector(".takimlar")
            channel_name = name_element.inner_text().strip() if name_element else "İsimsiz Kanal"

            # Stream ID'sini alma - DİKKAT: Bu kısım hala bir varsayım!
            stream_id = element.get_attribute('data-stream-id')

            # --- Geliştirilmiş ID Çıkarma (onclick'ten) ---
            if not stream_id:
                onclick_attr = element.get_attribute('onclick')
                if onclick_attr:
                    # Örnek onclick="loadChannel('androstreamlivebs2')"
                    match = re.search(r"loadChannel\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick_attr, re.IGNORECASE)
                    if match:
                        stream_id = match.group(1)
            # --- Bitti ---

            if stream_id and stream_id not in processed_ids:
                channels.append({
                    'name': channel_name,
                    'id': stream_id
                })
                processed_ids.add(stream_id)
            else:
                 # ID bulunamayanları veya tekrarları sessizce atla
                 pass
                 # print(f"-> Uyarı: '{channel_name}' için stream ID bulunamadı veya zaten işlendi.")


        print(f"✅ {len(channels)} adet benzersiz kanal bilgisi başarıyla çıkarıldı.")
        return channels

    except PlaywrightTimeoutError:
         print(f"❌ Zaman aşımı: Kanal listesi elemanları ({list_item_selector}) belirtilen sürede yüklenmedi.")
         print("   Sayfanın yapısı değişmiş veya JS yavaş yükleniyor olabilir.")
         return []
    except Exception as e:
        print(f"❌ Ana sayfa işlenirken hata oluştu: {e}")
        return []

# --- Gruplama Fonksiyonu (DEĞİŞİKLİK YOK) ---
def get_channel_group(channel_name):
    channel_name_lower = channel_name.lower()
    group_mappings = {
        'BeinSports': ['bein sports', 'beın sports', ' bs', ' bein '],
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
    if 'bs' in channel_name_lower: return 'BeinSports'
    if 'ss' in channel_name_lower: return 'S Sports'
    if 'ts' in channel_name_lower: return 'Tivibu'
    if 'ex' in channel_name_lower: return 'Exxen'
    return "Diğer Kanallar"

# --- Ana Fonksiyon (DEĞİŞİKLİK YOK) ---
def main():
    with sync_playwright() as p:
        print("🚀 Playwright ile Taraftarium24 M3U8 Kanal İndirici Başlatılıyor (Tüm Liste)...")

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        # 1. Adım: Varsayılan kanaldan event URL'sini ve ID'sini al
        default_event_url, default_stream_id = scrape_default_channel_info(page) # Hata buradaydı
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
            group_name = get_channel_group(channel_name if channel_name != "İsimsiz Kanal" else stream_id)

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
