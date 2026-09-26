const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/workspace-main.js','utf8');
const boxes = Array.from({length:13},(_,i)=>({id:`batch-check-${i+1}`,dataset:{},checked:true}));
const context = {
  SCRIPT_DATA:{shots:Array.from({length:21},(_,i)=>({index:i+1,duration:12}))},
  SHOT_DATA:{},
  document:{querySelectorAll:selector=>selector.includes('input[')?boxes:[],getElementById:()=>null},
  $:()=>null,
};
vm.createContext(context);
vm.runInContext(src.slice(src.indexOf('function promptSelectionBoxes()'),src.indexOf('function setPromptShotSelection(')),context);
const result = context.collectPromptBatchEdits();
assert.equal(result.length,21,'Denominator must use full script even with only 13 DOM checkboxes');
assert.equal(result.filter(s=>s.selected).length,13,'Explicit subset must be preserved');
assert.equal(result[20].duration,12,'Hidden shot keeps script duration');
boxes.forEach(b=>b.checked=false);
assert.equal(context.collectPromptBatchEdits().filter(s=>s.selected).length,0,'Clear must stay empty');
console.log('PASS: 21-shot script / 13 checkbox regression and explicit selection');
