"""Run the local validation suite through the owner's FIFO build wrapper."""
import json
from pathlib import Path
import subprocess
import sys

commands = [[sys.executable, '-B', '-m', 'tests'],
            [sys.executable, '-B', '-m', 'pytest', 'tests_ha', '-o', 'asyncio_mode=auto', '-p', 'no:cacheprovider']]
commands += [['node', str(path)] for path in sorted(Path('.github').glob('*.cjs'))]
commands += [[sys.executable, '-B', 'scripts/' + name] for name in ['validate_catalog.py', 'check_consumption_coverage.py', 'check_sprint_ledger.py']]
commands += [[sys.executable, '-B', 'scripts/generate_frontend_catalog.py', '--check'], ['node', '--check', 'ha-vacuum-water-monitor.js']]
failed = []
for command in commands:
    print('\nRUN', ' '.join(command), flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode:
        failed.append(command)
assert Path('ha-vacuum-water-monitor.js').read_bytes() == Path('custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js').read_bytes()
import jsonschema
root = Path('custom_components/ha_vacuum_water_monitor')
jsonschema.Draft202012Validator(json.loads((root/'model_profiles.schema.json').read_text()), format_checker=jsonschema.FormatChecker()).validate(json.loads((root/'model_profiles.json').read_text()))
print('FAILED COMMANDS:', json.dumps(failed), flush=True)
sys.exit(bool(failed))
