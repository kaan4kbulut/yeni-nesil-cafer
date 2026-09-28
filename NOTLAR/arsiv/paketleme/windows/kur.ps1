# YENİ NESİL CAFER — Windows kurulumu
# Tam paket: her şey içinde (taşınabilir Python ve kütüphaneleri, Ollama, temel model), internet gerekmez.
# İnternet paketi (GitHub'daki küçük dosya): Python, kütüphaneler, Ollama ve tarayıcı resmi kaynaklarından indirilir
# (asistan\bootstrap.py; sürümler sabit, SHA-256 doğrulamalı); modelleri ilk açılıştaki kurulum sihirbazı indirir.
# Programı %LOCALAPPDATA%\YeniNesilCafer'e kopyalar, masaüstü ve Başlat menüsü kısayolu oluşturur.
$ErrorActionPreference = "Stop"
$Kaynak = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "program"
$Hedef = Join-Path $env:LOCALAPPDATA "YeniNesilCafer"
$Eski = Join-Path $env:LOCALAPPDATA "YerelAsistan"  # 2.2'ye kadarki kurulum klasörü: yeni kurulumdan sonra silinir

function Calistir($exe, [string[]]$argv) {
    # harici program: çıktısı gizli, çıkış kodu döner. Windows PowerShell 5.1'de "Stop" modunda
    # programın stderr'e yazması (Ollama ilerlemesi gibi) hata sayılmasın diye geçici olarak "Continue"
    $onceki = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $exe @argv *> $null; return $LASTEXITCODE } finally { $ErrorActionPreference = $onceki }
}
function Yaz($metin) { Write-Host "  $metin" -ForegroundColor Yellow }
function Hata($metin) {
    Write-Host ""
    Write-Host "  $metin" -ForegroundColor Red
    Write-Host "  Bu pencerenin ekran görüntüsünü gönderirsen sorunu çözebiliriz." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  YENİ NESİL CAFER · kurulum" -ForegroundColor White
Write-Host ""

if (-not (Test-Path (Join-Path $Kaynak "main.py"))) {
    Hata "Kurulum dosyaları eksik. Zip dosyasını tamamen çıkarıp Kur.bat'ı çıkan klasörden çalıştır."
}
$Internet = -not (Test-Path (Join-Path $Kaynak "python\pythonw.exe"))  # küçük paket: Python ve gerisi indirilecek
$PyUrl = "@PY_URL_WINDOWS@"
$PySha = "@PY_SHA_WINDOWS@"

# eski kurulumdan açık kalan program ya da Ollama varsa dosyalar kilitli olur: kapat
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path.StartsWith($Hedef, "OrdinalIgnoreCase") -or
    $_.Path.StartsWith($Eski, "OrdinalIgnoreCase")) } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

Yaz "Program kopyalanıyor: $Hedef"
if (-not $Internet) {
    Yaz "(yaklaşık 4 GB, diskine göre 1-3 dakika sürebilir)"
    foreach ($eski in @(".venv", "python", "ollama")) {  # eski sürümün kalıntıları (tam paket yenilerini getirir)
        $yol = Join-Path $Hedef $eski
        if (Test-Path $yol) { Remove-Item $yol -Recurse -Force }
    }
}
New-Item -ItemType Directory -Force -Path $Hedef | Out-Null
robocopy $Kaynak $Hedef /E /NFL /NDL /NJH /NJS /NC /NS /NP /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { Hata "Dosyalar kopyalanamadı (robocopy kodu $LASTEXITCODE). Diskte yer var mı?" }

$pyw = Join-Path $Hedef "python\pythonw.exe"
$py = Join-Path $Hedef "python\python.exe"
$ollama = Join-Path $Hedef "ollama\ollama.exe"
$main = Join-Path $Hedef "main.py"

