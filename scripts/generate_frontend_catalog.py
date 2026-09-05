#!/usr/bin/env python3
"""Generate the read-only card catalog from validated backend records."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');args=ap.parse_args()
 profiles=json.loads((ROOT/'custom_components/ha_vacuum_water_monitor/model_profiles.json').read_text())['profiles']
 client={}
 for key,r in profiles.items():
  caps=r['reservoirs_ml'];client[key]={'label':r['manufacturer']+' '+r['model'],'tank_ml':r['tracked_capacity_ml'],'robot_tank_ml':caps['robot_clean'],'dock_clean_tank_ml':caps['dock_clean'],'dock_dirty_tank_ml':caps['dock_dirty'],'robot_clean_tank_ml':caps['robot_clean'],'robot_dirty_tank_ml':caps['robot_dirty'],'detergent_tank_ml':caps['detergent'],'water_per_m2':{},'mop_wash_ml':None,'source_urls':[s['url'] for s in r['provenance']],'data_quality':r['verification_status'],'notes':'Capacity evidence only. Unknown fields require model-specific documentation; all consumption rates require measurement.'}
 client['generic']={'label':'Unknown model','tank_ml':None,'robot_tank_ml':None,'water_per_m2':{},'mop_wash_ml':None,'notes':'No verified capacity or consumption rate.'}
 source=(ROOT/'ha-vacuum-water-monitor.js').read_text()
 generated=re.sub(r'const CALIBRATION_DATA = \{.*?\n\};',lambda _: 'const CALIBRATION_DATA = '+json.dumps(client,ensure_ascii=False,indent=2)+';',source,count=1,flags=re.S)
 targets=[ROOT/'ha-vacuum-water-monitor.js',ROOT/'custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']
 if args.check:
  if any(t.read_text()!=generated for t in targets):raise SystemExit('Frontend catalog drift; run scripts/generate_frontend_catalog.py')
 else:
  for t in targets:t.write_text(generated)
 print('Frontend catalog parity PASS')
if __name__=='__main__':main()
