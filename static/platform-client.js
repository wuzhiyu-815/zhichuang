(() => {
  if (!window.PLATFORM?.user) return;
  const nativeFetch=window.fetch.bind(window), NativeEventSource=window.EventSource;
  window.fetch=async function(input,options={}){
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    if(url.origin===location.origin&&url.pathname.startsWith('/api/')){
      const headers=new Headers(options.headers||(input instanceof Request?input.headers:undefined));
      headers.set('X-CSRF-Token',window.PLATFORM.csrf);
      options={...options,headers};
    }
    const response=await nativeFetch(input,options);
    if(url.origin===location.origin){
      if(response.status===401)location.assign('/login');
      if(response.status===428)location.assign('/account/password');
    }
    return response;
  };
  window.EventSource=class extends NativeEventSource{
    constructor(input,options){
      const url=new URL(input,location.href);
      if(url.origin===location.origin)url.searchParams.set('_csrf',window.PLATFORM.csrf);
      super(url.href,options);
    }
  };
  window.teamLogout=async()=>{await fetch('/api/auth/logout',{method:'POST'});location.assign('/login');};
  document.addEventListener('DOMContentLoaded',()=>{
    const member=PLATFORM.user.role!=='admin';
    document.querySelectorAll('[data-series-scope-title]').forEach(el=>el.textContent=member?'🎞️ 我的剧项目':'🎞️ 全部剧项目');
    document.querySelectorAll('[data-team-admin]').forEach(el=>el.hidden=member);
    const name=document.getElementById('team-current-user');
    if(name)name.textContent=PLATFORM.user.display_name+(member?' · 成员':' · 管理员');
    document.querySelectorAll('[onclick^="openComfyMonitor("]').forEach(el=>el.style.display='none');
    const exclusive=document.getElementById('cfg-exclusive')?.closest('.flex.items-start');if(exclusive)exclusive.style.display='none';
    if(member){
      document.querySelectorAll('#cfg-comfy-section button,#cfg-comfy-section > p').forEach(el=>el.style.display='none');
      for(const handler of ['openTomatoDownloader','openSkillsManager','openComfyMonitor']){
        document.querySelectorAll(`[onclick^="${handler}("]`).forEach(el=>el.style.display='none');
      }
    }
  });
})();
