import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from test_user_device_removal import storage
from test_local_measurements import cycle, measurement


class MeasurementWebsocketTests(unittest.TestCase):
    def test_save_uses_recorded_cycle_and_rejects_duplicate(self):
        path=Path(__file__).parents[1]/'custom_components/ha_vacuum_water_monitor/websocket_api.py'
        tree=ast.parse(path.read_text())
        handlers=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_ws_save_measurement']
        self.assertTrue(handlers,'Measurement endpoint is missing')
        handler=handlers[0];handler.decorator_list=[]
        async def run():
            st=storage.VacuumWaterStorage(None)
            await st.async_set_tank_state('vacuum.test',{'automatic_sessions':[cycle(1)]})
            ns={'_storage':lambda _:st,'_notify_store_updated':lambda *a:None}
            exec(compile(ast.Module(body=[handler],type_ignores=[]),str(path),'exec'),ns)
            results=[];errors=[]
            connection=SimpleNamespace(send_result=lambda *a:results.append(a),send_error=lambda *a:errors.append(a))
            hass=SimpleNamespace(states=SimpleNamespace(get=lambda _:object()))
            msg={'id':1,'vacuum_entity':'vacuum.test','session_index':0,'session_ts':1,'measurement':measurement()}
            await ns['_ws_save_measurement'](hass,connection,msg)
            await ns['_ws_save_measurement'](hass,connection,msg)
            self.assertTrue(results[0][1]['saved'])
            self.assertEqual(errors[0][1],'invalid_payload')
            self.assertEqual(len((await st.async_get_settings())['local_measurements']['vacuum.test']),1)
        asyncio.run(run())
