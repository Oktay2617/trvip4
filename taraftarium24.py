import re
import sys
import time
from urllib.parse import urlparse, parse_qs, urljoin
from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

# Taraftarium ana domain'i
TARAFTARIUM_DOMAIN = "https://taraftarium24.xyz/"

# --- YENİ FONKSİYON: Varsayılan Kanal Bilgisini Al ---
def scrape_default_channel_info(page):
    """
    Taraftarium ana sayfasını ziyaret eder ve varsayılan iframe'den
    event.html URL'sini ve stream ID'sini alır.
    """
    print(f"\n📡 Varsayılan kanal bilgisi {TARAFTARIUM_DOMAIN} adresinden alınıyor...")
    try:
        page.goto(TARAFTARIUM_DOMAIN, timeout=25000, wait_until='domcontentloaded')
        
        iframe_selector = "iframe#customIframe"
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

# --- YENİ FONKSİYON: event.html'den M3U8 çıkar ---
def extract_m3u8_from_event_page(page, event_url, stream_id):
    """
    Verilen event.html URL'sine gider, JavaScript içeriğinden base URL'i
    (tahmini olarak) çıkarır ve M3U8 linkini oluşturur.
    """
    try:
        print(f"-> Event sayfasına gidiliyor: {event_url}")
        page.goto(event_url, timeout=20000, wait_until="domcontentloaded")

        content = page.content()

        # JavaScript'ten base URL'i bulmaya çalış (Tahmini Regex - Değişebilir!)
        # Örnek M3U8'e bakarak '/checklist/' ile biten bir atama arıyoruz.
        base_url_match = re.search(r"['\"](https?://[^'\"]+/checklist/)['\"]", content)
        
        if not base_url_match:
            # Alternatif arama (örn: 'streamUrl =' gibi bir değişken olabilir)
             base_url_match = re.search(r"streamUrl\s*=\s*['\"](https?://[^'\"]+/checklist/)['\"]", content)

        if not base_url_match:
            print(" -> ❌ Event sayfası kaynağında '/checklist/' ile biten base URL bulunamadı.")
            return None
        
        base_url = base_url_match.group(1)
        print(f"-> ✅ Base URL bulundu: {base_url}")

        # M3U8 linkini oluştur ve döndür
        m3u8_link = f"{base_url}{stream_id}.m3u8"
        print(f"-> ✅ M3U8 linki oluşturuldu: {m3u8_link}")
        
        return m3u8_link

    except Exception as e:
        print(f"-> ❌ Event sayfası işlenirken hata oluştu: {e}")
        return None

def main():
    with sync_playwright() as p:
        print("🚀 Playwright ile Taraftarium24 M3U8 İndirici Başlatılıyor (Varsayılan Kanal)...")
        
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        event_url, stream_id = scrape_default_channel_info(page)

        if not event_url or not stream_id:
            print("❌ UYARI: Varsayılan kanal bilgisi alınamadı, işlem sonlandırılıyor.")
            browser.close()
            sys.exit(1)
        
        m3u_content = []
        output_filename = "taraftarium24_varsayilan.m3u8"
        print(f"\n📺 Varsayılan kanal ({stream_id}) için M3U8 linki işleniyor...")
        
        m3u8_link = extract_m3u8_from_event_page(page, event_url, stream_id)
        
        browser.close()

        if m3u8_link:
            # Kanal adını şimdilik ID'den alıyoruz, dinamik listede gerçek ad olurdu
            channel_name = stream_id.replace("androstreamlive", "").upper() 
            group_name = "Taraftarium24"
            
            # --- ÖNEMLİ NOT: Referer/Origin Gerekebilir! ---
            # Yayın sunucusu ('andro.okan11...') referer isteyebilir. 
            # Şimdilik global başlık eklemiyoruz ama gerekebilir.
            # player_origin = urlparse(event_url).scheme + "://" + urlparse(event_url).netloc
            
            header = "#EXTM3U"
            m3u_content = [
                header,
                f'#EXTINF:-1 tvg-name="{channel_name}" group-title="{group_name}",{channel_name}',
                # f'#EXTVLCOPT:http-referrer={player_origin}/', # Gerekirse bu satırı açın
                m3u8_link
            ]
            
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write("\n".join(m3u_content))
            print(f"\n\n📂 Varsayılan kanal başarıyla '{output_filename}' dosyasına kaydedildi.")
            print(f"ℹ️ Yayın sunucusu ({urlparse(m3u8_link).netloc}) 'Referer' başlığı isteyebilir.")
        else:
            print("\n\nℹ️  Geçerli M3U8 linki bulunamadığı için dosya oluşturulmadı.")

        print("\n🎉 İşlem tamamlandı!")

if __name__ == "__main__":
    main()
