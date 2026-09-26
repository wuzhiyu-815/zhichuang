function renderComfyServers(){
  if(window.PLATFORM?.user?.role==='member'){
    const list=$('cfg-comfy-list');list.replaceChildren();
    const note=document.createElement('p');note.className='text-xs text-gray-400';note.textContent=comfyServers.length?'以下节点由管理员分配，修改请联系管理员。':'尚未分配 ComfyUI 节点，请联系管理员。';list.appendChild(note);
    for(const s of comfyServers){const row=document.createElement('div');row.className='text-xs py-2';row.textContent=`${s.name||'ComfyUI'} · ${s.enabled?'启用':'停用'} · ${s.url}`;list.appendChild(row);}
    return;
  }
  const list=$('cfg-comfy-list');list.replaceChildren();
  comfyServers.forEach((s,i)=>{
    const row=document.createElement('div');row.className='space-y-2 p-3 rounded-lg border border-white/10';
    const top=document.createElement('div');top.className='flex items-center gap-2';
    const en=document.createElement('input');en.type='checkbox';en.checked=s.enabled!==false;en.onchange=()=>s.enabled=en.checked;
    const name=document.createElement('input');name.value=s.name||`ComfyUI ${i+1}`;name.placeholder='节点名称';name.className='flex-1 min-w-0 bg-black/30 border border-white/10 rounded-lg px-2 py-1';name.oninput=()=>s.name=name.value;
    const toggle=document.createElement('button');toggle.type='button';toggle.textContent=s.enabled!==false?'停用节点':'启用节点';toggle.className=s.enabled!==false?'text-xs text-red-300':'text-xs text-green-300';toggle.onclick=()=>toggleComfyServer(s,toggle,en);
    const test=document.createElement('button');test.type='button';test.textContent='测试';test.className='text-xs text-green-300';test.onclick=()=>testComfyServer(s,test);
    const del=document.createElement('button');del.type='button';del.textContent='删除';del.className='text-xs text-red-400';del.onclick=()=>{comfyServers=comfyServers.filter(x=>x.id!==s.id);renderComfyServers();};
    top.append(en,document.createTextNode('启用'),name,toggle,test,del);
    const url=document.createElement('input');url.value=s.url||'';url.placeholder='http://192.168.1.100:8188';url.className='w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2';url.oninput=()=>s.url=url.value.trim();
    const status=document.createElement('span');status.className='text-xs text-gray-500';status.textContent=s.enabled!==false?'可参与任务分发':'已停用';
    row.append(top,url,status);list.appendChild(row);s._status=status;
  });
}
async function toggleComfyServer(server,button,checkbox){
  const next=server.enabled===false;
  const old=button.textContent;button.disabled=true;button.textContent=next?'启用中…':'停用中…';
  try{
    const r=await fetch('/api/comfy/server/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:server.id,enabled:next})});
    const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||d.msg||'节点状态更新失败');
    server.enabled=next;checkbox.checked=next;button.textContent=next?'停用节点':'启用节点';
    button.className=next?'text-xs text-red-300':'text-xs text-green-300';
    log(`${server.name||server.url} 已${next?'启用':'停用'}，${next?'会':'不会'}参与后续任务分发`,next?'text-green-400':'text-gray-400');
  }catch(e){checkbox.checked=server.enabled!==false;button.textContent=old;alert(e.message);}
  finally{button.disabled=false;}
}
async function testComfyServer(s,button){
  const old=button.textContent;button.disabled=true;button.textContent='测试中';
  try{
    const r=await fetch('/api/comfy/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:s.url})});
    const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||d.message||'离线');
    s._status.textContent=`在线（HTTP ${d.status}）`;s._status.className='text-xs text-green-400';
  }catch(e){s._status.textContent=e.message;s._status.className='text-xs text-red-400';}
  finally{button.disabled=false;button.textContent=old;}
}
function addComfyServer(){comfyServers.push({id:newClientId(),name:`ComfyUI ${comfyServers.length+1}`,url:'',enabled:true});renderComfyServers();}
let comfyHealthLoading=false;
async function refreshComfyHealth(){
  if(comfyHealthLoading||$('nodes-modal').classList.contains('hidden'))return;
  comfyHealthLoading=true;
  try{
    const r=await fetch('/api/comfy/nodes-status'),d=await r.json();if(!r.ok||!d.ok)return;
    const box=$('cfg-comfy-health');box.replaceChildren();
    for(const node of d.nodes){const row=document.createElement('div');const label=!node.enabled?'已停用':node.busy?'渲染中':node.online===true?'在线 · 可参与渲染':node.online===false?'离线 · 自动等待恢复':'正在检测';row.textContent=`${node.name||'ComfyUI'}：${label}`;box.appendChild(row);}
    if(!d.nodes.length)box.textContent='暂无已配置 / 已分配节点';
  }catch(e){$('cfg-comfy-health').textContent='暂时无法读取节点状态';}
  finally{comfyHealthLoading=false;}
}
setInterval(refreshComfyHealth,5000);

async function openNodeManager(){
  try{
    const r=await fetch('/api/config');const c=await r.json();
    if(!r.ok)throw Error(c.error||'读取节点失败');
    comfyServers=(c.comfyui_servers||[]).map(s=>({...s}));
    const member=window.PLATFORM?.user?.role==='member';
    $('nodes-add').hidden=member;$('nodes-save').hidden=member;
    $('nodes-message').textContent=member?'节点由管理员分配。':'新增、删除和勾选启用状态后，请保存节点配置。';
    renderComfyServers();$('nodes-modal').classList.replace('hidden','flex');refreshComfyHealth();
  }catch(e){alert(e.message);}
}
function closeNodeManager(){$('nodes-modal').classList.replace('flex','hidden');}
async function saveNodes(){
  const button=$('nodes-save');button.disabled=true;
  try{
    const nodes=comfyServers.map(({id,name,url,enabled})=>({id,name,url,enabled}));
    const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({comfyui_servers:nodes})});
    const d=await r.json();if(!r.ok||!d.ok)throw Error(d.error||'保存失败');
    comfyServers=(d.config.comfyui_servers||[]).map(s=>({...s}));renderComfyServers();
    $('nodes-message').textContent='节点配置已保存，等待分配的任务会使用最新在线节点。';refreshComfyHealth();refreshStatus();
  }catch(e){$('nodes-message').textContent=e.message;}
  finally{button.disabled=false;}
}
