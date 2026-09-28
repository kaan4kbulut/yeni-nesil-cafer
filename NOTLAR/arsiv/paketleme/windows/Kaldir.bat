@echo off
rem YENİ NESİL CAFER'i kaldırır. Sohbetlerin ve ayarların silinmez (%APPDATA%\yeni-nesil-cafer, %LOCALAPPDATA%\yeni-nesil-cafer).
chcp 65001 >nul
set "HEDEF=%LOCALAPPDATA%\YeniNesilCafer"
rem açık kalan program ve paketteki Ollama kapatılsın (dosyalar kilitli kalmasın)
powershell -NoProfile -Command "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:HEDEF, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"
timeout /t 1 >nul
rem kısayollar: dosya adında Türkçe harf (İ) var; .bat'tan PowerShell'e ASCII kalıpla geçirilir (eski adlılar da silinir)
powershell -NoProfile -Command "foreach ($d in @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) { Remove-Item (Join-Path $d '*CAFER.lnk'), (Join-Path $d 'Yerel Asistan.lnk') -ErrorAction SilentlyContinue }"
if exist "%HEDEF%" rmdir /s /q "%HEDEF%"
if exist "%LOCALAPPDATA%\YerelAsistan" rmdir /s /q "%LOCALAPPDATA%\YerelAsistan"
echo YENİ NESİL CAFER kaldırıldı. Sohbetlerin ve ayarların duruyor.
echo Yüklenen yapay zeka modelleri %USERPROFILE%\.ollama klasöründe; yer açmak istersen o klasörü silebilirsin.
pause
