"""Emit a CycloneDX 1.5 inventory from the fully resolved runtime lock.
No vulnerability assessment or signed build provenance is implied.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
components = []
for name, version in re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', (root/'requirements.lock').read_text(), re.M):
    name = name.lower().replace('_','-')
    purl = f'pkg:pypi/{name}@{version}'
    components.append({'type':'library', 'name':name, 'version':version, 'purl':purl, 'bom-ref':purl})
bom = {'bomFormat':'CycloneDX','specVersion':'1.5','version':1,
       'metadata':{'timestamp':datetime.now(timezone.utc).isoformat(),
                   'component':{'type':'application','name':'Parinita GrowthOS','version':'1.8.0'}},
       'components':components}
print(json.dumps(bom,indent=2))
