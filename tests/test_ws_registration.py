"""Every decorated websocket endpoint must be installed by the entrypoint."""
import ast
from pathlib import Path
import unittest
class RegistrationTests(unittest.TestCase):
    def test_all_endpoint_handlers_are_registered(self):
        tree=ast.parse((Path(__file__).parents[1]/'custom_components/ha_vacuum_water_monitor/websocket_api.py').read_text())
        endpoints={n.name for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name.startswith('_ws_')}
        register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='async_register_commands')
        installed={n.id for n in ast.walk(register) if isinstance(n,ast.Name)}
        self.assertFalse(endpoints-installed, f'Missing handlers: {endpoints-installed}')
