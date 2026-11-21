FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY dental_agent/ ./dental_agent/
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY doctor_availability.csv ./

EXPOSE 8000

CMD ["uvicorn", "dental_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
