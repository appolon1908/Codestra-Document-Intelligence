FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.141.1 uvicorn==0.54.0
COPY stub.py /srv/stub.py
WORKDIR /srv
USER 65534:65534
CMD ["uvicorn", "stub:app", "--host", "0.0.0.0", "--port", "8080"]
