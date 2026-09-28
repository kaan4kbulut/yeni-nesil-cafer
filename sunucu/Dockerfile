# YENİ NESİL CAFER · sunucu modu (MIMARI §9): python:3.12-slim, yalnızca çekirdek + web; masaüstü kodu yüklenmez.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CAFER_GENEL_KADEME_KILIDI=sunucu \
    XDG_DATA_HOME=/veri XDG_CONFIG_HOME=/veri/ayar HOME=/veri
RUN useradd --system --create-home --home-dir /veri asistan && mkdir -p /veri/ayar && chown -R asistan:asistan /veri
WORKDIR /app
COPY requirements-sunucu.txt .
RUN pip install --no-cache-dir -r requirements-sunucu.txt
COPY asistan/ ./asistan/
# masaüstü kodu imaja girmez (gui), Playwright/3D motorları da yok
RUN rm -rf asistan/gui asistan/arayuz/masaustu && find . -name __pycache__ -type d -exec rm -rf {} +
USER asistan
VOLUME ["/veri"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/saglik', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "asistan", "sunucu", "--host", "0.0.0.0", "--port", "8765"]
