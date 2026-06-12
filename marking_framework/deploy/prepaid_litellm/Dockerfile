FROM python:3.12-slim

WORKDIR /app
COPY deploy/prepaid_litellm/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
ENV PORT=8080
CMD ["sh", "-c", "uvicorn deploy.prepaid_litellm.credit_service:app --host 0.0.0.0 --port ${PORT}"]
