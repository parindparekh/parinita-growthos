"""Transfer approved episode copy to a company-authorized Studio project."""
import re
from . import Adapter, DeliveryResult, register
from ._common import call, failure, secret

_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


class AIStudioAdapter(Adapter):
    protocols = {"ai_studio"}

    def check_config(self, url, cfg):
        if not url or not cfg.get("bearer_token_env"):
            return "AI Studio needs a service URL and company producer token variable"
        if cfg.get("aspect_ratio", "16:9") not in {"16:9", "9:16", "1:1", "4:5"}:
            return "AI Studio aspect_ratio must be 16:9, 9:16, 1:1 or 4:5"
        return ""

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        script = str(payload.get("body") or "").strip()
        if not 10 <= len(script) <= 200000:
            return DeliveryResult(ok=False, publishes=False, detail="Studio needs an episode script between 10 and 200000 characters")
        headers = {"Authorization": "Bearer " + secret(cfg, "bearer_token_env"), "Content-Type": "application/json"}
        base = endpoint.url.rstrip("/")
        project = resume
        if project and not _ID.fullmatch(project):
            return DeliveryResult(ok=False, publishes=False, detail="Invalid Studio project reference")
        if not project:
            # Project creation does not support idempotency. Never retry it automatically.
            response, n, error = call("POST", base + "/api/projects", headers=headers, idempotent=False,
                json={"name": (str(payload.get("title") or "GrowthOS episode")[:120]).ljust(2),
                      "project_type": "enterprise", "prompt": script[:8000]})
            if response is None or response.status_code != 201:
                return failure(response, n, error, "Studio project creation was not confirmed; inspect Studio before retrying")
            try:
                project = response.json()["id"]
                if not isinstance(project, str) or not _ID.fullmatch(project):
                    raise ValueError("invalid project")
            except (ValueError, KeyError, TypeError):
                return DeliveryResult(ok=False, publishes=False, detail="Studio returned an invalid project reference; inspect Studio before retrying")
        try:
            response, n, error = call("POST", base + f"/api/projects/{project}/script", headers=headers, idempotent=False,
                json={"text": script, "episode": 1, "aspect_ratio": cfg.get("aspect_ratio", "16:9"), "expected_version": 0})
        except Exception:
            return DeliveryResult(ok=False, publishes=False, provider_id=project,
                detail="Studio script transfer is unconfirmed; inspect the project before retrying")
        if response is None or response.status_code != 200:
            result = failure(response, n, error, "Studio script transfer needs attention; existing project retained")
            result.provider_id, result.publishes = project, False
            return result
        try:
            result = response.json()
            if not isinstance(result.get("graph"), dict) or not result["graph"].get("version"):
                raise ValueError("missing graph")
        except (ValueError, AttributeError, TypeError):
            return DeliveryResult(ok=False, publishes=False, provider_id=project, detail="Studio did not confirm the script graph")
        return DeliveryResult(ok=True, publishes=False, provider_id=project, status_code=200,
            detail="Episode script prepared in AI Studio. Video creation requires Studio render approval and configured models.")


register(AIStudioAdapter())
