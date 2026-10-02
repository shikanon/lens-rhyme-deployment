"""Guard commas in tmpfs options against YAML flow-list splitting."""
from pathlib import Path
import yaml

config = yaml.safe_load((Path(__file__).parents[1] / 'compose/docker-compose.yml').read_text())
for name in ('seo-research', 'seo-agent-reach'):
    service = config['services'][name]
    assert len(service['tmpfs']) == 1, f'{name}: tmpfs options split into multiple mount paths'
    assert service['tmpfs'][0].startswith('/tmp:size=') and ',mode=1777' in service['tmpfs'][0]
    assert service.get('ports') is None
    assert service['read_only'] is True and service['pull_policy'] == 'never'
print('SEO research Compose isolation and tmpfs checks passed.')
