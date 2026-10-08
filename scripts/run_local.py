"""Run an isolated development instance on loopback; never publishes by default."""
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
data = ROOT / 'data' / 'local'
data.mkdir(parents=True, exist_ok=True)
key_file = data / 'admin-key.txt'
if not key_file.exists():
    key_file.write_text(secrets.token_urlsafe(36), encoding='utf-8')

# The launcher always uses a separate development database and local identity.
# Do not inherit an operator's production provider or identity configuration.
for name in list(os.environ):
    if name.startswith(('GROWTHOS_SECRET_', 'CHRYSALIS_', 'OIDC_', 'SMTP_', 'TEXT_MODEL_', 'SESSION_')):
        os.environ.pop(name)
os.environ.update(ENVIRONMENT='development', API_KEY=key_file.read_text().strip(), API_KEYS='',
                  DATABASE_URL='sqlite:///' + (data / 'growthos.db').as_posix(),
                  PUBLIC_BASE_URL='http://127.0.0.1:8080')

from app import config
# Ignore any production .env file for this isolated development launcher.
config.settings = config.Settings(_env_file=None)

if __name__ == '__main__':
    import uvicorn
    print('GrowthOS local console: http://127.0.0.1:8080/console', flush=True)
    print(f'Local admin access key: {key_file}', flush=True)
    uvicorn.run('app.main:app', host='127.0.0.1', port=8080)