if ($Internet) {  # önce taşınabilir Python, sonra gerisini o indirir (kurulu olan yeniden inmez)
    $surum = Join-Path $Hedef "python\.surum"
    if (-not ((Test-Path $surum) -and ((Get-Content $surum -Raw).Trim() -eq $PyUrl))) {
        Yaz "Python indiriliyor (~25 MB)…"
        $klasor = Join-Path $Hedef "kurulum"
        New-Item -ItemType Directory -Force -Path $klasor | Out-Null
        $arsiv = Join-Path $klasor "python.tar.gz"
        $curl = Join-Path $env:SystemRoot "System32\curl.exe"  # Windows 10 (1803) ve 11'de hazır gelir
        if (Test-Path $curl) { & $curl -fL --retry 5 --retry-delay 3 -C - -o $arsiv $PyUrl }
        else { Invoke-WebRequest $PyUrl -OutFile $arsiv -UseBasicParsing }
        if (-not (Test-Path $arsiv) -or (Get-FileHash $arsiv -Algorithm SHA256).Hash.ToLower() -ne $PySha) {
            Remove-Item $arsiv -ErrorAction SilentlyContinue
            Hata "Python indirilemedi ya da doğrulanamadı. İnterneti denetleyip Kur.bat'ı yeniden çalıştır."
        }
        $eskiPy = Join-Path $Hedef "python"
        if (Test-Path $eskiPy) { Remove-Item $eskiPy -Recurse -Force }
        & (Join-Path $env:SystemRoot "System32\tar.exe") -xzf $arsiv -C $Hedef
        if (-not (Test-Path $py)) { Hata "Python açılamadı (tar.exe). Windows 10 (1803) ya da daha yeni bir sürüm gerekir." }
        Remove-Item $arsiv -ErrorAction SilentlyContinue
        Set-Content -Path $surum -Value $PyUrl -Encoding ascii
    }
    # indirmeler: çıktı (ilerleme) doğrudan bu pencereye; PowerShell'in stderr işlemesine girmesin diye ayrı süreç
    $env:PYTHONUTF8 = "1"
    $p = Start-Process -FilePath $py -ArgumentList @("-m", "asistan.bootstrap", "`"$Hedef`"") -WorkingDirectory $Hedef `
        -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Hata "Kurulum yarım kaldı. İnterneti denetleyip Kur.bat'ı yeniden çalıştır; inenler korunur, kaldığı yerden sürer."
    }
}

Yaz "Program denetleniyor…"
$env:QT_QPA_PLATFORM = "offscreen"
$denetim = Calistir $py @("-c", "import PySide6.QtWidgets, httpx, anthropic, ddgs, bs4, keyring, psutil")
Remove-Item Env:\QT_QPA_PLATFORM
if ($denetim -ne 0) { Hata "Programın parçaları yüklenemedi (Python denetimi başarısız)." }

Yaz "Kısayollar oluşturuluyor…"
$kabuk = New-Object -ComObject WScript.Shell
foreach ($klasor in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    Remove-Item (Join-Path $klasor "Yerel Asistan.lnk") -ErrorAction SilentlyContinue  # 2.2'ye kadarki adı
    $k = $kabuk.CreateShortcut((Join-Path $klasor "YENİ NESİL CAFER.lnk"))
    $k.TargetPath = $pyw
    $k.Arguments = '-X utf8 "' + $main + '"'
    $k.WorkingDirectory = $Hedef
    $k.IconLocation = Join-Path $Hedef "asistan\gui\assets\icon.ico"
    $k.Description = "YENİ NESİL CAFER — kişisel yapay zekâ asistanı"
    $k.Save()
}

# gömülü temel model: paketteki Ollama ile internetsiz kurulur
$modeller = Join-Path $Hedef "modeller"
if (Test-Path (Join-Path $modeller "Modelfile")) {
    $model = (Get-Content (Join-Path $modeller "MODEL")).Trim()
    Yaz "Temel model ($model) kuruluyor (internet gerekmez, 1-2 dakika)…"
    $sunucu = $null
    try {
        $calisiyor = $true
        try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch { $calisiyor = $false }
        if (-not $calisiyor) {
            $sunucu = Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden -PassThru
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Milliseconds 500
                try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { }
            }
        }
        Push-Location $modeller
        $sonuc = Calistir $ollama @("create", $model, "-f", "Modelfile")
        Pop-Location
        if ($sonuc -eq 0) { Remove-Item (Join-Path $modeller "*.gguf") -Force }
        else { Yaz "Temel model şimdi kurulamadı; program ilk açılışta tekrar deneyecek." }
    } catch {
        Yaz "Temel model şimdi kurulamadı; program ilk açılışta tekrar deneyecek."
    } finally {
        if ($sunucu -and -not $sunucu.HasExited) { Stop-Process -Id $sunucu.Id -Force -ErrorAction SilentlyContinue }
    }
}

Write-Host ""
if (Test-Path $Eski) {  # eski adlı kurulum (Yerel Asistan): ayarlar ve sohbetler program açılınca yeni ada taşınır
    Remove-Item $Eski -Recurse -Force -ErrorAction SilentlyContinue
}
Yaz "Kurulum bitti. YENİ NESİL CAFER açılıyor; ilk açılışta sistemini tarayıp sana uygun modelleri önerecek (internet paketinde modeller o zaman iner)."
Start-Process $pyw -ArgumentList ('-X utf8 "' + $main + '"') -WorkingDirectory $Hedef
