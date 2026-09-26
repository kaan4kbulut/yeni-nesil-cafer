"""Hazır API kataloğu: sık kullanılan, herkesin kolayca bağlanabileceği HTTP API'leri.

- Anahtarsız olanlar (free=True, auth="none") varsayılan olarak açıktır: asistan `call_api` ile hemen
  kullanabilir, kullanıcının bir şey kurması gerekmez. Adresleri Eylül 2026'da denendi.
- Anahtar isteyenler API'ler sekmesindeki "hazır API'ler" listesinden tek tıkla eklenir.
- Asistan `find_api` aracıyla bu kataloğu arar; elinde olmayan bir API'yi kullanıcıya önerir.
"""

from dataclasses import dataclass

from .connections import Connection


@dataclass
class ApiEntry:
    id: str
    name: str
    category: str
    summary: str  # kullanıcıya görünen kısa Türkçe açıklama
    usage: str  # modele: ne işe yarar, hangi yol ve parametreler (İngilizce, kısa)
    base_url: str
    auth: str = "none"  # none | query | header | bearer
    auth_param: str = ""
    key_url: str = ""  # anahtarın alındığı sayfa
    tags: str = ""  # find_api araması için ek sözcükler

    @property
    def free(self) -> bool:
        return self.auth == "none"

    def connection(self) -> Connection:
        """Asistanın call_api ile kullanabileceği bağlantı (anahtarsızlar için hazır)."""
        return Connection(kind="tool", name=self.name, base_url=self.base_url, id=f"hazir-{self.id}",
                          description=self.usage, auth=self.auth, auth_param=self.auth_param)


