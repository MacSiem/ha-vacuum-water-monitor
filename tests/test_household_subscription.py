"""The scoped subscription delivers compact balance updates and detaches cleanly."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]

class HouseholdSubscriptionTests(unittest.TestCase):
    def test_household_receives_own_domain_updates_and_unsubscribe_stops_delivery(self):
        source = ROOT / "custom_components/ha_vacuum_water_monitor/websocket_api.py"
        tree = ast.parse(source.read_text())
        handlers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_ws_subscribe"]
        self.assertTrue(handlers, "Authenticated household subscription endpoint is missing")
        handler = handlers[0]
        handler.decorator_list = []
        listeners = {}
        def listen(kind, callback):
            listeners[kind] = callback
            return lambda: listeners.pop(kind, None)
        events = []
        results = []
        connection = SimpleNamespace(user=SimpleNamespace(is_admin=False), subscriptions={}, send_event=lambda *args: events.append(args), send_result=lambda *args: results.append(args))
        hass = SimpleNamespace(bus=SimpleNamespace(async_listen=listen))
        ns = {"HomeAssistant": object, "websocket_api": SimpleNamespace(ActiveConnection=object), "Any": object, "EVENT_STATE_CHANGED": "ha_vacuum_water_monitor_state_changed", "callback": lambda f:f}
        exec(compile(ast.Module(body=[handler],type_ignores=[]),str(source),"exec"),ns)
        ns["_ws_subscribe"](hass, connection, {"id":7,"type":"ha_vacuum_water_monitor/subscribe"})
        payload = {"partial":True,"tank_states":{"vacuum.qa":{"used_ml":175}}}
        listeners["ha_vacuum_water_monitor_state_changed"](SimpleNamespace(data=payload))
        self.assertEqual(events, [(7,{"data":payload})])
        self.assertEqual(results, [(7,)])
        connection.subscriptions[7]()
        self.assertFalse(listeners)

    def test_household_card_receives_compact_updates_without_losing_history(self):
        subprocess.run(["node", ".github/household-events.cjs"],cwd=ROOT,check=True,env=os.environ.copy())
