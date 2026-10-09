"""Render installation variants and verify Kubernetes resource wiring without a cluster."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM_BIN", "helm")
CHART = str(ROOT / "charts" / "growthos")
BASE = ["--set", "image.repository=registry.example.com/growthos", "--set", "image.tag=test",
        "--set", "existingSecret=growthos-runtime", "--set", "publicBaseUrl=https://growthos.example.com"]


def render(extra=(), success=True):
    p = subprocess.run([HELM, "template", "verify", CHART, *BASE, *extra], capture_output=True, text=True)
    assert (p.returncode == 0) == success, p.stderr
    return list(yaml.safe_load_all(p.stdout)) if success else []


def validate():
    subprocess.run([HELM, "lint", CHART, "--strict", *BASE], check=True)
    for extra in [[], ["--set", "worker.enabled=false"],
                  ["--set", "media.enabled=true", "--set", "postgresql.enabled=true", "--set", "postgresql.existingSecret=db-secret"],
                  ["--set", "replicaCount=2", "--set", "podDisruptionBudget.enabled=true", "--set", "ingress.enabled=true",
                   "--set", "ingress.host=growthos.example.com", "--set", "ingress.tlsSecretName=growthos-tls"]]:
        docs = [d for d in render(extra) if d]
        assert not any(d['kind'] == 'Secret' for d in docs)
        service = next(d for d in docs if d['kind'] == 'Service' and d['metadata']['name'] == 'verify-growthos')
        api = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-api'))
        assert all(api['spec']['template']['metadata']['labels'][k] == v for k,v in service['spec']['selector'].items())
        for dep in (d for d in docs if d['kind'] == 'Deployment'):
            pod = dep['spec']['template']['spec']
            assert pod['automountServiceAccountToken'] is False
            c = pod['containers'][0]
            assert c['securityContext']['readOnlyRootFilesystem'] is True
            assert c['envFrom'][1]['secretRef']['name'] == 'growthos-runtime'
            if dep['metadata']['name'].endswith('-api'):
                assert c['readinessProbe']['httpGet']['path'] == '/health'
                assert c['livenessProbe']['httpGet']['path'] == '/live'
            else:
                assert dep['spec']['replicas'] == 1 and dep['spec']['strategy']['type'] == 'Recreate'
    for extra in [["--set", "existingSecret="], ["--set", "publicBaseUrl=http://unsafe.example"],
                  ["--set", "env.API_KEY=forbidden"], ["--set", "podDisruptionBudget.enabled=true"],
                  ["--set", "ingress.enabled=true"], ["--set", "postgresql.enabled=true"],
                  ["--set", "image.tag="]]:
        render(extra, success=False)
    print("PASS: four deployment variants; seven invalid configurations rejected; secret, service, probe and worker checks.")


if __name__ == "__main__":
    validate()
