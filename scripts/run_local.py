"""Run an isolated development instance on loopback; never publishes by default."""
import os
import json
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
    if name.startswith(('GROWTHOS_SECRET_', 'CHRYSALIS_', 'OIDC_', 'SMTP_', 'SESSION_')):
        os.environ.pop(name)
port = int(os.environ.get('GROWTHOS_LOCAL_PORT', '8080'))
if not 1024 <= port <= 65535:
    raise ValueError('GROWTHOS_LOCAL_PORT must be between 1024 and 65535')
os.environ.update(ENVIRONMENT='development', API_KEY=key_file.read_text().strip(), API_KEYS='',
                  DATABASE_URL='sqlite:///' + (data / 'growthos.db').as_posix(),
                  PUBLIC_BASE_URL=f'http://127.0.0.1:{port}')

# Local accounts are opt-in. Never inherit production credentials implicitly.
# This directory is git-ignored; the file is provisioned privately by the operator.
from scripts.local_connectors import load_connector_secrets
os.environ.update(load_connector_secrets(data / 'connector-secrets.json'))

from cryptography.fernet import Fernet
vault_key = data / "connector-vault.key"
if not vault_key.exists():
    with vault_key.open("xb") as stream:
        stream.write(Fernet.generate_key())
os.environ["CONNECTOR_ENCRYPTION_KEY"] = vault_key.read_text(encoding="utf-8").strip()

from app import config
# Ignore any production .env file for this isolated development launcher.
model_file = data / 'model-connection.json'
model_options = {}
if model_file.exists():
    connection = json.loads(model_file.read_text(encoding='utf-8-sig'))
    # Only model settings may be supplied by this private, git-ignored file.
    for source, target in [('BLU_API_BASE', 'text_model_base_url'),
                           ('BLU_API_KEY', 'text_model_api_key'),
                           ('BLU_MODEL', 'text_model_name')]:
        if connection.get(source):
            model_options[target] = connection[source]
config.settings = config.Settings(_env_file=None, **model_options)

if __name__ == '__main__':
    import uvicorn
    print(f'GrowthOS local console: http://127.0.0.1:{port}/console', flush=True)
    print(f'Local admin access key: {key_file}', flush=True)
    uvicorn.run('app.main:app', host='127.0.0.1', port=port)
