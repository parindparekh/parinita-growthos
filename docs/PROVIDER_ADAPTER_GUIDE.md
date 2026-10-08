# Writing a provider adapter

Built-in adapters and their settings are in `PROVIDERS.md`. This page is for adding another one.

## Contract (`app/adapters/__init__.py`)

```python
from app.adapters import Adapter, DeliveryResult, register
from app.adapters._common import base_url, call, compose, failure, secret

class ExampleNetAdapter(Adapter):                   # "ExampleNet" is fictitious; use the real provider's API reference
    protocols = {"examplenet"}                      # also add to schemas.Protocol, netguard.PUSH_ONLY and PUSH in console.js

    def check_config(self, url, cfg) -> str:        # runs when the endpoint is created or edited
        return "" if cfg.get("bearer_token_env") and cfg.get("account_id") else "examplenet needs bearer_token_env and account_id"

    def send(self, payload, endpoint, cfg, idempotency_key, resume="") -> DeliveryResult:
        token = secret(cfg, "bearer_token_env")     # GROWTHOS_SECRET_* only; raises a readable error if unset
        text = compose(payload, "examplenet", 500)  # current Amplify copy, else title + summary + CTA; link never cut
        r, attempts, err = call("POST", base_url("examplenet", "https://api.example.net") + f"/v1/accounts/{cfg['account_id']}/posts",
                                idempotent=False, json={"text": text}, headers={"Authorization": f"Bearer {token}"})
        if r is not None and r.status_code == 201:
            return DeliveryResult(ok=True, status_code=201, attempts=attempts, provider_id=str(r.json().get("id", "")))
        return failure(r, attempts, err)

register(ExampleNetAdapter())
```

Import the module from `app/adapters/__init__.py` so it registers.

## What the core does around every adapter

`feed_fabric.push_content` runs, in order: destination enabled / direction / classification policy, the
Hallucination Gate, the idempotency claim on `deliveries`, the adapter, the delivery record, the audit event.
An adapter cannot skip any of them and must not change content state.

## Rules

1. Build the request from `payload` (the public projection). Do not read the database.
2. Add no prose of your own. Every sentence that leaves must come from governed content, or the gate never saw it.
3. Credentials via `secret(cfg, "<name>_env")`. Never from content, never from endpoint `headers`.
4. All HTTP through `_common.call` (or `netguard.safe_post`) so the egress policy and retry rules apply.
5. `idempotent=True` only if the provider honours an idempotency key you send. Otherwise `False`: the helper
   then retries only on connection failure and HTTP 429.
6. Multi-step providers: return the intermediate id in `provider_id` even on failure. The next attempt receives
   it as `resume` and should continue instead of starting over (see `TransistorAdapter`).
7. `provider_id` on success = the provider's post / episode / release id.
8. `PROVIDER_BASE_OVERRIDES={"examplenet": "http://127.0.0.1:9000"}` points the adapter at a sandbox or mock.

## Tests to write (`tests/test_providers.py` has the pattern)

Request shape and auth header; text limit; provider 4xx with a useful message; no blind retry on 5xx; 429 retry;
duplicate Send produces one request; gate-blocked item produces none; bad config rejected at creation with 422.
