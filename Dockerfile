# Өлшем — production image (Render / Railway / Hugging Face Spaces)
FROM python:3.11-slim

# LibreOffice renders .docx -> PDF to count pages and locate page numbers.
# Liberation Serif is metric-compatible with Times New Roman, so page counts match Word.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui fonts-liberation fonts-liberation2 fonts-dejavu-core \
        fonts-crosextra-carlito fonts-crosextra-caladea fontconfig \
    && rm -rf /var/lib/apt/lists/* && fc-cache -f

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data HOME=/tmp PORT=7860

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY olshem ./olshem
COPY demo ./demo
COPY scripts ./scripts

# pre-compute demo data (synthetic works) so cold starts are instant
RUN python -m olshem.services.seed_build

# Hugging Face Spaces runs the container as uid 1000
RUN chmod -R a+rX /app && useradd -m -u 1000 app && mkdir -p /app/data && chown -R app:app /app/data
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/api/health',timeout=4)"
CMD ["sh", "-c", "uvicorn olshem.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
