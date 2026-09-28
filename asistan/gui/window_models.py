"""Ana pencere: model menüleri (Online / Offline, baloncuklar), bağlantılar, varsayılan ve otomatik model seçimi."""

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QMenu, QMessageBox, QPushButton, QWidget, QWidgetAction,
)

from .. import cards, catalog, cli_agents, roster, specialists, sysinfo
from ..cekirdek import modeller
from ..config import CLAUDE_MODELS

from .sidebar import run_in_background
from .theme import C


_NOT_CHAT = ("embed", "tts", "image", "audio", "whisper", "dall-e", "moderation", "realtime", "transcribe", "imagen",
             "veo", "aqa", "learnlm")

_CODE_HINTS = tuple(modeller.deger("aileler.kod_menusu"))  # ayar/modeller.json


def _upper_tr(text: str) -> str:
    """Türkçe büyük harf: i → İ, ı → I."""
    return text.replace("i", "İ").replace("ı", "I").upper()


def _models_for_menu(models: list[str], code: bool) -> list[str]:
    """Sohbet menüsünde kod modelleri (codex, coder…) yok; kod menüsünde yalnız kodda iyi olanlar."""
    usable = [m for m in models if not any(x in m for x in _NOT_CHAT)]
    if code:
        picked = [m for m in usable if any(h in m for h in _CODE_HINTS)]
    else:
        picked = [m for m in usable if not any(h in m for h in ("codex", "coder", "codestral", "devstral"))]
    return (picked or usable)[:15]


class ModelsMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    def run_setup(self):
        """İlk kurulum sihirbazı: sistem taraması, Ollama, önerilen yerel modeller."""
        from .setup_wizard import SetupWizard

        SetupWizard(self.settings, self).exec()
        self._reload_models()
        self._update_workspace_label()
        self.right.models.refresh()
        if not self.worker:
            self.new_conversation()

    def _set_active_auto(self):
        """Tam otomatik: sohbet varsayılanları (Online, Offline) bırakılır; Kod yazıcının Kod varsayılanı kalır."""
        self.settings.active_kind = ""
        self.settings.defaults.pop("online", None)
        self.settings.defaults.pop("offline", None)
        self._set_auto_model(True)

    def _fill_model_menu(self, menu: QMenu, kind: str):
        """Üst çubuk: Online (bulut) · Offline (yerel). Bugünün en iyi 10'u + uzmanlığa göre en iyi 10'lar.

        Sıralamalar her gün güncellenir: bulutta LMArena (kullanıcı oyları) + OpenRouter (fiyat), yerelde Ollama
        kütüphanesi + sistem taraması. Bir modele tıklamak o işin varsayılanı yapar (bağlı değilse bağlanır)."""
        from .. import model_updates

        menu.clear()
        s = self.settings
        live = model_updates.load()
        if model_updates.stale():  # liste yok ya da eski biçimde: arka planda yenile, menü sonra dolar
            self._daily_model_update()
            if not (live or {}).get("arena"):
                menu.addAction("güncel liste indiriliyor… birkaç saniye sonra menüyü yeniden aç").setEnabled(False)
        prio = menu.addAction("Bulutu öncelikli kullan — en güçlü, ücretli olabilir" if kind == "online"
                              else "Yereli öncelikli kullan — ücretsiz, bilgisayarında")
        prio.setCheckable(True)
        prio.setChecked((s.model_policy == "guclu") == (kind == "online"))
        prio.triggered.connect(lambda: self._set_policy("guclu" if kind == "online" else "yerel"))
        auto = menu.addAction(f"otomatik — {self._auto_choice(kind)}")
        auto.setCheckable(True)
        # her menünün "otomatik"i kendi kategorisi: Online → bugünün en iyi bulut modeli, Offline → yerel otomatik
        cloud_in_use = (self.route[0] if getattr(self, "route", None) else self.provider) != "ollama"
        if kind == "online":
            auto.setChecked(s.model_policy == "guclu" and cloud_in_use and not s.extra.get("uncensored"))
            auto.triggered.connect(lambda: self._set_policy("guclu"))
        else:
            auto.setChecked(s.auto_model and not s.active_kind and not cloud_in_use and not s.extra.get("uncensored"))
            auto.triggered.connect(lambda: self._set_policy("yerel"))
        self._model_chips(menu, kind)  # kurulu / bağlı modeller: listelerde kaybolmasın
        if kind == "online":
            self._fill_online(menu, live)
        else:
            self._fill_offline(menu, live)
        menu.addSeparator()
        age = model_updates.age_hours()
        source = "LMArena + OpenRouter" if kind == "online" else "Ollama kütüphanesi + sistemin"
        menu.addAction(f"liste {('az önce' if age is not None and age < 1 else f'{age:.0f} saat önce') if age is not None else 'henüz'}"
                       f" güncellendi · {source}").setEnabled(False)
        menu.addAction("Model önerileri — ayrıntılı, ücretli ve ücretsiz…", self.open_advisor)

    CHIP_COLUMNS = 3

    def _model_chips(self, menu: QMenu, kind: str):
        """Menünün başında baloncuklar: Offline'da kurulu yerel modeller, Online'da bağlı bulut modelleri.
        Seçili olan dolu, araç kullanamayan kırmızı çerçeveli, sansürsüz 🔓; üstüne gelince model kartı."""
        from .. import model_updates

        live = model_updates.load()
        items = []  # (etiket, ipucu, değer, varsayılan türü, çerçeve rengi)
        if kind == "offline":
            for c in sorted((c for c in roster.candidates(self.settings) if c.local), key=lambda c: -c.score):
                card = cards.card(c.model)
                tip = cards.describe(card) if card else "henüz sınanmadı (Yardım → Model kartları)"
                free = model_updates.is_uncensored(c.model)
                color = C["error"] if "tools" not in c.caps else C["frame"]
                tags = [t for t in model_updates.local_tags(c.model, 0, live, c.caps) if t != "araç"]
                level = card.get("tools") if card else (2 if "tools" in c.caps else 0)
                tags.insert(0 if not free else 1, {2: "araç", 1: "araç zayıf"}.get(level, "sadece sohbet"))
                label = ("🔓 " if free else "") + c.model + "\n" + model_updates.hashtags(tags)
                items.append((label, tip, f"ollama|{c.model}", "offline", color))
        else:
            for cli in cli_agents.available_agents():
                items.append((cli.title, f"{cli.account} · kod ve genel işler", f"{cli.provider}|{cli.default}",
                              "code", C["frame"]))
            for c in roster.candidates(self.settings):
                if not c.local:
                    items.append((c.model, f"{self._company(c.provider)} · bağlı", f"{c.provider}|{c.model}", "online",
                                  C["frame"]))
        title = "kurulu modeller" if kind == "offline" else "bağlı modeller"
        empty = ("yerel model yok — Ollama çalışıyor mu?" if kind == "offline"
                 else "bulut bağlantısı yok — aşağıdan bir firmaya bağlan")
        self._chip_box(menu, title, [(label, tip, color, self._in_use(target, value),
                                      lambda t=target, v=value: self._set_default_model(t, v))
                                     for label, tip, value, target, color in items], empty)

    def _chip_box(self, menu: QMenu, title: str, items: list, empty: str = ""):
        """Menünün başına baloncuk kutusu. items: (etiket, ipucu, çerçeve rengi, seçili mi, tıklanınca | None)."""
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setSpacing(6)
        head = QLabel(_upper_tr(title) + f"  ·  {len(items)}")
        head.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        grid.addWidget(head, 0, 0, 1, self.CHIP_COLUMNS)
        if not items and empty:
            note = QLabel(empty)
            note.setStyleSheet(f"color: {C['muted']};")
            grid.addWidget(note, 1, 0, 1, self.CHIP_COLUMNS)
        for n, (label, tip, color, active, on_click) in enumerate(items):
            chip = QPushButton(label, toolTip=tip)
            chip.setCursor(Qt.PointingHandCursor if on_click else Qt.ArrowCursor)
            chip.setStyleSheet(
                f"QPushButton {{ border: 1px solid {C['accent'] if active else color}; border-radius: 11px; "
                f"padding: 3px 10px; background: {C['accent'] if active else C['surface']}; "
                f"color: {C['on_accent'] if active else C['text']}; text-align: left; }}"
                f"QPushButton:hover {{ border-color: {C['accent']}; }}")
            if on_click:
                def pick(_=False, fn=on_click):
                    while QApplication.activePopupWidget():  # alt menüden seçilince bütün menü zinciri kapansın
                        QApplication.activePopupWidget().close()
                    fn()
                chip.clicked.connect(pick)
            grid.addWidget(chip, 1 + n // self.CHIP_COLUMNS, n % self.CHIP_COLUMNS)
        action = QWidgetAction(menu)
        action.setDefaultWidget(box)
        menu.addAction(action)
        menu.addSeparator()

    def _local_chips(self, menu: QMenu, models: list[str], target: str | None, live):
        """Alt menünün başında o alandaki kurulu yerel modeller (etiketleri #, seçili olan dolu)."""
        from .. import model_updates

        caps = {c.model: c.caps for c in roster.candidates(self.settings) if c.local}
        items = []
        for m in dict.fromkeys(models):
            card = cards.card(m)
            tags = model_updates.local_tags(m, 0, live, caps.get(m))
            if m in caps and "tools" not in caps[m]:
                tags.append("sadece sohbet")
            value = f"ollama|{m}"
            items.append((("🔓 " if model_updates.is_uncensored(m) else "") + m + "\n" + model_updates.hashtags(tags),
                          cards.describe(card) if card else "henüz sınanmadı",
                          C["error"] if m in caps and "tools" not in caps[m] else C["frame"],
                          bool(target) and self._in_use(target, value),
                          (lambda t=target, v=value: self._pick_for(t, v)) if target else None))
        self._chip_box(menu, "bu alanda kurulu", items, "bu alanda kurulu model yok — aşağıdan indirebilirsin")

    def _cloud_chips(self, menu: QMenu, rows: list[dict], target: str):
        """Alt menünün başında listedeki kullanılabilir (bağlı) bulut modelleri."""
        from .. import model_updates

        items = []
        for agent in cli_agents.available_agents() if target == "code" else []:  # abonelik: kod listesinde hep hazır
            chosen = self.settings.defaults.get("code", "")
            cli = chosen if chosen.startswith(agent.provider + "|") else f"{agent.provider}|{agent.default}"
            items.append((f"{agent.title}\n#kod #araç #abonelik", f"{agent.account}, anahtar gerekmez", C["frame"],
                          chosen == cli, lambda v=cli: self._set_default_model("code", v)))
        for r in rows:
            value = self._cloud_value(r)
            if not value:
                continue
            tags = model_updates.cloud_tags(r, model_updates.load())
            items.append((value.split("|", 1)[1] + ("\n" + model_updates.hashtags(tags) if tags else ""),
                          r.get("org", ""), C["frame"], self._in_use(target, value),
                          lambda t=target, v=value: self._pick_for(t, v)))
        self._chip_box(menu, "bu listede bağlı", items, "bu listeden bağlı model yok — tıklayınca bağlanırsın")

    @staticmethod
    def _menu_title(target: QMenu, text: str):
        target.addSeparator()
        target.addAction(_upper_tr(text)).setEnabled(False)  # addSection bu temada başlığı göstermiyor

    # ---- Online: bulut modelleri
    def _fill_online(self, menu: QMenu, live):
        from .. import model_updates

        top = model_updates.arena_ranked(live, "text", 10)
        menu.addSeparator()
        best = menu.addMenu("Bugünün en iyi 10'u  ·  genel")  # alt menü: ana menü ekranı kaplamasın
        if top:
            self._cloud_chips(best, top, "online")
        if not top:
            best.addAction("liste henüz alınmadı — internet gerekli").setEnabled(False)
        for r in top:
            self._cloud_action(best, r, "online")
        self._menu_title(menu, "uzmanlığa göre en iyi 10")
        for cat, (title, note) in model_updates.ARENA.items():
            if cat == "text":
                continue
            sub = menu.addMenu(f"{title}  ·  {note}")
            target = {"webdev": "code", "vision": "vision"}.get(cat, "online")
            agents = cli_agents.available_agents() if cat == "webdev" else []
            for agent in agents:
                chosen = self.settings.defaults.get("code", "")
                cli = chosen if chosen.startswith(agent.provider + "|") else f"{agent.provider}|{agent.default}"
                a = sub.addAction(f"{agent.title} — {agent.account}, anahtar gerekmez")
                a.setCheckable(True)
                a.setChecked(chosen == cli)
                a.triggered.connect(lambda _=False, v=cli: self._set_default_model("code", v))
            if agents:
                sub.addSeparator()
            rows = model_updates.arena_ranked(live, cat, 10)
            if rows:
                self._cloud_chips(sub, rows, target)
            for r in rows:
                self._cloud_action(sub, r, target)
        free = menu.addMenu("Ücretsiz  ·  kart gerekmeyen seçenekler")
        for name, note, pid in model_updates.FREE_TIERS:
            free.addAction(f"{name}  ·  {note}", lambda p=pid: self._connect_provider(catalog.BY_ID[p], "online", ""))
        today = ((live or {}).get("cloud") or {}).get("free") or []
        if today:
            free.addSeparator()
            free.addAction("OPENROUTER'DA BUGÜN ÜCRETSİZ").setEnabled(False)
            for r in today[:10]:
                self._cloud_action(free, {"name": r["id"].split("/")[-1], "org": r["id"].split("/")[0],
                                          "rank": 0, "open": True, "or": r}, "online", via_openrouter=True)
        self._menu_title(menu, "firmalar")
        firms = menu.addMenu("Firmaya göre seç — bağlı olanlar ve bağlan")
        chosen = self.settings.defaults.get("online", "")
        for prov in catalog.PROVIDERS:
            linked = self._provider_conn(prov)[0]
            if linked:
                firms.addSeparator()
                firms.addAction(prov.name.upper() + "  ·  bağlı").setEnabled(False)
            self._provider_submenu(firms, prov, "online", chosen, inline=linked)
        menu.addAction("Başka sağlayıcı ekle…", lambda: self._add_connection(""))

    def _cloud_value(self, r: dict, via_openrouter: bool = False) -> str:
        """LMArena satırını seçilebilir "sağlayıcı|model" değerine çevirir; bağlantı yoksa ""."""
        match = r.get("or") or {}
        or_id = match.get("id", "")
        direct = {"anthropic": "anthropic", "openai": "openai", "google": "google", "xai": "xai",
                  "x-ai": "xai"}.get(r.get("org", ""))
        if direct and or_id and not via_openrouter:
            linked, key, _ = self._provider_conn(catalog.BY_ID[direct])
            if linked:
                model = or_id.split("/", 1)[1]
                return f"{key}|{model.replace('.', '-') if direct == 'anthropic' else model}"
        conn = next((c for c in self.connections if c.kind == "llm" and c.enabled and "openrouter.ai" in c.base_url),
                    None)
        return f"api:{conn.id}|{or_id}" if conn and or_id else ""

    def _cloud_action(self, target: QMenu, r: dict, kind: str, via_openrouter: bool = False):
        match = r.get("or") or {}
        price = ""
        if match:
            price = "ücretsiz" if not (match.get("in") or match.get("out")) else f"${match['in']:g}/${match['out']:g}"
        from .. import model_updates

        rank = f"{r['rank']}. " if r.get("rank") else ""
        shown = match.get("id", "").split("/")[-1].replace(":free", "") or r["name"]  # firmanın gerçek adı
        tags = model_updates.cloud_tags(r, model_updates.load())
        bits = [b for b in (r.get("org", ""), price) if b]
        a = target.addAction(f"{rank}{shown}    {' · '.join(bits)}    {model_updates.hashtags(tags)}" if tags
                             else f"{rank}{shown}    {' · '.join(bits)}")
        value = self._cloud_value(r, via_openrouter)
        if value:
            a.setCheckable(True)
            a.setChecked(self._in_use(kind, value))
            a.triggered.connect(lambda _=False, v=value: self._pick_for(kind, v))
        elif not match:
            a.setEnabled(False)
            a.setToolTip("Bu ad yalnızca sohbet sitelerinde var; API'de bulunamadı.")
        else:  # bağlı değil: önce firmaya (yoksa OpenRouter'a) bağlan, sonra seç
            org = {"x-ai": "xai"}.get(r.get("org", ""), r.get("org", ""))
            pid = org if org in catalog.BY_ID and not via_openrouter else "openrouter"
            a.setToolTip("Bağlı değil — tıklayınca bağlanma penceresi açılır")
            a.triggered.connect(lambda _=False, p=pid, row=r: self._connect_then_pick(p, row, kind, via_openrouter))

    def _connect_then_pick(self, provider_id: str, row: dict, kind: str, via_openrouter: bool):
        self._connect_provider(catalog.BY_ID[provider_id], "online", "")
        value = self._cloud_value(row, via_openrouter)
        if value:
            self._pick_for(kind, value)

    def _pick_for(self, kind: str, value: str):
        """Uzmanlığa göre seçim: görme ve düşünme uzman model olur; diğerleri o menünün varsayılanı."""
        if kind == "uncensored":  # Sansürsüz uzmanlığından kurulu bir model: mod o modelle açılır
            self._toggle_uncensored(True, value.split("|", 1)[1])
            return
        if kind in ("vision", "reasoning"):
            self.settings.specialists[kind] = value
            self.settings.save()
            self.agent_panel.refresh_experts()
            self._notify(f"{'görsel' if kind == 'vision' else 'düşünme'} uzmanı: {value.split('|', 1)[1]}")
        else:
            self._set_default_model(kind, value)

    # ---- Offline: yerel modeller
    def _system_info(self, arka_plan: bool = True):
        """Sistem taraması; sonuç 60 sn saklanır. K12-D3: tarama (`ensure_ollama` 15 sn bekleme, model başına
        `/api/show`) ARKA PLANDA yapılır; elde sonuç yoksa None döner (menü "taranıyor…" gösterir), eskiyse eski sonuç
        döner ve arkada yenilenir. `arka_plan=False`: eşzamanlı (arayüz dışı çağıranlar)."""
        import time as _time

        cached = getattr(self, "_sysinfo_cache", None)
        eski = cached is None or _time.time() - cached[0] > 60
        if eski and not arka_plan:
            cached = self._sysinfo_cache = (_time.time(), sysinfo.scan(self.settings.ollama_url))
        elif eski and not getattr(self, "_sysinfo_taraniyor", False):
            self._sysinfo_taraniyor = True
            url = self.settings.ollama_url

            def bitti(info, error):
                self._sysinfo_taraniyor = False
                if error is None and info is not None:
                    self._sysinfo_cache = (_time.time(), info)

            run_in_background(lambda: sysinfo.scan(url), bitti, self)
        return cached[1] if cached else None

    def _fill_offline(self, menu: QMenu, live):
        from .. import model_updates

        info = self._system_info()
        if info is None:  # K12-D3: ilk tarama arka planda sürüyor
            menu.addSeparator()
            menu.addAction("sistem taranıyor… (menüyü birazdan yeniden aç)").setEnabled(False)
            return
        installed = set(info.ollama_models)
        menu.addSeparator()
        best = menu.addMenu("Bugünün en iyi 10'u  ·  sistemine göre")  # alt menü: ana menü ekranı kaplamasın
        ranked = sysinfo.local_ranked(info, live)
        self._local_chips(best, [r["model"] for r in ranked if r["model"] in installed], "offline", live)
        for n, r in enumerate(ranked, 1):
            self._local_action(best, r, "offline", installed, n)
        self._menu_title(menu, "uzmanlığa göre en iyi 10")
        specs = [("chat", "offline"), ("code", "code"), ("reasoning", "reasoning"), ("vision", "vision"),
                 ("ocr", "vision"), ("embedding", None)]
        titles = {**model_updates.CAPABILITIES, **model_updates.LOCAL_EXTRA}
        for cap, target in specs:
            title, note = titles[cap]
            sub = menu.addMenu(f"{title}  ·  {note}")
            rows = sysinfo.local_ranked(info, live, cap, 10)
            # bu alandaki kurulu modeller: listede olsun olmasın, yetenekleri uyanlar baloncuk olarak en üstte
            self._local_chips(sub, [r["model"] for r in rows if r["model"] in installed]
                              + self._installed_for(cap, info), target, live)
            if cap == "embedding":
                sub.addAction("hafızada anlamsal arama için (Aşama 4)").setEnabled(False)
            if not rows:
                sub.addAction("liste henüz alınmadı").setEnabled(False)
            for n, r in enumerate(rows, 1):
                self._local_action(sub, r, target, installed, n)
        # sansürsüz: diğerleri gibi bir uzmanlık; yalnızca kullanıcı seçerse kullanılır (otomatik seçim almaz)
        sub = menu.addMenu("Sansürsüz  ·  filtresiz; 🔓 modda asistan ve ekip bunlarla çalışır")
        budget = info.vram_gb * 0.92 if info.vram_gb else info.ram_gb * 0.5
        # her gün güncellenen liste (yoksa programdaki sabit liste); sistemine uyanlar önce, sonra popülerlik
        free = sorted(model_updates.uncensored_models(live), key=lambda u: (u["size"] > budget, -u.get("score", 0)))
        self._local_chips(sub, [m for m in info.ollama_models if model_updates.is_uncensored(m)], "uncensored", live)
        for n, u in enumerate(free[:10], 1):
            self._local_action(sub, {"model": u["model"], "size": u["size"], "fits": u["size"] <= budget},
                               "uncensored", installed, n)
        # kurulu modeller tek bir alt menüde: menü ekranı kaplamasın
        local = [c for c in roster.candidates(self.settings, refresh=False) if c.local]  # K12-D3: menüde N×/api/show yok
        menu.addSeparator()
        mine = menu.addMenu(f"Kurulu modeller  ·  {len(local)}")
        for c in sorted(local, key=lambda c: -c.score):
            tags = model_updates.local_tags(c.model, 0, live, c.caps)
            a = mine.addAction(f"{c.model}    " + model_updates.hashtags(
                tags + ([] if "tools" in c.caps else ["sadece sohbet"])))
            a.setCheckable(True)
            a.setChecked(self._in_use("offline", f"ollama|{c.model}"))
            a.triggered.connect(lambda _=False, v=f"ollama|{c.model}": self._set_default_model("offline", v))
        if not local:
            mine.addAction("yerel model yok — Ollama çalışıyor mu?").setEnabled(False)
        menu.addAction("Modelleri yönet…", lambda: self._show_tab(self.right.models))

    def _installed_for(self, cap: str, info) -> list[str]:
        """Bu uzmanlığa uyan kurulu modeller (sıralama listesinde olmasalar da)."""
        from .. import model_updates

        local = {c.model: c.caps for c in roster.candidates(self.settings) if c.local}
        if cap == "embedding":
            return [m for m in info.ollama_models if "embed" in m]
        if cap == "ocr":
            return [m for m in local if "ocr" in m]
        need = {"code": "code", "reasoning": "thinking", "vision": "vision"}.get(cap)
        pool = [m for m, caps in sorted(local.items(), key=lambda kv: -len(kv[1]))
                if not model_updates.is_uncensored(m)]
        if cap == "code":
            return [m for m in pool if "code" in local[m] or "coder" in m]
        return [m for m in pool if need is None or need in local[m]]

    def _local_action(self, target: QMenu, r: dict, kind: str | None, installed: set, n: int):
        from .. import model_updates

        have = r["model"] in installed
        state = "kurulu ✓" if have else ("sistemine uygun · indir" if r["fits"] else "sistemine ağır · yavaş")
        tags = model_updates.local_tags(r["model"], r["size"], model_updates.load())
        a = target.addAction(f"{'● ' if have else ''}{n}. {r['model']}    {r['size']:.1f} GB · {state}    "
                             f"{model_updates.hashtags(tags)}")  # ●: kurulu, listede göze çarpsın
        value = f"ollama|{r['model']}"
        if have and kind:
            a.setCheckable(True)
            a.setChecked(self._in_use(kind, value))
            a.triggered.connect(lambda _=False, v=value: self._pick_for(kind, v))
        elif not have:
            a.triggered.connect(lambda _=False, m=r["model"], sz=r["size"], k=kind: self._download_model(m, sz, k))

    def _download_model(self, model: str, size: float, kind: str | None):
        """Menüden yerel model indirme: onay, arka planda indir, bitince o uzmanlığa ata."""
        if QMessageBox.question(self, "Model indir", f"{model} indirilsin mi? ({size:.1f} GB)") != QMessageBox.Yes:
            return
        self._notify(f"{model} indiriliyor…", 600000)
        url = self.settings.ollama_url

        def work():
            sysinfo.pull(model, url, lambda pct, status: pct >= 0 and pct % 10 == 0 and
                         self.pull_progress.emit(f"{model} indiriliyor… %{pct}"), lambda: False)

        def done(_res, err):
            if err:
                self._notify(f"{model} indirilemedi: {err}", 15000)
                return
            self._notify(f"{model} kuruldu ✓", 10000)
            QTimer.singleShot(5000, self._exam_models)  # yeni modelin kartı çıkarılsın
            self._sysinfo_cache = None
            self.right.models.refresh()
            if kind:
                self._pick_for(kind, f"ollama|{model}")

        run_in_background(work, done, self)

    def _provider_conn(self, prov) -> tuple[bool, str, list[str]]:
        """(bağlı mı, sağlayıcı anahtarı, hesaptaki modeller)"""
        if prov.id == "anthropic":
            return specialists._claude_available(), "claude", list(CLAUDE_MODELS)
        # anahtarsız / anahtarı reddedilmiş bağlantı "bağlı" sayılmaz: menüde bağlan ve 🔑 seçenekleri görünür
        conn = next((c for c in self.connections if c.kind == "llm" and c.usable and prov.host in c.base_url), None)
        return conn is not None, (f"api:{conn.id}" if conn else ""), (list(conn.models) if conn else [])

    def _provider_submenu(self, menu: QMenu, prov, kind: str, chosen: str, inline: bool = False):
        """Firmanın modelleri: bağlıysa doğrudan menüde (inline), değilse alt menüde bağlan / anahtar al ile."""
        code = kind == "code"
        connected, provider_key, available = self._provider_conn(prov)
        sub = menu if inline else menu.addMenu(f"{prov.name}" + (f"  ·  {prov.note}" if prov.note else ""))
        featured = prov.code if code else prov.chat
        for model, note in featured:
            missing = connected and available and model not in available
            a = sub.addAction(f"{model}    {note}" + ("  · hesabında yok" if missing else ""))
            if missing:
                a.setEnabled(False)
                continue
            if connected:
                value = f"{provider_key}|{model}"
                a.setCheckable(True)
                a.setChecked(self._in_use(kind, value))
                a.triggered.connect(lambda _=False, v=value: self._set_default_model(kind, v))
            else:  # önce bağlan; bağlantı kurulunca bu model seçilir
                a.triggered.connect(lambda _=False, m=model: self._connect_provider(prov, kind, m))
        if connected and prov.id != "anthropic":
            rest = [m for m in _models_for_menu(available, code) if m not in {m for m, _ in featured}]
            if rest:
                more = sub.addMenu("   hesabındaki diğer modeller")
                for m in rest[:25]:
                    a = more.addAction(m)
                    a.setCheckable(True)
                    a.setChecked(self._in_use(kind, f"{provider_key}|{m}"))
                    a.triggered.connect(lambda _=False, v=f"{provider_key}|{m}": self._set_default_model(kind, v))
        if connected:
            if not inline:
                sub.addSeparator()
            self._account_actions(sub, prov, kind)  # ör. OpenAI anahtarla bağlıyken ChatGPT aboneliğiyle Codex
            sub.addAction("   bağlantıyı düzenle…", lambda: self._connect_provider(prov, kind, "", edit=True))
            return
        sub.addSeparator()
        self._account_actions(sub, prov, kind)
        sub.addAction("bağlan — API anahtarını gir…", lambda: self._connect_provider(prov, kind, ""))
        sub.addAction("anahtar al — web sayfasını aç", lambda: QDesktopServices.openUrl(QUrl(prov.key_url)))

    def _connect_provider(self, prov, kind: str, model: str, edit: bool = False):
        """Firmaya bağlanır (ya da bağlantıyı düzenler); model verildiyse bağlantı kurulunca onu seçer."""
        self.side_tabs.button(3).click()
        if prov.id == "anthropic":
            self.api_panel.add_claude()
            ok, value = specialists._claude_available(), f"claude|{model}"
        else:
            conn = next((c for c in self.connections if prov.host in c.base_url), None)
            if conn:  # zaten var (anahtarsız olsa da): yenisini açma, onu düzenle
                self.api_panel.edit(conn.id)
            else:
                self.api_panel._add(prov.preset)
            conn = next((c for c in self.connections if c.kind == "llm" and prov.host in c.base_url), None)
            ok, value = conn is not None, (f"api:{conn.id}|{model}" if conn else "")
        if ok and model:
            self._set_default_model(kind, value)

    def _add_connection(self, preset: str):
        self.side_tabs.button(3).click()  # API'ler sekmesi: eklenen bağlantı orada görünsün
        self.api_panel._add(preset)

    def _add_claude_key(self):
        self.side_tabs.button(3).click()
        self.api_panel.add_claude()

    def _auto_choice(self, kind: str) -> str:
        """Menüde "otomatik"in yanında görünen: şu an programın seçeceği model."""
        s = self.settings
        if kind == "code":
            found = roster.pick_for(s, next((p for p in self.profiles if p.id == "kod"), None))
            if found and found.local:
                return f"şimdilik yerel {found.model} (bulut kod modeli seçilmedi)"
        else:
            pool = [c for c in roster.candidates(s) if c.local == (kind == "offline") and "tools" in c.caps]
            found = max(pool, key=lambda c: c.score) if pool else None
            if found is None and kind == "online":
                return self._best_cloud()[2] or "bulut bağlantısı yok"
        return found.model if found else "yok"

    def _in_use(self, kind: str, value: str) -> bool:
        """Menülerdeki ✓: alttaki ve üstteki menüler aynı kaynaktan, o an gerçekten kullanılan modeli işaretler."""
        s = self.settings
        if kind in ("vision", "reasoning"):
            return value == s.specialists.get(kind, "")
        free = self._free_model()
        if free:  # sansürsüz modda çalışan model bu (pilde küçük olan)
            return kind in ("offline", "uncensored") and value == f"ollama|{free}"
        if kind in ("online", "offline"):
            return s.active_kind == kind and s.defaults.get(kind) == value
        return kind != "uncensored" and s.defaults.get(kind) == value

    def _set_default_model(self, kind: str, value: str):
        s = self.settings
        if kind in ("online", "offline") and not self.worker:
            # sansürsüz model seçildiyse sansürsüz mod onunla açılır; başka bir model ya da otomatik seçilirse kapanır
            from .. import model_updates

            provider, _, name = value.partition("|")
            if provider == "ollama" and model_updates.is_uncensored(name):
                self._toggle_uncensored(True, name)
                return
            if s.extra.get("uncensored"):
                self._toggle_uncensored(False)
            if not value:  # üstteki "otomatik" alttakiyle aynı: tam otomatik
                self._set_active_auto()
                return
        if value:
            s.defaults[kind] = value
            s.active_kind = kind  # seçilen alan etkin olur: alttaki model hemen ona geçer
            if kind in ("online", "offline"):
                s.model_policy = "guclu" if kind == "online" else "yerel"
        else:
            s.defaults.pop(kind, None)
            if s.active_kind == kind:
                s.active_kind = ""
        if self.worker:
            s.auto_model = True
            s.save()
            self._notify("seçim kaydedildi; asistan şu anki işi bitirince geçerli olur")
            return
        # sürmekte olan sohbetin mesaj biçimi yeni firmaya uymuyorsa yeni sohbet aç
        found = roster.pick_for(s, self.profile)
        if found and self.conv and self.conv.messages:
            same = found.provider == self.conv.provider or (
                self.conv.provider == "ollama" and cli_agents.is_cli(found.provider))
            if not same:
                profile = self.profile
                self.new_conversation(profile.id if profile and not profile.provider else "")
                self._notify(f"{self._company(found.provider)} modeline geçildi — yeni sohbet açıldı")
        self._set_auto_model(True)  # varsayılanlar otomatik seçimin parçası
        names = {"online": "bulut", "code": "kod", "offline": "yerel"}
        text = f"varsayılan {names[kind]} modeli: {value.split('|', 1)[1] if value else 'otomatik'}"
        found = roster.default(self.settings, kind)
        if found and "tools" not in found.caps:
            text += " — araç kullanamadığı için görev gereken işler otomatik olarak başka modele gider"
        self._notify(text, 12000)

    def _best_cloud(self) -> tuple[str, str, str]:
        """Bugünün sıralamasında (LMArena genel) kullanabileceğin en iyi bulut modeli: (tür, değer, görünen ad).
        Bağlı bir firma / OpenRouter yoksa Claude aboneliği (Claude Code); o da yoksa boş."""
        from .. import model_updates

        for r in model_updates.arena_ranked(model_updates.load(), "text", 60):
            value = self._cloud_value(r)
            if value:
                return "online", value, value.split("|", 1)[1]
        if specialists._claude_available():
            return "online", f"claude|{CLAUDE_MODELS[0]}", CLAUDE_MODELS[0]
        for agent in cli_agents.available_agents():
            return "code", f"{agent.provider}|{agent.default}", agent.title.lower()
        return "", "", ""

    def _best_local(self) -> tuple[str, str]:
        """Sistemin en iyi saydığı yerel model: (değer, ad). Model kartına göre araç kullanabilen, sansürsüz
        olmayanlar arasından en yüksek puanlı (puan: boyut, kuşak, bu bilgisayardaki sınav ve pil durumu)."""
        from .. import model_updates

        pool = [c for c in roster.candidates(self.settings, refresh=True)
                if c.local and "tools" in c.caps and not model_updates.is_uncensored(c.model)]
        if not pool:
            return "", ""
        best = max(pool, key=lambda c: ((cards.card(c.model) or {}).get("tools", 1), c.score))
        return f"ollama|{best.model}", best.model

    def _set_policy(self, policy: str):
        """Öncelik seçimi bir kategori seçimidir: sansürsüz mod kapanır. Bulut önceliğinde bugünün en iyi
        kullanılabilir bulut modeli seçilir (Online yanar); yerel öncelikte program yerel modeli otomatik seçer."""
        if self.settings.extra.get("uncensored") and not self.worker:
            self._toggle_uncensored(False)
        if policy == "guclu":
            kind, value, name = self._best_cloud()
            if value:
                self._set_default_model(kind, value)
                self.settings.model_policy = "guclu"
                self.settings.save()
                self._notify(f"öncelik: bulut — bugünün en iyi kullanılabilir modeli: {name}", 12000)
                return
            self._notify("Bağlı bir bulut modeli yok: Online → Bağlan menüsünden bir firmaya bağlan "
                         "(Gemini, Groq ve OpenRouter'ın ücretsiz seçenekleri var). Şimdilik yerel model sürüyor.", 15000)
        if policy == "yerel":
            value, name = self._best_local()
            if value:  # en iyi yerel modele hemen geçilir; işe göre otomatik seçim yine yerel modeller arasında
                self._set_default_model("offline", value)
                self.settings.model_policy = "yerel"
                self.settings.save()
                self._notify(f"öncelik: yerel — sistemin en iyi yerel modeli: {name}", 12000)
                return
        self.settings.model_policy = policy
        self.settings.active_kind = ""  # yerel model yoksa: program işe göre seçer
        self._set_auto_model(True)
        if policy == "yerel":
            self._notify("öncelik: yerel — araç kullanabilen yerel model bulunamadı; program işe göre seçer", 8000)

    def _center_model_tabs(self):
        bar, tabs = self.menuBar(), getattr(self, "model_tabs", None)
        if tabs is None:
            return
        # ortada; pencere darsa soldaki menülerin (Sohbet · Görünüm · Yardım) üstüne binmesin
        left = max((bar.actionGeometry(a).right() for a in bar.actions()), default=0) + 16
        self._fit_model_tabs(bar.width() - left - 8)
        tabs.move(max((bar.width() - tabs.width()) // 2, left), (bar.height() - tabs.height()) // 2)
        tabs.raise_()

    def _fit_model_tabs(self, room: int):
        """Pencere daralınca üst düğmeler taşmasın: önce anahtarlar yalnızca simge (🛡 🔓 🔋, ayrıntı ipucunda),
        yetmezse model düğmeleri yalnızca "Online ⌄" / "Offline ⌄" olur. Genişleyince tam yazıya döner."""
        switches = [b for b in (getattr(self, n, None) for n in ("guard_btn", "free_btn", "light_btn")) if b]
        kinds = list(getattr(self, "kind_tabs", {}).values())
        for b in switches + kinds:
            if b.text() != b.property("short"):  # metni güncelleme fonksiyonu değiştirdi: tam metin bu
                b.setProperty("full", b.text())
            b.setText(b.property("full") or b.text())
        steps = [(switches, lambda t: (t.split() or [t])[0]), (kinds, lambda t: t.split(" · ")[0].replace("  ⌄", "") + "  ⌄")]
        self.model_tabs.adjustSize()
        for group, short in steps:
            if self.model_tabs.width() <= room:
                break
            for b in group:
                b.setProperty("short", short(b.property("full") or b.text()))
                b.setText(b.property("short"))
            self.model_tabs.adjustSize()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.menuBar() and event.type() in (QEvent.Resize, QEvent.Show):
            self._center_model_tabs()
        return super().eventFilter(obj, event)

    def _set_auto_model(self, on: bool):
        self.settings.auto_model = on
        self.settings.save()
        if on and not self.worker:
            self._auto_route()
        self._update_header()
        self.agent_panel.refresh()

    def _auto_route(self):
        """Otomatik modda sıradaki mesaj için modeli seçer (sürmekte olan sohbette sağlayıcı değişmez)."""
        self.route = None
        if not self.settings.auto_model or (self.profile and self.profile.provider):
            return
        providers = None
        if self.conv and self.conv.messages:
            providers = {self.conv.provider}
            if self.conv.provider == "ollama":  # Claude Code / Codex / Gemini CLI düz metin geçmişle çalışır
                providers.update(cli_agents.AGENTS)
        found = roster.pick_for(self.settings, self.profile, providers)
        if found is not None and cli_agents.is_cli(found.provider):
            self.route = found.key  # sohbet sağlayıcısı değişmez; bu mesaj Claude Code'a gider
            self._update_header()
            return
        if found is None or found.key == (self.provider, self.model_box.currentText()):
            return
        old = self.settings.ollama_model
        self._set_provider_model(*found.key)
        self.settings.save()
        if found.provider == "ollama" and found.model != old:
            QTimer.singleShot(300, self._check_context)  # yeni modelin bağlamını ölç
        self._update_header()

    def _pick_model(self, provider: str, model: str):
        self.settings.auto_model = False  # elle seçildi: otomatik kapanır
        if provider != self.provider:
            self.settings.provider = provider
            if provider == "claude":
                self.settings.claude_model = model
            elif provider == "ollama":
                self.settings.ollama_model = model
            else:
                self.settings.api_models[provider[4:]] = model
            self.provider_box.setCurrentIndex(self.provider_box.findData(provider))
        self.model_box.setCurrentText(model)
