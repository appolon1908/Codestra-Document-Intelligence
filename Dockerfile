FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
CMD ["uvicorn","codestra_document_intelligence.app:app","--app-dir","src","--host","0.0.0.0","--port","8080"]
