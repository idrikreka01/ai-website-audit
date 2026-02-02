FROM python:3.11-bookworm

WORKDIR /app

COPY api/requirements.txt ./api-requirements.txt
COPY worker/requirements.txt ./worker-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r worker-requirements.txt
RUN playwright install --with-deps chromium

COPY . .
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
