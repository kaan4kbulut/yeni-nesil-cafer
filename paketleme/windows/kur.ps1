# YENİ NESİL CAFER — Windows kurulumu (internet gerekmez)
# Paketin içinde her şey var: taşınabilir Python (kütüphaneleri kurulu), Ollama ve temel model.
# Programı %LOCALAPPDATA%\YeniNesilCafer'e kopyalar, masaüstü ve Başlat menüsü kısayolu oluşturur, temel modeli kurar.
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

if (-not (Test-Path (Join-Path $Kaynak "python\pythonw.exe"))) {
    Hata "Kurulum dosyaları eksik. Zip dosyasını tamamen çıkarıp Kur.bat'ı çıkan klasörden çalıştır."
}

# eski kurulumdan açık kalan program ya da Ollama varsa dosyalar kilitli olur: kapat
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path.StartsWith($Hedef, "OrdinalIgnoreCase") -or
    $_.Path.StartsWith($Eski, "OrdinalIgnoreCase")) } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

Yaz "Program kopyalanıyor: $Hedef"
Yaz "(yaklaşık 4 GB, diskine göre 1-3 dakika sürebilir)"
foreach ($eski in @(".venv", "python", "ollama")) {  # eski sürümün kalıntıları
    $yol = Join-Path $Hedef $eski
    if (Test-Path $yol) { Remove-Item $yol -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $Hedef | Out-Null
robocopy $Kaynak $Hedef /E /NFL /NDL /NJH /NJS /NC /NS /NP /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { Hata "Dosyalar kopyalanamadı (robocopy kodu $LASTEXITCODE). Diskte yer var mı?" }

$pyw = Join-Path $Hedef "python\pythonw.exe"
$py = Join-Path $Hedef "python\python.exe"
$ollama = Join-Path $Hedef "ollama\ollama.exe"
$main = Join-Path $Hedef "main.py"

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
Yaz "Kurulum bitti. YENİ NESİL CAFER açılıyor; ilk açılışta sistemini tarayıp sana uygun modelleri önerecek."
Start-Process $pyw -ArgumentList ('-X utf8 "' + $main + '"') -WorkingDirectory $Hedef
