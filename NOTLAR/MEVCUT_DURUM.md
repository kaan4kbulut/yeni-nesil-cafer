# MEVCUT DURUM — K0 haritası

Tarih: 2026-09-27 · dal `k-serisi` · commit `7113a46` · geri dönüş etiketi `v-k0-baslangic`. Kod okunarak ve komut
çalıştırılarak çıkarıldı, tahmin yok. Bu aşamada hiçbir kod değişmedi. Ölçüm betikleri `.cafer/k0_*.py` (git dışı).
Hedef yapı için `docs/MIMARI.md`, modüllerin tek satırlık açıklaması için `CLAUDE.md` → Dosya haritası.

## 1. Özet

- `asistan/` düz bir paket: kökte 51 modül (14.915 satır), tek alt paket `gui/` (29 dosya, 10.723 satır).
  `cekirdek/`, `arayuz/`, `yetenekler/`, `ayar/` klasörleri yok.
- **Çekirdek ayrımı fiilen büyük ölçüde var:** `gui/` dışındaki 50 modülden 47'si PySide6/fastapi yasaklıyken ayrı
  süreçte içe aktarılabiliyor. Qt'ye gerçekten bağlı tek modül `dictation.py`; kalan ikisi (`decor3d`,
  `figure3d_worker`) yalnızca 3D kütüphaneleri eksik olduğu için açılmıyor (ajan Python'unda çalışan alt süreçler).
- Arayüz çekirdeğe `agent.Callbacks` protokolüyle bağlı (`Agent.cb`); `gui/worker.py` bu protokolü Qt sinyallerine
  çeviren ince bir `QThread`. Bulut sunucu (`cloud_server.py`) aynı `agent`/`manager` kodunu Qt'siz kullanıyor.
- Eksik olanlar yapısal: sağlayıcı arayüzü, tek ayar kaynağı (`ayar.toml` + `CAFER_*`), kademe/profil, `modeller.json`,
  görev deposu (SQLite + checkpoint), yetenek manifestleri, hata sınıflandırıcı, CLI.

## 2. Giriş noktaları

| Giriş | Ne yapar | Qt |
|---|---|---|
| `main.py` | Masaüstü: güncelleme geri dönüşü (`rollback_if_needed`, asistan içe aktarılmadan) → `QApplication` → `gui.window.MainWindow`; Ollama'yı arka planda başlatır, ilk açılışta kurulum sihirbazı | evet |
| `calistir.sh` | Geliştirme: `.venv/bin/python main.py` | evet |
| `python -m asistan.cloud_server` | Bulut beyin: `http.server` API + web sayfası + Telegram botu + kuyruk (`DATA_DIR/bulut.json`, `bulut.db`) | hayır |
| `asistan/bootstrap.py` | İnternet kurulumu (yalnızca standart kütüphane): Python, paketler, Ollama, playwright chromium | hayır |
| `asistan/dictation_server.py` | Dikte alt süreci (faster-whisper) | hayır |
| `asistan/figure3d_worker.py`, `asistan/decor3d.py` | 3D alt süreçler (torch, manifold3d, trimesh; ajan Python'unda) | hayır |
| `asistan/askpass.py` | `sudo` parola penceresi (alt süreç, `YA_SUDO_COMMAND`) | evet |
| `paketleme/aktar.sh`, `paketle.py`, `yayinla.sh`, `bulut_paketi.sh`; `sunucu/kur.sh` | aktarma, paket, yayın kapısı, bulut paketi, sunucu kurulumu | — |
| `testler/sinav/calistir.py`, `testler/arayuz_denetimi.py` | gerçek görevli sınav; ekransız arayüz denetimi | — |
| CLI | **yok**: `python -m asistan` → `No module named asistan.__main__`; `cafer` komutu yok | — |

## 3. Modüller (gruplar, satır sayısı)

| Grup | Modüller | Qt'siz içe aktarılır mı |
|---|---|---|
| Çekirdek döngü | `agent` 1952, `manager` 552, `work` 540, `storage` 48, `choices` 51, `suggest` 165 | evet |
| Model seçimi | `roster` 316, `cards` 251, `categories` 262, `specialists` 267, `profiles` 146, `connections` 192, `catalog` 101, `model_updates` 459, `cli_agents` 477, `accounts` 231, `ctxprobe` 88 | evet |
| Araçlar | `tools` 1333, `registry` 87, `factory` 428, `mcp` 385, `browser` 477, `apps` 178, `api_catalog` 146, `libraries` 113, `hooks` 101, `definitions` 189 | evet |
| Hafıza/öğrenme | `memory_db` 278, `learning` 455 | evet |
| Güvenlik | `permissions` 119, `security` 343, `keystore` 85, `askpass` 27 | evet (`askpass` Qt'yi fonksiyon içinde yükler) |
| Görsel/3D/ses | `imagegen` 318, `inspect_output` 202, `figure3d` 167, `gpu` 279, `dictation` 272, `dictation_server` 70, `decor3d` 553, `figure3d_worker` 226 | `dictation` **hayır** (üst düzey PySide6); `decor3d`/`figure3d_worker` 3D kütüphanesi yok |
| Bulut | `cloud_server` 444, `cloud_sync` 80 | evet |
| Sistem/dağıtım | `sysinfo` 436, `power` 149, `results` 82, `problem_report` 270, `updates` 184, `bootstrap` 243, `config` 92 | evet |
| Arayüz | `gui/` 29 dosya (en büyükleri `chat` 1307, `sidebar` 1100, `panels` 786, `window` 762, `window_models` 723) | — |

`gui/` 41 ayrı çekirdek modülünü doğrudan içe aktarıyor; en çok kullanılanlar: `roster` (9 dosya), `agent` (8),
`cli_agents` (8), `sysinfo` (7), `specialists` (6), `power` (6), `model_updates` (6). Tek bir çekirdek cephesi yok.

## 4. Araçlar (`registry.REGISTRY`)

Risk sınıfları (kayıtta): `okur`, `danisir`, `yazar`, `ekip`, `calistirir`, `kurar`. Onay: `calistirir`/`kurar` her
seferinde; `yazar`/`ekip` değişiklik sayılır (kipe göre); `call_api` yalnızca GET dışında onaylı.

| Araç | Risk | Grup | K5 hedef yetenek |
|---|---|---|---|
| `list_files` | okur | temel | `dosya_listele` |
| `read_file` | okur | temel | `dosya_oku` |
| `search_files` | okur | temel | — |
| `write_file`, `edit_file` | yazar | temel | `dosya_yaz` |
| — | — | — | `dosya_tasi` (**karşılığı yok**; bugün `run_command` ile) |
| `run_command` | calistirir | temel | `komut_calistir` |
| `run_python` | calistirir | temel | `python_calistir` |
| `web_search` | okur | temel | `web_arama` |
| `fetch_url` | okur | temel | `web_oku` |
| `browser_open/read/click/type/scroll/back/look` | danisir | tarayici | `tarayici` (tıklama/yazmada `Agent._gate_browser_click` → `browser.gate`) |
| `call_api` | okur (GET dışı onaylı) | temel/ozel | — |
| `install_python_package` | kurar | ozel | — |
| `install_app` | kurar | herkes | — |
| `check_3d_model`, `check_installed`, `find_api`, `use_skill` | okur | çeşitli | — |
| `make_decor_model`, `make_3d_figure`, `generate_image` | yazar | ozel | — |
| `start_team_task` | ekip | ozel | — |
| `open_app`, `delegate_to_agent`, `look_at_image`, `ask_specialist`, `remember`, `inspect_output`, `learn_skill`, `request_tool` | danisir | çeşitli | — |

Dinamik araçlar: MCP sunucularının araçları (`sunucu__araç`, `mcp.py`, `CONFIG_DIR/mcp.json`), fabrika araçları
(`f_` önekli, `calistirir`, `DATA_DIR/arac-fabrikasi/araclar/<ad>/` → `arac.py`, `test_arac.py`, `arac.json`, git
deposu), dosyayla tanımlanan ajan/beceriler (`definitions.py`, `CONFIG_DIR/ajanlar|beceriler`), hazır beceriler
(`asistan/beceriler/`, ör. `3d-baski`). Tek çalıştırma yolu `agent._execute_tool` → `_permit` (`permissions.decide`)
→ `_gate_<ad>` → `Agent._tool_<ad>` ya da `Toolbox._tool_<ad>`.

## 5. Sağlayıcılar

| Sağlayıcı | Kod | Not |
|---|---|---|
| Ollama | `agent._run_ollama`, `_ollama_step`, `_ollama_call` (httpx `/api/chat`); `ollama_models`, `ollama_running`; `sysinfo.ensure_ollama`, `sysinfo.pull` | bağlam `ctxprobe`, `LEAN_CTX` → `agent.lean` |
| Claude API | `agent._run_claude`, `_claude_client` (`anthropic` SDK) | anahtar: keystore `anthropic` ya da `ANTHROPIC_API_KEY` |
| OpenAI uyumlu | `agent._run_openai(conn)` + `connections.Connection` (`baglantilar.json`, `LLM_PRESETS`) | katalog `catalog.py` (OpenAI, Gemini, DeepSeek, Groq, Mistral…), OpenRouter OAuth `accounts.py` |
| CLI ajanları | `agent._run_cli` → `cli_agents` (`cli:claude`, `cli:codex`, `cli:gemini`) | kurulum yalnızca düğmeyle, sabit SHA |

**Ortak arayüz yok:** dört yol `Agent` sınıfının içinde dal olarak duruyor (`sohbet/akis/saglik/maliyet` yok).
Sağlık: `connections.key_error` + oturumluk `_REJECTED` (401), `Connection.usable`; süreli önbellek yok. Maliyet takibi
yok. Seçim: `roster.worker_for/manager_for/stronger/default`, `categories`, `specialists`, kartlar `cards.py`.

## 6. Ayar mekanizması

- `config.Settings` (dataclass) → `CONFIG_DIR/ayarlar.json` (0600). 22 alan + serbest `extra` sözlüğü; `extra`'da
  kullanılan anahtarlar: `uncensored`, `uncensored_model`, `uncensored_only`, `api_off`, `power_override`, `dev_dir`,
  `kurulum`, `guvenlik_sansursuz`, `cloud`, `writer_model`, `cli_model`, `tanitim_surumu`, `sonuclari_topla`,
  `guncelleme_otomatik`, `guncelleme_denetimi`, `gorsel_added`, `dikte_temizle`, `dikte_dil`.
- Klasörler: `XDG_CONFIG_HOME`/`XDG_DATA_HOME` (Windows `APPDATA`/`LOCALAPPDATA`) + `yeni-nesil-cafer`; eski ad
  `config.migrate_dir` ile taşınır. Yollar içe aktarmada sabitlenir (testler önce XDG'yi değiştirir).
- `CONFIG_DIR`: `ayarlar.json`, `baglantilar.json`, `anahtarlar.json` (keyring yoksa), `ajanlar.json`, `ajanlar/`,
  `beceriler/`, `hooks.json`, `mcp.json`, `.ajan-kategorileri`.
- `DATA_DIR`: `sohbetler/`, `gorevler/`, `hafiza.db` (+ eski `hafiza.json`, `beceriler.json`), `gelisim*.{jsonl,json,md}`,
  `model-kartlari.json`, `model_katalogu.json`, `oneriler.json`, `arac-fabrikasi/`, `python-kutuphaneleri/`,
  `ajan-programlari/`, `ogrenilen-beceriler/`, `resim/`, `figur-motoru/`, `dikte-modeli/`, `tarayici-profili/`,
  `indirilenler/`, `onizleme-onbellegi/`, `mcp-kayitlari/`, `sorun-raporlari/`, `program-gunlugu.log`,
  `hook-kayitlari.log`, `guncelleme-durum.json`, `guncelleme-yedek/`, `askpass.sh`; bulut sunucuda `bulut.json`,
  `bulut.db`, `bulut-calisma/`.
- Ortam değişkenleri: yalnızca `ANTHROPIC_API_KEY`, `YA_SUDO_COMMAND`, `DIKTE_CPU`. **`ayar.toml` ve `CAFER_*` yok.**
- Anahtarlar: `keystore` (keyring hizmeti `yeni-nesil-cafer`, eski `yerel-asistan`'dan kopyalar; yedek JSON).

## 7. Test durumu (2026-09-27 ölçümü)

| Kontrol | Komut | Sonuç |
|---|---|---|
| Birim testleri | `python -m pytest testler/ -q -rs` (`.venv`, Python 3.14) | **249 geçti, 21 atlandı, 0 kaldı**, 14 sn |
| Atlananlar | — | hepsi 3D/belge kütüphanesi yokluğu: trimesh, build123d, PyMCubes/manifold3d, python-docx, matplotlib (`test_3d_baski` 5, `test_figur` 5, `test_sus_modelleri` 5, `test_sinav` 3, `test_denetim` 2, `test_kurulum` 1) |
| Kurulu programın Python'u | `~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest …` | **koşulamadı**: bu otomatik oturumda izin listesinde yok (onay istedi, reddedildi) |
| Arayüz denetimi | `python testler/arayuz_denetimi.py` (ekransız) | 714 eylem, 0 açılış hatası, 0 hatalı, 0 bağlantısız, 67 sn |
| Sınav | `testler/sinav/calistir.py` (gerçek Ollama) | K0'da koşulmadı; son ölçüm `RAPOR.md`: hizli 15/30 (%50), hepsi 9/20 (%45); eşik `esik.json` 0.80 |

Test dosyaları: 30 `test_*.py` (unittest; pytest ile de koşuyor), `arayuz_denetimi.py`, elle koşulanlar
`tarayici_gercek.py`, `dikte_uctan_uca.py`, yardımcı `ornek_mcp_sunucu.py`.

## 8. Hedef yapı (`docs/MIMARI.md` §2) ↔ bugün

Durum: ✓ var · ◐ işlev var, yer/biçim farklı · ✗ yok.

| Hedef | Bugünkü karşılığı | Durum | Aşama |
|---|---|---|---|
| `asistan/cekirdek/` (UI bilmez) | klasör yok; `asistan/` kökündeki 50 modülün 47'si zaten Qt'siz içe aktarılıyor | ◐ | K1 |
| `cekirdek/ayar.py` (`ayar.toml` + `CAFER_*`) | `config.Settings` → `ayarlar.json`, `Settings.extra`, `connections` (`baglantilar.json`), `keystore` | ◐ | K1 |
| `cekirdek/profil.py` → `.cafer/profil.json`, kademe | `sysinfo.py` (donanım taraması, önerilen model), `gpu.py` (en güçlü kart, `fault`), `power.py` (pil/hafif mod), `ctxprobe.py`; **kademe kavramı yok** | ◐ | K2 |
| `ayar/modeller.json` | yok; model adları 20 dosyada (bkz. §9.2); `model_updates` günlük listesi `DATA_DIR/model_katalogu.json` en yakın parça | ✗ | K2 |
| `cekirdek/yonlendirici.py` | `roster`, `categories`, `specialists`, `cards`; `model_policy` (yerel/guclu) var; `secim={saglayici,model,neden}`, gizlilik modu, maliyet tavanı, 5 dk sağlık önbelleği yok | ◐ | K3 |
| `cekirdek/guvenlik.py` + `ayar/guvenlik.toml` | `permissions.py` (tek izin hattı) + `security.py` (güvenlik ajanı, yasak listesi); politika dosyası yok | ◐ | K6 |
| `saglayici/temel.py`, `ollama.py`, `claude.py`, `openai_uyumlu.py`, `cli_ajan.py` | `agent._run_ollama/_run_claude/_run_openai/_run_cli`, `connections.py`, `cli_agents.py` | ◐ | K1 |
| `gorev/anlayici.py` | `manager.needs_plan`, `agent.is_task_request/is_install_request/is_advice_request` | ◐ | K4 |
| `gorev/planlayici.py` | `manager.py` JSON planı (başlık, talimat, bitti ölçütü); şema kısıtı (`format`) yok | ◐ | K4 |
| `gorev/yurutucu.py` | `manager.py` adım döngüsü (`_program` mesajları), `work.py` grup görevi; checkpoint yok | ◐ | K4 |
| `gorev/dogrulayici.py` | `manager._completion_check` (önce program kanıtı, sonra model), `inspect_output.py` | ◐ | K4 |
| `gorev/durum.py` → `gorevler.db` | `storage.py` (sohbet JSON; plan `_plan` alanında), `work.py` (`DATA_DIR/gorevler`); SQLite ve "yarım görevler" yok | ◐ | K4 |
| `yetenek/kayit.py` | `registry.py` + `mcp.py` + `factory.py` + `definitions.py`; manifest yok | ◐ | K5 |
| `yetenek/calistirici.py` | `agent._execute_tool` + `Toolbox`; fabrika sandbox'ı (`unshare -rn`, 60 sn) | ◐ | K5 |
| `yetenek/yukleyici.py` | dağınık: `tools._tool_install_python_package`, `libraries.install`, `apps.install` (flatpak/winget/brew/AppImage), `factory.install_packages` | ◐ | K6 |
| `yetenek/uretici.py` | `factory.py` (`request_tool`: hazır çözüm → yaz → sandbox → onay → kayıt, git) | ◐ | K6 |
| `analiz/hata.py` | yok; parçalar: `agent.describe_error`, `connections.key_error`, `gpu.fault`, `agent._CLAIMS_WORK`, `learning` başarısızlık kaydı, `problem_report` | ✗ | K6 |
| `analiz/olcum.py` | `cards.py` (hız, araç sınavı), `ctxprobe.py`, `testler/sinav/` | ◐ | K7 |
| `arayuz/masaustu/` | `asistan/gui/` + `main.py` | ◐ | K1 |
| `arayuz/web/` (FastAPI + PWA) | `cloud_server.py` (`http.server`, Telegram, web sayfası, kuyruk); FastAPI yok | ◐ | K8 |
| `arayuz/komut/` (`cafer` CLI) | yok | ✗ | K2/K4/K8 |
| `cekirdek/semalar/*.json` | yok | ✗ | K4/K5 |
| `yetenekler/<ad>/manifest.json + calistir.py + test` | yok; en yakın: `asistan/beceriler/`, fabrika araç klasörleri | ✗ | K5 |
| `sunucu/` (Dockerfile, compose, Caddyfile, `.env.ornek`) | `sunucu/kur.sh` + `BENIOKU.md` (systemd, Tailscale) | ◐ | K8 |
| `testler/` | 30 test dosyası + sınav seti + arayüz denetimi | ✓ | — |
| `.cafer/` (profil, görev deposu) | depo kökündeki `.cafer/` yalnızca geliştirme ilerlemesi; uygulama verisi XDG `DATA_DIR`'de | ✗ | K2/K4 (bkz. SORULAR) |

## 9. Mimari ihlaller

### 9.1 Çekirdek / arayüz karışıklığı

Gui dışındaki modüllerde Qt:
- `dictation.py:19` üst düzeyde `from PySide6.QtCore import QObject, QTimer, Signal`; `:154`, `:188` QtMultimedia
  (mikrofon kaydı). Qt'siz içe aktarılamayan tek gui dışı modül.
- `inspect_output.py:108-110`, `:131-133` PDF/SVG önizlemesi QtPdf/QtSvg ile (fonksiyon içinde; sunucuda çalışmaz).
- `problem_report.py:120` yalnızca PySide6 sürümünü okur (try/except; zararsız ama grep testine takılır).
- `askpass.py:12` parola penceresi — arayüz parçası, çekirdeğe girmemeli.

Arayüzdeki iş akışı (K1'de çekirdeğe inmeli):
- `gui/worker.py` `Agent` ve `manager.Manager`'ı doğrudan kurup çalıştırıyor; çekirdekte "bir isteği çalıştır" cephesi
  yok, web/CLI bu akışı yeniden yazmak zorunda kalır.
- `gui/window_help.py:298-387` güncelleme denetle → indir → kur → yeniden başlat (`subprocess.Popen main.py`).
- `gui/window_models.py:430`, `setup_wizard.py:350`, `model_advisor.py:243` model indirmeyi (`sysinfo.pull`) arayüzden
  iş parçacığıyla yönetiyor; `categories_dialog.py:146` `libraries.install`, `window_modes.py:322` `figure3d.install`
  (düğmeyle — kurala uygun, ama akış arayüzde).
- `gui/learning_dialog.py:45,53` terminal açıp betik çalıştırıyor.

### 9.2 Gömülü model adları

`/kontrol` 7 deseni (`ollama run`, `:<n>b`, `claude-`, `gpt-`) 20 dosyada 65 satır (yorumlar dahil, kaba). Önemliler:
- `config.py:42-54` `CLAUDE_MODELS`, varsayılan `ollama_model="qwen3.5:4b"`, `claude_model="claude-opus-5"`.
- `sysinfo.py:22` `BASE_MODEL`, `:28-35` donanıma göre önerilen model tablosu, `:295` `nomic-embed-text`.
- `categories.py:45-101` `SIZES`, `SMALL`, 7 kategorinin model listeleri.
- `catalog.py:29-85` bulut model kataloğu; `cli_agents.py:47-53` CLI model takma adları.
- `roster.py:25-26` aile puanları, `cards.py:110` `NO_TOOL_FAMILIES`, `specialists.py:28` akıl yürütme aileleri.
- `agent.py:49-51` `CLAUDE_FALLBACK_MODELS`, `CLAUDE_NO_THINKING`; `memory_db.py:25` `EMBED_MODEL`;
  `dictation.py:27` `CLEAN_MODELS`; `cloud_server.py:89`; `factory.py:103`; `model_updates.py:379`.
- `gui/`: `window_bar`, `window_models`, `window_accounts`, `learning_dialog` (birer satır).

### 9.3 Onaysız kurulum / silme / ağa gönderme

Her `pip install`, `/api/pull`, `rmtree`, `unlink` çağrısının çağıranı izlendi.

Kurala uygun: `install_python_package`, `install_app` (`kurar` → izin hattı); `sysinfo.pull`, `figure3d.install`,
`imagegen.install`, `cli_agents.install`, `libraries.install` yalnızca kullanıcı düğmesinden; güncelleme yalnızca
"Güncelle ve yeniden başlat" ile (otomatik olan günlük sürüm denetimi, GET); `factory.remove`,
`definitions.delete_skill_dir`, `libraries.remove`, sohbet/görev silme kullanıcının arayüzdeki eylemi; kalan
`unlink`'ler geçici dosya/indirme parçası temizliği.

Sapmalar:
1. **İkinci onay yolu:** `factory.py:394` (paket kurma) ve `:416` (araç ekleme) onayı `cb.ask_approval` ile doğrudan
   kullanıcıya soruyor, `permissions.decide`'den geçmiyor. Güvenliği gevşetmiyor (güvenlik ajanı kipinde de hep
   sorar) ama "onay kuralları yalnızca `permissions.py`'de" kuralına aykırı. `request_tool`'un kendisi `danisir`.
2. **Risk sınıfları CLAUDE.md ile uyuşmuyor:** CLAUDE.md "okur / yazar / siler / calistirir / kurar / internete
   gönderir" diyor; kayıtta `siler` ve `internete gönderir` yok (`danisir`, `ekip` var). Silme yalnızca `run_command`
   / `run_python` (`calistirir`) içinden ve `security.py` desenleriyle yakalanıyor.
3. **Ağa onaysız gönderme:** `web_search`, `fetch_url` (`okur`), `browser_type` (`danisir`), `call_api` GET sorgu
   metnini/parametreyi dışarı onaysız gönderiyor; `browser.gate` yalnızca ödeme/mesaj/hesap/giriş/indirmede soruyor.
   MIMARI §10 `ag = "sor"` karşılanmıyor (bugünkü tasarım: arama = okuma).
4. `cloud_sync.sync` bulut bağlantısı kurulunca hafızayı sunucuyla kendiliğinden eşitliyor (kullanıcı bağlantıyı
   kendisi kurduğu için bilinçli izin; tek tek onay yok).
5. **Kullanıcıya komut yazdırma** (CLAUDE.md: hiçbir zaman): `sysinfo.py:414-417` `install_hint` → kurulum
   sihirbazında "Terminalde çalıştır: `sudo pacman -S …` / `curl … | sh`"; `manager.py:232` "`ollama pull
   qwen3.5:4b`"; `agent.py:1114` modele `ollama pull gemma3:12b` önermesini söylüyor.
6. Çekirdek koruması kodla yok: asistanın kendi kodunu değiştirememesi yalnızca çalışma klasörü yol kısıtıyla.

### 9.4 Diğer uyumsuzluklar

- Adlandırma: K kuralı 10 Türkçe; mevcut modüllerin hepsi İngilizce (SORULAR'daki karar: yalnızca yeni kod Türkçe).
- `/kontrol` 1 `python -m pytest` (`.venv`, 21 atlanan) ile CLAUDE.md'nin "kurulu programın Python'u, atlanan 0" kuralı
  farklı sonuç verir; sürücü (`otomatik.py`) de `sys.executable` ile pytest koşuyor.
- `requirements.txt`'de `playwright` (tarayıcı motoru) zorunlu bağımlılık; MIMARI §11.7'ye göre isteğe bağlı olmalı
  (`browser.py` onu yalnızca fonksiyon içinde yüklüyor, içe aktarma zamanında değil).
- `CLAUDE.md` 192 satır (Aşama 0 sınırı 150; SORULAR'da açık).

## 10. K1 için öneri sırası

1. Önce `testler/test_cekirdek_ayrimi.py` + boş `asistan/cekirdek/__init__.py`; `.cafer/k0_qtsiz.py`'deki "Qt yasakla,
   içe aktar" yöntemi grep'ten güçlü (dolaylı içe aktarmayı da yakalar).
2. `dictation.py`'yi böl: Qt'siz kısım (model indirme, temizleme, sunucu istemcisi) çekirdekte, ses kaydı `gui/`'de.
3. `inspect_output`'taki PDF/SVG çizimini arayüz tarafına ya da isteğe bağlı yeteneğe al; `problem_report`'taki
   sürüm okumasını `importlib.metadata`'ya çevir.
4. Sağlayıcı arayüzü: `agent.py`'deki dört dalı `saglayici/` altına çıkar, `Agent` onları çağırsın; `test_baglam`,
   `test_bulut_baglam`, `test_devretme` davranışı korur.
5. `ayar.py` `ayarlar.json`'u okumaya/yazmaya devam etsin; `ayar.toml` + `CAFER_*` üstüne katman olsun (biçim değişikliği
   geri alınması zor → onay gerekir).
6. Eski yollar: `asistan/<eski>.py` yeni yeri yeniden dışa aktarsın (uyarıyla); `gui/` ve `cloud_server` bozulmasın.
7. `gui/worker.py`'deki `Agent`/`Manager` kurulumunu çekirdekte tek bir "isteği çalıştır" işlevine indir.
