(async()=>{
 const $=id=>document.getElementById(id);let csrf='',resetId=null;
 async function api(url,method='GET',body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})}),data=await r.json();if(r.status===401){location.assign('/login');throw Error('请重新登录');}if(!r.ok||!data.ok)throw Error(data.msg||'操作失败');return data;}
 function cell(row,text){const td=document.createElement('td');td.textContent=text;row.appendChild(td);return td;}
 function button(parent,text,handler){const b=document.createElement('button');b.textContent=text;b.className='secondary';b.onclick=async()=>{b.disabled=true;try{await handler();}catch(e){$('status').textContent=e.message;}finally{b.disabled=false;}};parent.appendChild(b);}
 async function load(){
  const data=await api('/api/team/users');$('users').replaceChildren();
  for(const u of data.users){const row=document.createElement('tr');cell(row,u.email||u.username);cell(row,u.display_name);cell(row,u.role==='admin'?'管理员':'成员');cell(row,u.enabled?'启用':'停用');const actions=cell(row,'');
   button(actions,u.enabled?'停用':'启用',async()=>{await api('/api/team/users/'+u.id,'PATCH',{enabled:!u.enabled});await load();});
   if(u.role==='member')button(actions,'分配节点',()=>openNodes(u));
   button(actions,'重置密码',()=>{resetId=u.id;$('reset-title').textContent='重置密码 · '+u.username;$('reset-panel').hidden=false;$('reset-password').value='';$('reset-password').focus();});
   button(actions,u.role==='admin'?'设为成员':'设为管理员',async()=>{await api('/api/team/users/'+u.id,'PATCH',{role:u.role==='admin'?'member':'admin'});await load();});$('users').appendChild(row);
  }
  const log=await api('/api/team/audit');$('audit').replaceChildren();for(const i of log.items){const row=document.createElement('tr');cell(row,new Date(i.created*1000).toLocaleString());cell(row,i.username||'系统');const labels={team_user_nodes:'分配成员节点',email_register:'邮箱注册',team_mail_settings:'修改发信设置',team_mail_test:'发送测试邮件',login:'登录',team_users:'创建账号',update_user:'修改账号',team_update_user:'修改账号',team_password:'修改密码',team_logout:'退出登录',api_series_create:'创建剧项目',api_pipeline_run:'启动制作',api_render_queue_add:'加入生成队列',api_render_queue_pause:'暂停队列',api_render_queue_start:'继续队列',jianying_export_start:'导出剪映草稿',start:'合并下载'};cell(row,labels[i.action]||i.action);$('audit').appendChild(row);}
 }
 $('create-form').onsubmit=async e=>{e.preventDefault();$('create-button').disabled=true;try{await api('/api/team/users','POST',{username:$('username').value.trim(),display_name:$('display-name').value.trim(),password:$('password').value,role:$('role').value});$('password').value='';$('status').textContent='账号已创建，请将账号和初始密码交给对应成员。';await load();}catch(error){$('status').textContent=error.message;}finally{$('create-button').disabled=false;}};
 $('reset-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/team/users/'+resetId,'PATCH',{password:$('reset-password').value});$('reset-password').value='';$('reset-panel').hidden=true;$('status').textContent='密码已重置，该成员下次登录需修改密码。';await load();}catch(error){$('status').textContent=error.message;}};
 $('reset-cancel').onclick=()=>{$('reset-panel').hidden=true;$('reset-password').value='';};

 let nodesUser=null,nodes=[];
 function renderNodes(){
  $('nodes-rows').replaceChildren();
  for(const node of nodes){
   const row=document.createElement('div');row.className='form-grid';
   for(const [key,label,placeholder] of [['name','节点名称','例如 视频节点 1'],['url','节点地址','http://服务器地址:8188']]){
    const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement('input');input.value=node[key]||'';input.placeholder=placeholder;input.required=true;input.oninput=()=>node[key]=input.value;wrap.appendChild(input);row.appendChild(wrap);
   }
   const label=document.createElement('label');label.textContent='状态';const select=document.createElement('select');select.add(new Option('启用','true'));select.add(new Option('停用','false'));select.value=String(node.enabled!==false);select.onchange=()=>node.enabled=select.value==='true';label.appendChild(select);row.appendChild(label);
   const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='移除';remove.onclick=()=>{nodes=nodes.filter(n=>n!==node);renderNodes();};row.appendChild(remove);$('nodes-rows').appendChild(row);
  }
  if(!nodes.length){const p=document.createElement('p');p.textContent='暂无分配节点。保存空列表将收回该成员的全部 ComfyUI 节点。';$('nodes-rows').appendChild(p);}
 }
 async function openNodes(user){const d=await api('/api/team/users/'+user.id+'/nodes');nodesUser=user.id;nodes=d.nodes.map(n=>({...n}));$('nodes-title').textContent='分配 ComfyUI 节点 · '+user.display_name;$('nodes-panel').hidden=false;$('nodes-health').textContent='正在检测节点状态…';refreshAssignedHealth();$('nodes-catalog').hidden=true;$('nodes-status').textContent='';renderNodes();$('nodes-panel').scrollIntoView({behavior:'smooth',block:'start'});}
 $('nodes-add').onclick=()=>{nodes.push({name:'',url:'',enabled:true});renderNodes();};
 $('nodes-copy').onclick=async()=>{try{
  const r=await fetch('/api/config'),cfg=await r.json();if(!r.ok)throw Error('无法读取自己的节点');
  const catalog=$('nodes-catalog');catalog.replaceChildren();catalog.hidden=false;
  for(const source of cfg.comfyui_servers||[]){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=(source.name||'ComfyUI')+' · '+source.url;b.onclick=()=>{if(!nodes.some(n=>n.url===source.url)){nodes.push({name:source.name,url:source.url,enabled:source.enabled!==false});renderNodes();}b.disabled=true;};catalog.appendChild(b);}
  if(!catalog.childNodes.length)catalog.textContent='你尚未配置节点，可直接填写上方节点地址。';
 }catch(e){$('nodes-status').textContent=e.message;}};
 $('nodes-cancel').onclick=()=>{$('nodes-panel').hidden=true;};
 $('nodes-form').onsubmit=async e=>{e.preventDefault();$('nodes-save').disabled=true;try{const d=await api('/api/team/users/'+nodesUser+'/nodes','PUT',{nodes});nodes=d.nodes;renderNodes();$('nodes-status').textContent='节点分配已保存，待分派任务将自动使用最新的在线节点。';}catch(e){$('nodes-status').textContent=e.message;}finally{$('nodes-save').disabled=false;}};
 let healthLoading=false;
 async function refreshAssignedHealth(){
  if(!nodesUser||$('nodes-panel').hidden||healthLoading)return;
  const uid=nodesUser;healthLoading=true;
  try{const d=await api('/api/team/users/'+uid+'/nodes');if(uid!==nodesUser)return;$('nodes-health').textContent=(d.node_statuses||[]).map(n=>(n.name||'ComfyUI')+'：'+(!n.enabled?'已停用':n.busy?'渲染中':n.online===true?'在线':n.online===false?'离线':'正在检测')).join('；')||'暂无已保存的分配节点';}
  catch(e){$('nodes-health').textContent='暂时无法读取节点状态';}finally{healthLoading=false;}
 }
 setInterval(refreshAssignedHealth,5000);
 async function loadMail(){const d=await api('/api/team/email-settings');for(const key of ['enabled','host','port','security','username','sender'])$('mail-'+key).value=String(d.settings[key]);$('mail-password').placeholder=d.settings.password_set?'已保存授权码，留空保持不变':'请输入 SMTP 密码或邮箱授权码';}
 $('mail-form').onsubmit=async e=>{e.preventDefault();$('mail-save').disabled=true;try{const body={};for(const key of ['host','port','security','username','sender','password'])body[key]=$('mail-'+key).value;body.enabled=$('mail-enabled').value==='true';await api('/api/team/email-settings','POST',body);$('mail-password').value='';await loadMail();$('mail-status').textContent='已保存。开启注册后，用户即可通过登录页的注册入口验证邮箱并注册。';}catch(e){$('mail-status').textContent=e.message;}finally{$('mail-save').disabled=false;}};
 $('mail-test-form').onsubmit=async e=>{e.preventDefault();$('mail-test').disabled=true;try{const d=await api('/api/team/email-test','POST',{email:$('mail-recipient').value});$('mail-status').textContent=d.msg;}catch(e){$('mail-status').textContent=e.message;}finally{$('mail-test').disabled=false;}};
 try{const data=await api('/api/auth/session');csrf=data.csrf;if(!data.user){location.assign('/login');return;}if(data.user.must_change){location.assign('/account/password');return;}await load();await loadMail();}catch(error){$('status').textContent=error.message;}
})();
