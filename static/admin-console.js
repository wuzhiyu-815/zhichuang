(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const names={overview:'运行概览',projects:'连续剧管理',history:'独立短片管理',episodes:'剧集与素材管理',tasks:'任务队列',team:'用户与权限',settings:'服务与模型',skills:'公共 Skills',library:'小说书库',usage:'配额与用量',audit:'操作审计',maintenance:'备份与维护'};
  let current='overview',generation=0;
  const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
  const action=(label,fn)=>{const b=text('button',label);b.onclick=fn;return b;};
  async function api(path,method='GET',body){const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':window.PLATFORM.csrf},...(body?{body:JSON.stringify(body)}:{})});if(r.status===401){location.assign('/login');throw Error('请重新登录');}const data=await r.json();if(!r.ok||!data.ok)throw Error(data.msg||'操作失败');return data;}
  function table(headings){const wrap=text('div','','panel scroll'),table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr'),body=document.createElement('tbody');headings.forEach(h=>row.append(text('th',h)));head.append(row);table.append(head,body);wrap.append(table);$('content').append(wrap);return body;}
  function info(value){$('content').append(text('p',value,'muted'));}
  const bytes=value=>(value/1024**3).toFixed(2)+' GB';
  async function show(page){const token=++generation;current=page;$('message').textContent='';$('page-title').textContent=names[page];$('content').replaceChildren();$('workspace').hidden=true;$('workspace').src='about:blank';document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-current',b.dataset.page===page?'page':'false'));
    if(['projects','history','episodes','tasks','team','settings','skills','library'].includes(page)){$('content').hidden=true;$('workspace').hidden=false;$('workspace').src=page==='team'?'/team':'/manage/workspace?embedded=1&view='+page;return;}
    $('content').hidden=false;
    try{
      if(page==='overview'||page==='usage'){
        const data=await api('/api/manage/overview');if(token!==generation)return;
        if(page==='overview'){
          const cards=text('div','','cards');for(const [name,value] of [['成员数',data.users.filter(r=>r.user.role==='member').length],['作品数',data.users.reduce((n,r)=>n+r.usage.projects,0)],['运行任务',data.queue.running],['待处理错误',data.queue.error]]){const card=text('div',name,'card');card.append(text('strong',value));cards.append(card);}$('content').append(cards);
          info(`成员工作台端口 ${data.member_port} · 管理后台端口 ${data.admin_port}。管理员与成员使用独立会话，制作队列由同一服务调度。`);
          const panel=text('div','','panel');panel.append(text('h2','管理范围'),text('p','在此管理账号、节点分配、公共 Skills、作品归属、任务队列及系统备份。成员的私人连接配置独立保存。','muted'));$('content').append(panel);
        }else{
          info('0 表示不限。并发和每日次数约束整集制作任务；每次启动或续跑计一次，按 UTC 日期重置。存储在启动前检查，正在运行的任务不会因达到阈值被中断；单镜任务不计入整集额度。');
          const body=table(['成员','作品 / 成片','作品存储','运行 / 今日启动','整集并发上限','每日启动上限','存储启动阈值 GB','操作']);
          for(const row of data.users.filter(r=>r.user.role==='member')){const tr=document.createElement('tr');[row.user.display_name||row.user.username,`${row.usage.projects} / ${row.usage.completed}`,bytes(row.usage.bytes),`${row.usage.active} / ${row.usage.daily}`].forEach(v=>tr.append(text('td',v)));const fields={};for(const key of ['parallel','daily','storage_gb']){const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.min='0';input.step=key==='storage_gb'?'0.1':'1';input.value=row.limits[key];input.setAttribute('aria-label',row.user.username+' '+key);fields[key]=input;td.append(input);tr.append(td);}const td=document.createElement('td');td.append(action('保存',async()=>{try{await api('/api/manage/users/'+row.user.id+'/quota','POST',Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Number(v.value)])));$('message').textContent='配额已保存';}catch(e){$('message').textContent=e.message;}}));tr.append(td);body.append(tr);}
        }
      }else if(page==='audit'){
        const data=await api('/api/team/audit');if(token!==generation)return;const body=table(['时间','账号','操作','对象']);for(const row of data.items){const tr=document.createElement('tr');[new Date(row.created*1000).toLocaleString(),row.username||'系统',row.action,row.resource].forEach(v=>tr.append(text('td',v)));body.append(tr);}info('记录管理员查看与下载作品，以及配置、删除、用户和队列操作。');
      }else if(page==='maintenance'){
        info('备份系统代码、配置、静态页面和工作流，不包含项目、素材、成片、账号数据库及队列状态。恢复或升级需要停机维护，当前页面不直接覆盖运行中的系统。');
        const create=action('创建系统备份',async()=>{create.disabled=true;try{await api('/api/manage/backups','POST',{});await show('maintenance');$('message').textContent='系统备份已完成';}catch(e){$('message').textContent=e.message;create.disabled=false;}});create.className='primary';$('content').append(create);const data=await api('/api/manage/backups');if(token!==generation)return;const body=table(['备份文件','创建时间','大小','操作']);for(const row of data.items){const tr=document.createElement('tr');[row.name,new Date(row.created*1000).toLocaleString(),(row.bytes/1024/1024).toFixed(1)+' MB'].forEach(v=>tr.append(text('td',v)));const td=document.createElement('td'),a=text('a','下载');a.href='/api/manage/backups/'+encodeURIComponent(row.name);a.download=row.name;td.append(a);tr.append(td);body.append(tr);}
      }
    }catch(e){if(token===generation)$('message').textContent=e.message;}
  }
  $('account').textContent=window.PLATFORM?.user?.display_name||'管理员';
  document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.page));
  $('refresh').onclick=()=>show(current);
  $('logout').onclick=async()=>{try{await api('/api/auth/logout','POST',{});location.assign('/login');}catch(e){$('message').textContent=e.message;}};
  show('overview');
})();
