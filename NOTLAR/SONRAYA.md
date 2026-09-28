# Sonraya

- **Flatpak / Flathub:** AppImage'a ek dağıtım. Runtime `org.kde.Platform` (PySide6 hazır gelir), `org.kde.Sdk`; manifest
  `io.github.kaan4kbulut.YeniNesilCafer.yml` (python3 + pip bağımlılıkları çevrimdışı wheel'lerden, `--share=network`,
  `--filesystem=home` çünkü çalışma klasörü ve Ollama soketi; Ollama Flatpak içinden çalıştırılamaz → sistemdeki
  `ollama serve`'e `--socket` / host erişimi ya da `flatpak-spawn --host`). Flathub başvurusu ayrı iş (metadata, appstream).
