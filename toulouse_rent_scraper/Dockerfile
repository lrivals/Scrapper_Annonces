# Interface web + API JSON (Sprint 2-bis.5) — PAS le scraping.
# Le scraping a besoin du vrai Chrome, de son profil persistant et d'un écran (X11) :
# il reste sur la machine, lancé par le timer systemd (voir README, « Automatisation »).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Logs et rapports écrits par l'utilisateur du conteneur (UID de l'hôte, voir docker-compose.yml)
RUN mkdir -p logs reports data && chmod 777 logs reports

EXPOSE 5000
# 0.0.0.0 dans le conteneur ; docker-compose ne publie le port que sur 127.0.0.1
CMD ["python", "main.py", "ui", "--host", "0.0.0.0", "--port", "5000", "--no-browser"]