CATALOG = [
    # ---- anahtarsız, ücretsiz (varsayılan açık)
    ApiEntry("hava", "Open-Meteo", "Hava durumu", "Hava durumu ve 16 günlük tahmin, anahtarsız",
             "Weather forecast. GET /v1/forecast?latitude=..&longitude=..&current=temperature_2m,weather_code,"
             "wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto "
             "(get coordinates from Open-Meteo Geocoding first)",
             "https://api.open-meteo.com", tags="weather hava sıcaklık yağmur tahmin"),
    ApiEntry("konum", "Open-Meteo Geocoding", "Harita ve konum", "Şehir adından koordinat bulma, anahtarsız",
             "City name to coordinates. GET /v1/search?name=Ankara&count=1&language=tr",
             "https://geocoding-api.open-meteo.com", tags="koordinat şehir enlem boylam geocode"),
    ApiEntry("adres", "OpenStreetMap Nominatim", "Harita ve konum", "Adres ve yer arama (OpenStreetMap)",
             "Search places/addresses. GET /search?q=Kadıköy&format=json&limit=3 ; reverse: "
             "GET /reverse?lat=..&lon=..&format=json. Max 1 request per second.",
             "https://nominatim.openstreetmap.org", tags="adres harita yer mekan osm"),
    ApiEntry("doviz", "Frankfurter", "Finans", "Döviz kurları (Avrupa Merkez Bankası), anahtarsız",
             "Currency exchange rates. GET /v1/latest?base=USD&symbols=TRY,EUR ; history: "
             "GET /v1/2026-01-01..2026-02-01?base=EUR&symbols=TRY",
             "https://api.frankfurter.dev", tags="döviz kur dolar euro para currency"),
    ApiEntry("tcmb", "TCMB Kurlar", "Finans", "Merkez Bankası günlük döviz kurları (XML)",
             "Central Bank of Turkey daily exchange rates as XML. GET /kurlar/today.xml",
             "https://www.tcmb.gov.tr", tags="merkez bankası kur döviz dolar euro altın"),
    ApiEntry("kripto", "CoinGecko", "Finans", "Kripto para fiyatları, anahtarsız (sınırlı)",
             "Crypto prices. GET /api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=try,usd ; "
             "search coin ids: GET /api/v3/search?query=..",
             "https://api.coingecko.com", tags="bitcoin ethereum kripto coin fiyat"),
    ApiEntry("wikipedia", "Wikipedia TR", "Bilgi", "Türkçe Vikipedi özetleri ve arama",
             "Turkish Wikipedia. Summary: GET /api/rest_v1/page/summary/<Title> ; search: "
             "GET /w/api.php?action=query&list=search&srsearch=..&format=json",
             "https://tr.wikipedia.org", tags="ansiklopedi bilgi vikipedi wiki"),
    ApiEntry("tatil", "Nager.Date", "Takvim", "Resmi tatiller (Türkiye ve 100+ ülke)",
             "Public holidays. GET /api/v3/PublicHolidays/2026/TR ; next: GET /api/v3/NextPublicHolidays/TR",
             "https://date.nager.at", tags="tatil bayram resmi tatil takvim"),
    ApiEntry("namaz", "Aladhan", "Takvim", "Namaz vakitleri (Diyanet hesaplaması)",
             "Prayer times. GET /v1/timingsByCity?city=Istanbul&country=Turkey&method=13 (13 = Diyanet)",
             "https://api.aladhan.com", tags="namaz vakit ezan imsak iftar ramazan"),
    ApiEntry("deprem", "AFAD Deprem", "Deprem", "AFAD son depremler (Türkiye)",
             "Turkish earthquakes (AFAD). GET /event/filter?start=2026-09-20T00:00:00&end=2026-09-23T23:59:59"
             "&minmag=3&orderby=timedesc (times in UTC)",
             "https://servisnet.afad.gov.tr/apigateway/deprem/apiv2", tags="deprem sarsıntı afad kandilli"),
    ApiEntry("deprem-dunya", "USGS Earthquakes", "Deprem", "Dünya genelinde depremler (USGS)",
             "Worldwide earthquakes. GET /fdsnws/event/1/query?format=geojson&starttime=2026-09-01&minmagnitude=5"
             "&limit=20 (add minlatitude/maxlatitude/minlongitude/maxlongitude for a region)",
             "https://earthquake.usgs.gov", tags="deprem earthquake dünya"),
    ApiEntry("kitap", "Open Library", "Bilgi", "Kitap arama (yazar, başlık, ISBN)",
             "Books. GET /search.json?q=..&limit=5 ; by ISBN: GET /isbn/<isbn>.json",
             "https://openlibrary.org", tags="kitap yazar isbn roman"),
    ApiEntry("sozluk", "Free Dictionary", "Dil", "İngilizce sözlük: anlam, telaffuz, örnek",
             "English dictionary. GET /api/v2/entries/en/<word>",
             "https://api.dictionaryapi.dev", tags="sözlük ingilizce kelime anlam"),
    ApiEntry("github", "GitHub", "Yazılım", "Açık GitHub depoları, sürümler, sorunlar (anahtarsız sınırlı)",
             "GitHub REST (public data, 60 requests/hour). GET /repos/<owner>/<repo> ; "
             "GET /repos/<owner>/<repo>/releases/latest ; GET /search/repositories?q=..",
             "https://api.github.com", tags="github repo kod yazılım sürüm"),
    # ---- anahtar gerekir (hazır API'ler listesinden eklenir)
    ApiEntry("openweather", "OpenWeatherMap", "Hava durumu", "Ayrıntılı hava durumu (ücretsiz anahtar)",
             "Weather. GET /data/2.5/weather?q=Istanbul&units=metric&lang=tr ; forecast: /data/2.5/forecast?q=..",
             "https://api.openweathermap.org", "query", "appid", "https://home.openweathermap.org/api_keys",
             tags="hava weather"),
    ApiEntry("haber", "NewsAPI", "Haberler", "Güncel haberler, 80 000+ kaynak (ücretsiz geliştirici anahtarı)",
             "News. GET /v2/top-headlines?country=tr ; search: GET /v2/everything?q=..&language=tr&sortBy=publishedAt",
             "https://newsapi.org", "header", "X-Api-Key", "https://newsapi.org/register",
             tags="haber gündem news manşet"),
    ApiEntry("gnews", "GNews", "Haberler", "Haber arama, Türkçe kaynaklar (ücretsiz anahtar)",
             "News. GET /api/v4/top-headlines?lang=tr&country=tr ; search: GET /api/v4/search?q=..&lang=tr",
             "https://gnews.io", "query", "apikey", "https://gnews.io/register", tags="haber gündem news"),
    ApiEntry("brave", "Brave Search", "Arama", "Web araması API'si (ücretsiz kota)",
             "Web search. GET /res/v1/web/search?q=..&country=tr&search_lang=tr",
             "https://api.search.brave.com", "header", "X-Subscription-Token",
             "https://api-dashboard.search.brave.com/app/keys", tags="arama web search"),
    ApiEntry("film", "TMDB", "Eğlence", "Film ve dizi bilgileri, Türkçe (ücretsiz anahtar)",
             "Movies/TV. GET /3/search/movie?query=..&language=tr-TR ; GET /3/trending/all/week?language=tr-TR",
             "https://api.themoviedb.org", "bearer", "", "https://www.themoviedb.org/settings/api",
             tags="film dizi sinema movie"),
    ApiEntry("borsa", "Alpha Vantage", "Finans", "Hisse senedi ve borsa verileri (ücretsiz anahtar)",
             "Stocks. GET /query?function=GLOBAL_QUOTE&symbol=AAPL ; GET /query?function=SYMBOL_SEARCH&keywords=..",
             "https://www.alphavantage.co", "query", "apikey", "https://www.alphavantage.co/support/#api-key",
             tags="borsa hisse stock bist"),
    ApiEntry("nasa", "NASA", "Bilim", "Günün astronomi fotoğrafı, Mars, asteroitler",
             "NASA. GET /planetary/apod ; GET /neo/rest/v1/feed?start_date=..",
             "https://api.nasa.gov", "query", "api_key", "https://api.nasa.gov/", tags="uzay nasa astronomi"),
    ApiEntry("youtube", "YouTube Data", "Eğlence", "YouTube video ve kanal arama (Google anahtarı)",
             "YouTube. GET /youtube/v3/search?part=snippet&q=..&type=video&maxResults=5",
             "https://www.googleapis.com", "query", "key", "https://console.cloud.google.com/apis/credentials",
             tags="youtube video kanal"),
    ApiEntry("futbol", "football-data.org", "Spor", "Futbol ligleri, fikstür, puan durumu (ücretsiz anahtar)",
             "Football. GET /v4/competitions/PL/standings ; GET /v4/matches?dateFrom=..&dateTo=..",
             "https://api.football-data.org", "header", "X-Auth-Token", "https://www.football-data.org/client/register",
             tags="futbol maç lig puan spor"),
]

BY_ID = {e.id: e for e in CATALOG}
CATEGORIES = list(dict.fromkeys(e.category for e in CATALOG))


def builtin_connections(disabled: list[str] | None = None) -> list[Connection]:
    """Varsayılan açık anahtarsız API'ler (kullanıcının kapattıkları hariç)."""
    off = set(disabled or [])
    return [e.connection() for e in CATALOG if e.free and e.id not in off]


def search(query: str) -> list[ApiEntry]:
    """Konuya uyan katalog girdileri (basit sözcük eşleşmesi)."""
    words = [w for w in query.lower().replace(",", " ").split() if len(w) > 2]
    scored = []
    for e in CATALOG:
        hay = f"{e.name} {e.category} {e.summary} {e.usage} {e.tags}".lower()
        score = sum(1 for w in words if w in hay or any(t.startswith(w[:5]) for t in hay.split()))
        if score:
            scored.append((score, e))
    return [e for _, e in sorted(scored, key=lambda x: -x[0])][:6]
