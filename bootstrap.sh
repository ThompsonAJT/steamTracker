#!/usr/bin/env bash
# =====================================================================
# Scaffolds the whole project from nothing.
#
#   chmod +x bootstrap.sh && ./bootstrap.sh
#
# Creates the folder tree, .env, venv, installs deps, starts Postgres.
# Safe to re-run.
# =====================================================================
set -euo pipefail

PROJECT="steamtracker"

echo "==> Creating folder tree"
mkdir -p "$PROJECT"/db/init "$PROJECT"/app/static
cd "$PROJECT"

if [ ! -f .env ]; then
  echo "==> Writing .env"
  PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
  cat > .env <<EOF
POSTGRES_USER=steam
POSTGRES_PASSWORD=$PASS
POSTGRES_DB=steamtracker
DATABASE_URL=postgresql+psycopg://steam:$PASS@localhost:5433/steamtracker
EOF
  echo "    generated a random password into .env"
fi

if [ ! -f .gitignore ]; then
  cat > .gitignore <<'EOF'
.env
.venv/
__pycache__/
*.pyc
sample_*.json
EOF
fi

echo "==> Python venv + dependencies"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet httpx psycopg[binary] sqlalchemy fastapi uvicorn python-dotenv apscheduler

echo "==> Starting database"
docker compose up -d

echo -n "==> Waiting for Postgres"
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U steam -d steamtracker >/dev/null 2>&1; then
    echo " ready"
    break
  fi
  echo -n "."
  sleep 2
done

echo "==> Tables:"
docker compose exec -T db psql -U steam -d steamtracker -c "\dt"

cat <<'EOF'

Done. Next:

    cd steamtracker
    source .venv/bin/activate
    python ingest.py          # pulls data for ~40 popular games
    uvicorn app.main:app --reload
    open http://localhost:8000

EOF
