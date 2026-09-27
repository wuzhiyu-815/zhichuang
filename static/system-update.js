(() => {
  let busy = false;
  let lastTask = null;
  const output = text => { const el = document.getElementById('system-update-info'); if (el) el.textContent = text; };
  const setBusy = value => {
    busy = value;
    document.querySelectorAll('[data-update-action]').forEach(b => b.disabled = value);
  };
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const render = task => {
    lastTask = task;
    const r = task.result;
    let text = task.message || '等待操作';
    if (r) {
      text += `\n分支：${r.branch} · 版本：${r.commit}`;
      text += `\n本地领先：${r.ahead ?? '未知'} · 远端领先：${r.behind ?? '未知'} · 修改文件：${r.changes?.length || 0}`;
      if (r.behind > 0) text += `\n发现 ${r.behind} 个新提交，可点击“手动更新此服务器”获取。`;
      else if (r.behind === 0 && r.ahead === 0) text += '\n当前代码已与 GitHub 同步。';
      if (r.changes?.length) text += '\n' + r.changes.slice(0, 30).map(x => `${x.status} ${x.path}`).join('\n');
      if (r.restart_required && !task.restarting) text += '\n代码已更新，请使用原服务管理方式重启。';
    }
    output(text);
  };
  async function readStatus() {
    const response = await fetch('/api/system-update/status', {cache:'no-store'});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.msg || data.error || '请先重启后端以加载版本更新功能');
    return data;
  }
  async function pollTask() {
    for (let i = 0; i < 900; i++) {
      const {task} = await readStatus();
      render(task);
      if (task.status !== 'running') {
        if (task.restarting) {
          output('更新完成，正在重启。页面将在服务恢复后刷新…');
          await delay(6000);
          for (let attempt = 0; attempt < 30; attempt++) {
            try { await readStatus(); location.reload(); return; } catch (_) {}
            await delay(2000);
          }
          throw new Error('更新完成，但暂时无法连接重启后的服务，请查看启动窗口');
        }
        return;
      }
      await delay(1000);
    }
    throw new Error('等待超时，请检查服务器；操作不会自动重复提交');
  }
  // Restore an in-flight operation when returning to this page or refreshing it.
  window.systemUpdateRefresh = async () => {
    if (busy) { setBusy(true); if (lastTask) render(lastTask); return; }
    setBusy(true);
    try {
      const {task} = await readStatus();
      render(task);
      if (task.status === 'running' || task.restarting) await pollTask();
    } catch (error) { output(error.message); }
    finally { setBusy(false); }
  };
  window.systemUpdateAction = async action => {
    if (busy) return;
    setBusy(true);
    try {
      const status = await readStatus();
      if (status.task.status === 'running' || status.task.restarting) { await pollTask(); return; }
      const headers = {'Content-Type':'application/json','X-Update-Token':status.token};
      if (window.PLATFORM?.csrf) headers['X-CSRF-Token'] = window.PLATFORM.csrf;
      const response = await fetch('/api/system-update/' + action, {
        method:'POST', headers,
        body:JSON.stringify({message:document.getElementById('system-update-message')?.value || ''})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.msg || '无法执行操作');
      await pollTask();
    } catch (error) { output(error.message); }
    finally {
      setBusy(false);
    }
  };
})();
