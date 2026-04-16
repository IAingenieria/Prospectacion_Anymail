FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Crear carpetas necesarias
RUN mkdir -p logs data

# Usuario no-root para seguridad
RUN useradd -m leadforge && chown -R leadforge:leadforge /app
USER leadforge

CMD ["python", "run.py"]
