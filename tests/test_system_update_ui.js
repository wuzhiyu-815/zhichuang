const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(responses, platform = {csrf: 'team-csrf'}) {
  const calls = [], buttons = [{disabled:false}, {disabled:false}];
  const elements = {
    'system-update-info': {textContent:''},
    'system-update-message': {value:'Update story skills'},
  };
  const context = {
    window: {PLATFORM:platform},
    document: {getElementById: id => elements[id], querySelectorAll: () => buttons},
    location: {reload: () => { context.reloaded = true; }},
    setTimeout: fn => { fn(); },
    fetch: async (url, options) => {
      calls.push({url, options});
      const data = responses.shift();
      assert.ok(data, `Unexpected request: ${url}`);
      return {ok:data.ok !== false, json:async () => data};
    },
  };
  vm.runInNewContext(fs.readFileSync('static/system-update.js', 'utf8'), context);
  return {context, calls, buttons, elements};
}
const idle = {ok:true,token:'update-token',task:{status:'idle'}};
const done = {ok:true,task:{status:'done',message:'完成',result:{branch:'main',commit:'abc123',ahead:0,behind:2,changes:[]}}};

(async () => {
  // Team requests need both independent tokens; completed status exposes updates.
  for (const action of ['check', 'push', 'update']) {
    const t = setup([idle, {ok:true}, done]);
    await t.context.window.systemUpdateAction(action);
    const request = t.calls.find(x => x.options?.method === 'POST');
    assert.equal(request.url, '/api/system-update/' + action);
    assert.equal(request.options.headers['X-CSRF-Token'], 'team-csrf');
    assert.equal(request.options.headers['X-Update-Token'], 'update-token');
    assert.equal(JSON.parse(request.options.body).message, 'Update story skills');
    assert.match(t.elements['system-update-info'].textContent, /发现 2 个新提交/);
    assert.ok(t.buttons.every(b => !b.disabled));
  }
  // Returning to the page resumes polling, never submits the operation twice.
  const resumed = setup([{ok:true,task:{status:'running'}}, done]);
  await resumed.context.window.systemUpdateRefresh();
  assert.ok(resumed.calls.every(x => x.options?.method !== 'POST'));
  const duplicate = setup([{ok:true,task:{status:'running'}}, done]);
  await duplicate.context.window.systemUpdateAction('push');
  assert.ok(duplicate.calls.every(x => x.options?.method !== 'POST'));
  // Navigating away removes the panel; an ongoing operation must still finish.
  const away = setup([idle, {ok:true}, done]);
  delete away.elements['system-update-info'];
  delete away.elements['system-update-message'];
  await away.context.window.systemUpdateAction('check');
  assert.equal(away.calls.length, 3);
  const failure = setup([idle, {ok:false,msg:'有生成任务正在运行'}]);
  await failure.context.window.systemUpdateAction('update');
  assert.match(failure.elements['system-update-info'].textContent, /有生成任务正在运行/);
  assert.ok(failure.buttons.every(b => !b.disabled));
  const restart = setup([idle, {ok:true}, {ok:true,task:{status:'done',restarting:true}}, idle]);
  await restart.context.window.systemUpdateAction('update');
  assert.equal(restart.context.reloaded, true);
  console.log('PASS: team CSRF, check/push/update, status resume, navigation, errors and restart');
})().catch(error => { console.error(error); process.exitCode = 1; });
