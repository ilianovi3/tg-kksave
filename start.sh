# Переходим в рабочую директорию
cd /srv/tg-kksocial

echo "🛠 Собираю образы и запускаю сервисы..."
docker-compose build
docker-compose up -d
