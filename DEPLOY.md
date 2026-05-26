# Despliegue en producción (Render / similar)

## Variables de entorno obligatorias

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Clave secreta Flask (32+ caracteres aleatorios) |
| `FLASK_ENV` | `production` |
| `DATABASE_PATH` | Ruta persistente, ej. `/data/lottery.db` |
| `INITIAL_ADMIN_PASSWORD` | Contraseña del admin inicial (primer arranque) |

Opcional: `INITIAL_ADMIN_USERNAME`, `LOG_LEVEL`, `PORT`

## Instalación local

```bash
pip install -r requirements.txt
copy .env.example .env
# Editar .env
python app.py
```

## Tests

```bash
pytest
```

## Producción local con Gunicorn

```bash
set FLASK_ENV=production
set SECRET_KEY=tu-clave-secreta-larga
gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --timeout 120
```

## Render

1. Conectar repositorio
2. Build: `pip install -r requirements.txt`
3. Start: `gunicorn app:app` (o usar Procfile)
4. Disco persistente en `/data` con `DATABASE_PATH=/data/lottery.db`
5. Health check: `GET /health`

## Endpoints de diagnóstico (solo admin)

- `/health` — público, sin auth
- `/debug/system` — admin
- `/debug/leidsa` — admin
- `/debug/leidsa/dropdowns` — admin
- `/debug/leidsa/history` — admin
- `/debug/recomendacion/leidsa` — admin
