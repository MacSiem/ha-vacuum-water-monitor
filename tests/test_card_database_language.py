import ast,json,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'tests/test_card_estimates.py').read_text())
prefix=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCRIPT' for t in n.targets)).split('const cases =')[0]
script=prefix+r'''
card._getDevices=()=>[];
const render=(lang,profile)=>{card._lang=lang;card._config={brand_profile:profile};return card._buildDatabaseTab();};
console.log(JSON.stringify({pl:render('pl','roborock_s7_maxv'),en:render('en','roborock_s7_maxv'),tapo:render('pl','tapo_rv50_pro_omni')}));
'''
class DatabaseLanguageTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.result=json.loads(subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip().splitlines()[-1])
 def test_polish_active_profile_keeps_unknown_capacity_and_localizes_estimate_explanation(self):
  h=self.result['pl'];self.assertNotIn('${this.',h);self.assertIn('aktywny profil',h);self.assertIn('pojemność czystej wody nieznana',h)
  for s in ['clean-water capacity unknown','Estimated water usage by mode','Typical for this mop system','Mop wash in dock:','manufacturer source','capacity unknown','Generic mopping estimate']:
   self.assertNotIn(s,h)
 def test_manufacturer_facts_remain_separate_from_estimated_floor_coverage(self):
  h=self.result['tapo'];self.assertIn('Tapo',h);self.assertIn('5,000',h);self.assertIn('szacowane zużycie wody',h.lower());self.assertIn('https://',h)
  self.assertNotIn('max area on one battery charge',h)
 def test_mixed_source_links_do_not_claim_manufacturer_provenance(self):
  for lang in ['pl','en']:
   h=self.result[lang];self.assertIn('github.com',h);self.assertNotIn('manufacturer source',h);self.assertNotIn('źródło producenta',h);self.assertIn('Źródło' if lang=='pl' else '>Source',h)
 def test_english_model_data_and_sources_are_preserved(self):
  h=self.result['en'];self.assertIn('(active profile)',h);self.assertIn('clean-water capacity unknown',h);self.assertIn('Estimated water usage by mode',h);self.assertIn('ml/m',h);self.assertIn('https://',h)
if __name__=='__main__':unittest.main()
