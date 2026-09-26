(async()=>{
 const $=id=>document.getElementById(id);let csrf='',enabled=false;
 async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)}:{}),d=await r.json();if(!r.ok||!d.ok)throw Error(d.msg||'请求失败');return d;}
 try{csrf=(await api('/api/auth/session')).csrf;enabled=(await api('/api/auth/registration')).enabled;if(!enabled){$('status').textContent='邮箱注册尚未启用。请管理员在「团队管理 → 邮箱注册与发信设置」中配置发信服务并开启注册。';return;}$('send-code').disabled=false;$('submit').disabled=false;}catch(e){$('status').textContent=e.message;return;}
 $('send-code').onclick=async()=>{
  if(!$('email').reportValidity())return;
  $('send-code').disabled=true;
  try{const d=await api('/api/auth/email-code',{email:$('email').value});$('status').textContent=d.msg;let remaining=d.retry_after;const tick=()=>{$('send-code').textContent=remaining>0?`${remaining} 秒后重发`:'重新发送验证码';if(remaining--<=0){clearInterval(timer);$('send-code').disabled=false;}};const timer=setInterval(tick,1000);tick();}catch(e){$('status').textContent=e.message;$('send-code').disabled=false;}
 };
 $('register-form').onsubmit=async e=>{e.preventDefault();if(!enabled)return;if($('password').value!==$('confirm-password').value){$('status').textContent='两次密码不一致';return;}$('submit').disabled=true;try{await api('/api/auth/register',{email:$('email').value,code:$('code').value,password:$('password').value,display_name:$('display-name').value});location.assign('/');}catch(e){$('status').textContent=e.message;}finally{$('submit').disabled=false;}};
})();
