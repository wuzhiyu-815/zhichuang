(() => {
  let busy = false;
  const output = text => { document.getElementById('system-update-info').textContent = text; };
  const render = task => {
    const r = task.result;
    let text = task.message || '等待操作';
    if (r) {
      text += `\n分支：${r.branch} · 版本：${r.commit}`;
      text += `\n本地领先：${r.ahead ?? '未知'} · 远端领先：${r.behind ?? '未知'} · 修改文件：${r.changes?.length || 0}`;
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
  window.systemUpdateAction = async action => {
    if (busy) return;
    busy = true;
    document.querySelectorAll('[data-update-action]').forEach(b => b.disabled = true);
    try {
      const status = await readStatus();
      const response = await fetch('/api/system-update/' + action, {
        method:'POST', headers:{'Content-Type':'application/json','X-Update-Token':status.token},
        body:JSON.stringify({message:document.getElementById('system-update-message').value})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.msg || '无法执行操作');
      for (let i = 0; i < 900; i++) {
        const {task} = await readStatus();
        render(task);
        if (task.status !== 'running') {
          if (task.restarting) {
            output('更新完成，正在重启。页面将在服务恢复后刷新…');
            await new Promise(resolve => setTimeout(resolve, 6000));
            for (let attempt = 0; attempt < 30; attempt++) {
              try { await readStatus(); location.reload(); return; } catch (_) {}
              await new Promise(resolve => setTimeout(resolve, 2000));
            }
            throw new Error('更新完成，但暂时无法连接重启后的服务，请查看启动窗口');
          }
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      throw new Error('等待超时，请检查服务器；操作不会自动重复提交');
    } catch (error) { output(error.message); }
    finally {
      busy = false;
      document.querySelectorAll('[data-update-action]').forEach(b => b.disabled = false);
    }
  };
})();
