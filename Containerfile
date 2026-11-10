# Shared by Podman (Fedora host) and Render (Docker runtime)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HOME=/tmp \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY .streamlit .streamlit
COPY app app
RUN useradd -r -u 10001 -s /usr/sbin/nologin appuser
USER 10001
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8501\")}/_stcore/health')"
# Render injects $PORT; Podman falls back to 8501
CMD ["sh","-c","exec streamlit run app/main.py --server.port=${PORT:-8501}"]
