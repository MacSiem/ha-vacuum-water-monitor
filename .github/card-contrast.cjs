// Contrast checks derive literal tokens from the actual shipped CSS rules.
const fs=require('fs'),assert=require('assert/strict');
const rulesFor=source=>[...source.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]+)\}/g)].map(match=>({selectors:match[1].trim().split(',').map(s=>s.trim()),body:match[2]}));
function declaration(rules,selector,key){
 let value;
 for(const rule of rules)if(rule.selectors.includes(selector)){
  const match=rule.body.match(new RegExp('(?:^|;)\\s*'+key+':\\s*([^;!]+)'));
  if(match)value=match[1].trim();
 }
 assert.ok(value,'Missing consumed '+key+' for '+selector);return value;
}
function luminance(hex){
 let s=hex.replace('#','');if(s.length===3)s=[...s].map(c=>c+c).join('');
 assert.match(s,/^[0-9a-f]{6}$/i,'Expected literal color token');
 const rgb=[0,2,4].map(i=>parseInt(s.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
 return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
}
function check(fg,bg,minimum,label){const a=luminance(fg),b=luminance(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);assert.ok(ratio>=minimum,label+' '+ratio.toFixed(2));}
for(const file of ['ha-vacuum-water-monitor.js','custom_components/ha_vacuum_water_monitor/www/ha-vacuum-water-monitor.js']){
 const rules=rulesFor(fs.readFileSync(file,'utf8'));
 const color=selector=>declaration(rules,selector,'color');
 const primary=color('.card .refill-btn');
 check(primary,declaration(rules,'.card .refill-btn','background'),4.5,'normal action');
 check(primary,declaration(rules,'.card .refill-btn:hover','background'),4.5,'hover action');
 check(color('.card .refill-btn:disabled'),declaration(rules,'.card .refill-btn:disabled','background'),4.5,'disabled action');
 for(const [prefix,bg] of [['','#ffffff'],[':host(.bento-dark) ','#28283c']]){
  check(color(prefix+'.card .vwm-link'),bg,4.5,prefix+'text action');
  check(color(prefix+'.card .tab-nav .tab-btn[aria-selected="true"]'),bg,4.5,prefix+'selected tab');
  check(declaration(rules,prefix+'.card :focus-visible','outline-color'),bg,3,prefix+'focus');
 }
 const font=declaration(rules,'.card .tab-nav .tab-btn','font-size');assert.ok(parseFloat(font)>=12,'tab typography');
}
console.log('Shipped action/hover/disabled/link/tab/focus contrast and tab typography PASS, both cards');
