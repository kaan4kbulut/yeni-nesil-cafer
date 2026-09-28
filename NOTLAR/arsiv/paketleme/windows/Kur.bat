@echo off
rem YENİ NESİL CAFER kurulumu: çift tıkla. Asıl işi kur.ps1 yapar.
chcp 65001 >nul
if not exist "%~dp0kur.ps1" (
    echo.
    echo   Kurulum dosyaları bulunamadı. Zip dosyasını önce bir klasöre çıkar
    echo   ^(sağ tık, "Tümünü ayıkla"^), sonra çıkan klasördeki Kur.bat dosyasını çalıştır.
    echo.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kur.ps1"
pause
