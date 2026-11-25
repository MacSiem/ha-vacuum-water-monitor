"""Exercise the registry listener without a Home Assistant installation."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace


def test_registry_burst_is_coalesced_and_discovery_is_preserved():
    async def scenario():
        path = Path(__file__).resolve().parents[1] / 'custom_components/ha_vacuum_water_monitor/__init__.py'
        tree = ast.parse(path.read_text())
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_listen_vacuum_registry')
        fn.decorator_list = []
        class Registry:
            entities = {}
            def async_get(self, key):
                return self.entities.get(key)
        registry = Registry()
        class Bus:
            def async_listen(self, _event, callback):
                self.callback = callback
                return lambda: None
        class Ticker:
            def __init__(self):
                self.calls = 0
                self.started = asyncio.Event()
                self.resume = asyncio.Event()
            async def run(self, _vacuums):
                self.calls += 1
                self.started.set()
                await self.resume.wait()
            async def run_serialized(self, action):
                return await action()
        class Storage:
            async def async_reconcile_registry(self, _identities):
                pass
        bus, ticker, notifications = Bus(), Ticker(), []
        hass = SimpleNamespace(bus=bus, data={'vwm': {'ticker': ticker}}, async_create_task=asyncio.create_task)
        env = {'callback': lambda f: f, 'HomeAssistant': object, 'VacuumWaterStorage': object,
               'Event': object, 'er': SimpleNamespace(async_get=lambda _: registry, EVENT_ENTITY_REGISTRY_UPDATED='registry'),
               'DOMAIN': 'vwm', 'DATA_TICKER': 'ticker', '_vacuum_registry_identities': lambda _: {},
               '_notify_store_updated': lambda _, payload: notifications.append(payload)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), env)
        stop, tasks = env['_listen_vacuum_registry'](hass, Storage())
        def add(entity, platform):
            registry.entities[entity] = SimpleNamespace(entity_id=entity, platform=platform, device_id='device', domain=entity.split('.')[0])
        def dispatch(entity):
            bus.callback(SimpleNamespace(data={'entity_id': entity, 'action': 'create'}))
        add('vacuum.robot', 'matter')
        dispatch('vacuum.robot')
        await asyncio.gather(*list(tasks))
        assert notifications == [{'registry_changed': True}]
        add('sensor.own', 'vwm')
        dispatch('sensor.own')
        assert not tasks
        add('sensor.source', 'matter')
        for _ in range(1000):
            dispatch('sensor.source')
        assert len(tasks) == 1
        await ticker.started.wait()
        dispatch('sensor.source')  # A change during the tick requires a follow-up.
        ticker.resume.set()
        await asyncio.gather(*list(tasks))
        assert ticker.calls == 2
        assert len(notifications) == 3
        stop()
    asyncio.run(scenario())
