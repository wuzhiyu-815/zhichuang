const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/workspace-main.js', 'utf8');
const code = src.slice(src.indexOf('async function selectSkill('), src.indexOf('function newSkillForm('));
async function select(builtin, can_delete) {
  const elements = {};
  const element = id => elements[id] ||= {
    classList: {hidden:false, add(){this.hidden=true;}, remove(){this.hidden=false;}, toggle(name, value){this.hidden=value;}},
  };
  const context = {CURRENT_SKILL_ID:'', SKILL_NEW:false, $:element, renderSkillsList(){},
    document:{querySelectorAll:()=>[]}, alert:message=>assert.fail(message),
    fetch:async()=>({ok:true,json:async()=>({ok:true,skill:{id:'test',builtin,can_delete,stages:[]}})})};
  vm.createContext(context);
  vm.runInContext(code, context);
  await context.selectSkill('test');
  return elements;
}
(async()=>{
  const admin = await select(true,true);
  assert.equal(admin['skill-delete-btn'].classList.hidden,false);
  assert.equal(admin['skill-save-btn'].classList.hidden,true);
  assert.equal(admin['skill-edit-content'].readOnly,true);
  const restricted = await select(true,false);
  assert.equal(restricted['skill-delete-btn'].classList.hidden,true);
  const custom = await select(false,undefined);
  assert.equal(custom['skill-delete-btn'].classList.hidden,false);
  console.log('PASS: admin builtin delete, readonly content, restricted users and custom skills');
})().catch(error=>{console.error(error);process.exitCode=1;});
