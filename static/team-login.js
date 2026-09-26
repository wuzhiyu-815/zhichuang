(async()=>{
 const $=id=>document.getElementById(id),change=location.pathname==='/account/password';
 let csrf='';
 const adminLink=document.querySelector('#admin-entry a');if(adminLink&&document.body.dataset.adminPort){const address=new URL('/admin/login',location.href);address.port=document.body.dataset.adminPort;adminLink.href=address.href;}

 if(location.pathname.startsWith('/admin/')){ $('heading').textContent='管理员登录';$('intro').textContent='此入口与成员工作区的登录相互独立，可在不同标签页同时使用。';$('signup-link').hidden=true;if($('admin-entry'))$('admin-entry').hidden=true;}

 $('signup-link').hidden=change||location.pathname.startsWith('/admin/');
 if(change){$('heading').textContent='修改登录密码';$('intro').textContent='新账号首次使用需更换初始密码；修改后其他设备的登录会话将失效。';$('username-label').hidden=true;$('username').required=false;for(const id of ['new-label','confirm-label','back'])$(id).hidden=false;$('new-password').required=true;$('confirm-password').required=true;$('submit').textContent='保存新密码';}
 $('submit').disabled=true;
 try{const r=await fetch('/api/auth/session'),data=await r.json();csrf=data.csrf;if(change&&!data.user){location.assign('/login');return;}}
 catch(e){$('status').textContent='无法连接服务，请刷新后重试';return;}
 $('submit').disabled=false;
 $('auth-form').addEventListener('submit',async e=>{
  e.preventDefault();$('status').textContent='';
  if(change&&$('new-password').value!==$('confirm-password').value){$('status').textContent='两次新密码不一致';return;}
  $('submit').disabled=true;
  try{
   const body=change?{old_password:$('password').value,new_password:$('new-password').value}:{username:$('username').value.trim(),password:$('password').value};
   const r=await fetch(change?'/api/auth/password':'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}),data=await r.json();
   if(!r.ok||!data.ok)throw Error(data.msg||'操作失败');
   location.assign(!change&&data.user.must_change?'/account/password':'/');
  }catch(error){$('status').textContent=error.message;}
  finally{$('submit').disabled=false;}
 });
})();
