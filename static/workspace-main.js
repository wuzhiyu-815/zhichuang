
const STAGES=[{n:1,name:'剧本解析',icon:'📝'},{n:2,name:'资产生成',icon:'🎨'},{n:3,name:'分镜视频',icon:'🎥'},{n:4,name:'合成成片',icon:'🏆'}];
let generationReference=null, generationReferenceBusy=false;
function setGenerationReference(reference){generationReference=reference||null;window.dispatchEvent(new Event('generation-reference-change'));}
let ASSET_EDIT_DATA={};
let currentPid=null, es=null, SHOT_DATA={}, SCRIPT_DATA=null, scriptChatHistory=[], PROJECT_LIST=[], DRAMA_PROJECT_LIST=[], RENDER_QUEUE=[], MANAGER_CURRENT=null, MANAGER_SELECTED=new Set(), MANAGER_PREVIEW_MODE='compact';
let restoringLastView=false;
let runStartedAt=0, runClockTimer=null, draftTimer=null;
let directorMatched=false, directorConfirmedSignature='', applyingDirectorMatch=false;

function $(id){return document.getElementById(id);}
function teamOwnerBadge(item){return window.PLATFORM?.user?.role==='admin'&&item.owner_name?` <span class="text-[10px] text-gray-500">· ${escapeHtml(item.owner_name)}</span>`:'';}
function newClientId(){
  if(window.crypto&&typeof window.crypto.randomUUID==='function')return window.crypto.randomUUID();
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`;
}
function log(msg,cls='text-gray-400'){
  const text=`[${new Date().toLocaleTimeString()}] ${msg}`;
  const d=document.createElement('div');d.className='log-line '+cls;d.textContent=text;$('log').appendChild(d);$('log').scrollTop=1e9;
  const side=$('side-process-log');if(side){if(side.textContent==='暂无过程日志')side.textContent='';const line=document.createElement('div');line.className=cls;line.textContent=text;side.appendChild(line);while(side.children.length>40)side.firstChild.remove();side.scrollTop=1e9;}
}

function renderStages(){
  $('stages').innerHTML=STAGES.map((s,i)=>`
    <div class="flex items-center flex-1" id="stage-${s.n}">
      <div class="flex flex-col items-center gap-1">
        <div class="stage-dot">${s.icon}</div>
        <div class="text-xs text-gray-400 whitespace-nowrap">${s.name}</div>
      </div>
      ${i<3?'<div class="flex-1 h-0.5 bg-white/10 mx-2 mb-5"></div>':''}
    </div>`).join('');
}
function setStage(n,state){
  const el=$('stage-'+n);if(!el)return;el.classList.remove('stage-active','stage-done','stage-err');if(state)el.classList.add(state);
  const stage=STAGES.find(x=>x.n===n);if($('side-process-stage'))$('side-process-stage').textContent=stage?`${stage.icon} ${stage.name} · ${state==='stage-done'?'已完成':state==='stage-err'?'出错':'进行中'}`:'等待开始';
  if($('side-process-dot'))$('side-process-dot').className='dot '+(state==='stage-err'?'dot-off':'dot-on');
}

let statusRefreshing=false;
async function refreshStatus(){
  if(statusRefreshing)return; statusRefreshing=true;
  try{
    const s=await(await fetch('/api/status')).json();
    $('dot-llm').className='dot '+(s.llm_online?'dot-on':'dot-off');
    $('dot-comfy').className='dot '+(s.comfyui_online?'dot-on':'dot-off');
    const mediaLabel=document.querySelector('#dot-comfy')?.parentElement;
    if(mediaLabel)mediaLabel.lastChild.textContent=s.media_provider==='jimeng'?' 即梦 API':' ComfyUI';
    $('dot-ffmpeg').className='dot '+(s.ffmpeg?'dot-on':'dot-off');
    $('llm-name').textContent=s.llm_model||'';
  }catch(e){} finally {statusRefreshing=false;}
}

async function refreshRenderQueue(){
  try{
    const r=await(await fetch('/api/render-queue')).json();
    if(!r.ok)return;
    RENDER_QUEUE=r.items||[];
    const active=RENDER_QUEUE.filter(x=>x.status!=='removed'&&x.status!=='done');
    $('queue-count').textContent=String(active.length);
    const activeNodes=r.active_nodes||[];
    $('queue-workers').textContent=`节点 ${r.busy_nodes||0}/${r.configured_workers||0}${activeNodes.length?` · ${activeNodes.map(escapeHtml).join('、')}`:''}`;
    $('queue-toggle-btn').textContent=r.running?'队列运行中':'启动队列';
    const label={queued:'等待中',running:'生成中',paused:'已暂停',retry:'待重试',error:'失败',done:'已完成'};
    const color={running:'text-yellow-300',error:'text-red-300',done:'text-green-300',paused:'text-gray-400'};
    $('render-queue-list').innerHTML=active.length?active.map(item=>{
      const pct=Math.max(0,Math.min(100,Number(item.progress)||0));
      const series=item.series?.name?` · ${escapeHtml(item.series.name)}${item.series.episode?` 第${item.series.episode}集`:''}`:'';
      const phase=item.phase?` · ${escapeHtml(item.phase)}`:'';
      const isRuntimeTask=item.queue_type==='single_shot'||item.queue_type==='rerender'||item.queue_type==='batch_render';
      return `<div class="workspace-list-item" title="${escapeHtml(item.error||item.message||'')}">
        <div class="workspace-item-heading"><div class="workspace-item-title">${escapeHtml(item.title||item.pid)}</div><span class="text-[10px] ${color[item.status]||'text-gray-500'}">${label[item.status]||item.status}</span></div>
        <div class="workspace-item-meta">${series}${item.status==='running'?` · ${pct}%${phase}${item.server?` · 节点 ${escapeHtml(item.server)}`:''}`:''}${item.error?`<br><span class="text-red-300">${escapeHtml(item.error).slice(0,80)}</span>`:''}</div>
        ${item.status==='error'&&!isRuntimeTask?`<button onclick="retryRenderQueueItem('${item.id}',event);event.stopPropagation();" class="mt-2 text-[10px] text-yellow-300 hover:text-yellow-100">↻ 重新排队</button>`:''}
        ${item.status!=='running'?`<button onclick="removeRenderQueueItem('${item.id}');event.stopPropagation();" class="mt-2 ml-3 text-[10px] text-gray-500 hover:text-red-300">移除</button>`:''}
      </div>`;
    }).join(''):'<div class="workspace-muted">队列为空</div>';
  }catch(e){}
}
async function toggleRenderQueue(){
  const r=await(await fetch('/api/render-queue/start',{method:'POST'})).json();
  if(!r.ok){alert(r.msg||'无法启动队列');return;}
  refreshRenderQueue();log('视频队列已启动','text-green-400');
}
async function pauseRenderQueue(){
  const r=await(await fetch('/api/render-queue/pause',{method:'POST'})).json();
  if(!r.ok){alert(r.msg||'无法暂停队列');return;}
  refreshRenderQueue();log('视频队列已暂停，当前生成完成后停止','gold');
}
async function addProjectsToRenderQueue(pids){
  const ids=[...new Set((pids||[]).filter(Boolean))];
  if(!ids.length){alert('没有可加入队列的单集项目');return;}
  const r=await(await fetch('/api/render-queue/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pids:ids,start:true})})).json();
  if(!r.ok){alert(r.msg||'加入队列失败');return;}
  refreshRenderQueue();
  log(`已加入 ${r.added?.length||0} 个视频任务`,'text-green-400');
  if(r.errors?.length)alert(r.errors.map(x=>`${x.pid}: ${x.msg}`).join('\n'));
}
function addEpisodeToRenderQueue(pid){addProjectsToRenderQueue([pid]);}
function queueCurrentProject(){
  if(!currentPid){alert('请先打开一个已经生成剧本、资产和分镜的单集项目');return;}
  addProjectsToRenderQueue([currentPid]);
}
async function queuePreparedEpisodes(){
  if(!SERIES_CURRENT)return;
  const pids=Object.values(SERIES_CURRENT.episode_status||{}).map(x=>x.project_id).filter(Boolean);
  await addProjectsToRenderQueue(pids);
}
async function removeRenderQueueItem(id){
  const r=await(await fetch(`/api/render-queue/${encodeURIComponent(id)}`,{method:'DELETE'})).json();
  if(!r.ok){alert(r.msg||'移除失败');return;}refreshRenderQueue();
}
async function retryRenderQueueItem(id,evt){
  const item=RENDER_QUEUE.find(x=>x.id===id);if(!item)return;
  const button=evt?.currentTarget;
  if(button){button.disabled=true;button.textContent='处理中…';}
  try{
    const r=await(await fetch('/api/render-queue/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pids:[item.pid],start:true})})).json();
    if(!r.ok){alert(r.msg||'重新排队失败');return;}
    const message=r.added?.length?'已重新排队，队列将继续生成。':(r.skipped?.[0]?.msg||r.errors?.[0]?.msg||'该项目未加入队列');
    log(message,r.added?.length?'text-green-400':'gold');
    if(r.errors?.length)alert(r.errors.map(x=>`${x.pid}: ${x.msg}`).join('\n'));
    refreshRenderQueue();
  }catch(e){alert('重新排队失败：'+e.message);}
  finally{if(button){button.disabled=false;button.textContent='↻ 重新排队';}}
}

function toggleCustomStyle(){
  const custom=$('style').value==='__custom__';
  $('styleCustom').classList.toggle('hidden',!custom);
  if(custom)$('styleCustom').focus();
}
function getStyleValue(){
  if($('style').value==='__custom__')return $('styleCustom').value.trim();
  return $('style').value;
}
let SKILLS=[], CURRENT_SKILL_ID='', SKILL_NEW=false;
const SKILL_STAGE_LABELS={script:'剧本解析',video_prompt:'视频提示词',asset:'资产生成',review:'审片',compose:'合成'};
function skillName(id){return id==='auto'?'自动识别':id==='none'?'基础 H3':(SKILLS.find(x=>x.id===id)?.name||id);}
function renderSkillSelectors(videoId,scriptId){
  const video=$('prompt-skill-mode'),script=$('script-skill-mode');
  videoId=videoId||video?.value||'auto';scriptId=scriptId||script?.value||'auto';
  if(video){
    video.replaceChildren(new Option('自动识别','auto'),new Option('基础 H3','none'));
    SKILLS.filter(x=>(x.stages||[]).includes('video_prompt')).forEach(x=>video.appendChild(new Option(x.name,x.id)));
    video.value=videoId||video.value||'auto';if(![...video.options].some(o=>o.value===video.value))video.value='auto';
  }
  if(script){
    script.replaceChildren(new Option('自动解析','auto'));
    SKILLS.filter(x=>(x.stages||[]).includes('script')).forEach(x=>script.appendChild(new Option(x.name,x.id)));
    script.value=scriptId||script.value||'auto';if(![...script.options].some(o=>o.value===script.value))script.value='auto';
  }
}
async function loadSkills(videoId='',scriptId=''){
  try{
    const r=await fetch('/api/skills');const d=await r.json();
    if(!r.ok||!d.ok)throw new Error(d.msg||'读取 Skills 失败');
    SKILLS=d.skills||[];
    renderSkillSelectors(videoId,scriptId);
    renderSkillsList();
  }catch(e){if($('skills-editor-status'))$('skills-editor-status').textContent=e.message;}
}
function renderCustomSkills(selectedId=''){renderSkillSelectors(selectedId,$('script-skill-mode')?.value||'auto');}
function loadCustomSkills(selectedId=''){return loadSkills(selectedId,$('script-skill-mode')?.value||'auto');}
function chooseCustomSkill(id){if(id){$('prompt-skill-mode').value=id;queueDraftSave();invalidateDirectorMatch(false);updateDirectorPreview();}}
function renderSkillsList(){
  const box=$('skills-list');if(!box)return;
  const query=($('skills-search')?.value||'').trim().toLowerCase();
  const list=SKILLS.filter(x=>!query||`${x.name} ${x.description} ${(x.stages||[]).map(s=>SKILL_STAGE_LABELS[s]).join(' ')}`.toLowerCase().includes(query));
  $('skills-count').textContent=String(SKILLS.length);
  box.innerHTML=list.map(x=>`<button type="button" class="w-full text-left rounded-lg p-2.5 ${CURRENT_SKILL_ID===x.id?'bg-cyan-400/15 border-cyan-400/40':'bg-black/20 border-white/10'} border hover:border-cyan-400/40" onclick="selectSkill('${escapeHtml(x.id)}')">
    <div class="flex items-center gap-2"><span class="text-xs font-bold truncate">${escapeHtml(x.name)}</span><span class="tag ml-auto">${x.builtin?'内置':'自定义'}</span></div>
    <div class="text-[10px] text-gray-500 mt-1 truncate">${escapeHtml((x.stages||[]).map(s=>SKILL_STAGE_LABELS[s]||s).join(' · ')||'未绑定环节')}</div>
  </button>`).join('')||'<div class="workspace-muted">没有匹配的 Skill</div>';
}
async function selectSkill(id){
  CURRENT_SKILL_ID=id;SKILL_NEW=false;renderSkillsList();
  const r=await fetch(`/api/skills/${encodeURIComponent(id)}`),d=await r.json();
  if(!r.ok||!d.ok){alert(d.msg||'读取 Skill 失败');return;}
  const s=d.skill;$('skills-empty').classList.add('hidden');$('skills-editor').classList.remove('hidden');
  $('skills-editor-kind').textContent=s.builtin?'内置 · 只读':'自定义';
  $('skills-editor-id').textContent=s.id;
  $('skill-edit-name').value=s.name||'';$('skill-edit-description').value=s.description||'';$('skill-edit-content').value=s.content||'';
  document.querySelectorAll('.skill-stage-check').forEach(c=>c.checked=(s.stages||[]).includes(c.value));
  const readonly=!!s.builtin;
  ['skill-edit-name','skill-edit-description','skill-edit-content'].forEach(id=>$(id).readOnly=readonly);
  document.querySelectorAll('.skill-stage-check').forEach(c=>c.disabled=readonly);
  $('skill-copy-btn').classList.toggle('hidden',!readonly);
  $('skill-save-btn').classList.toggle('hidden',readonly);$('skill-delete-btn').classList.toggle('hidden',readonly);
}
function newSkillForm(){
  CURRENT_SKILL_ID='';SKILL_NEW=true;renderSkillsList();$('skills-empty').classList.add('hidden');$('skills-editor').classList.remove('hidden');
  $('skills-editor-kind').textContent='新建';$('skills-editor-id').textContent='尚未保存';
  $('skill-edit-name').value='';$('skill-edit-description').value='';$('skill-edit-content').value='';
  document.querySelectorAll('.skill-stage-check').forEach(c=>{c.disabled=false;c.checked=c.value==='video_prompt';});
  ['skill-edit-name','skill-edit-description','skill-edit-content'].forEach(id=>$(id).readOnly=false);
  $('skill-copy-btn').classList.add('hidden');$('skill-save-btn').classList.remove('hidden');$('skill-delete-btn').classList.add('hidden');$('skill-edit-name').focus();
}
function copyCurrentSkill(){
  const sourceName=$('skill-edit-name')?.value.trim()||'未命名 Skill';
  const sourceDescription=$('skill-edit-description')?.value.trim()||'';
  const sourceContent=$('skill-edit-content')?.value||'';
  const sourceStages=[...document.querySelectorAll('.skill-stage-check:checked')].map(x=>x.value);
  newSkillForm();
  $('skill-edit-name').value=`${sourceName}（副本）`;
  $('skill-edit-description').value=sourceDescription;
  $('skill-edit-content').value=sourceContent;
  document.querySelectorAll('.skill-stage-check').forEach(c=>{c.checked=sourceStages.includes(c.value);});
  $('skills-editor-status').textContent='已复制为自定义 Skill，保存后生效';
  $('skill-edit-name').focus();
}
async function saveCurrentSkill(){
  const stages=[...document.querySelectorAll('.skill-stage-check:checked')].map(x=>x.value);
  const body={name:$('skill-edit-name').value.trim(),description:$('skill-edit-description').value.trim(),content:$('skill-edit-content').value,stages};
  if(!body.name||!body.content.trim()){alert('请填写 Skill 名称和内容');return;}
  const url=SKILL_NEW?'/api/skills':`/api/skills/${encodeURIComponent(CURRENT_SKILL_ID)}`;
  const r=await fetch(url,{method:SKILL_NEW?'POST':'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok||!d.ok){alert(d.msg||'保存 Skill 失败');return;}
  CURRENT_SKILL_ID=d.skill.id;SKILL_NEW=false;await loadSkills($('prompt-skill-mode')?.value,$('script-skill-mode')?.value);selectSkill(CURRENT_SKILL_ID);
  $('skills-editor-status').textContent='已保存';
}
async function deleteCurrentSkill(){
  if(!CURRENT_SKILL_ID||!confirm('确定删除当前自定义 Skill？'))return;
  const r=await fetch(`/api/skills/${encodeURIComponent(CURRENT_SKILL_ID)}`,{method:'DELETE'}),d=await r.json();
  if(!r.ok||!d.ok){alert(d.msg||'删除 Skill 失败');return;}
  CURRENT_SKILL_ID='';$('skills-editor').classList.add('hidden');$('skills-empty').classList.remove('hidden');await loadSkills();
}
async function importSkillFile(input){
  const file=input?.files?.[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  const r=await fetch('/api/skills/import',{method:'POST',body:fd}),d=await r.json().catch(()=>({}));
  if(!r.ok||!d.ok){alert(d.msg||'导入 Skill 失败');input.value='';return;}
  await loadSkills(d.skill.id,d.skill.stages?.includes('video_prompt')?d.skill.id:$('prompt-skill-mode')?.value);
  await selectSkill(d.skill.id);input.value='';
}
function openSkillsManager(){loadSkills($('prompt-skill-mode')?.value,$('script-skill-mode')?.value);$('skills-modal').classList.replace('hidden','flex');}
function closeSkillsManager(){$('skills-modal').classList.replace('flex','hidden');}

// ---------- V2 导演台 / 本地草稿 / 使用体验 ----------
const DRAFT_KEY='garen_shortdrama_v2_draft'+(window.PLATFORM?.user?':'+PLATFORM.user.id:'');
const LAST_VIEW_KEY='garen_shortdrama_v2_last_view'+(window.PLATFORM?.user?':'+PLATFORM.user.id:'');
function directorIds(){return ['director-platform','director-length','director-genre','director-pace','prompt-skill-mode','script-skill-mode','director-hook','director-reversal','director-ending','director-dialogue','director-payoff','director-consistency','series-mode','series-name','episode-no','prev-summary'];}
function directorSignature(){
  const values={idea:normalizeStoryText($('idea')?.value).trim(),style:getStyleValue(),shotDuration:$('shotDuration')?.value,shotCount:$('shotCount')?.value,resolution:$('resolution')?.value};
  directorIds().forEach(id=>{const el=$(id);values[id]=el?.type==='checkbox'?!!el.checked:(el?.value||'');});
  return JSON.stringify(values);
}
function setDirectorField(id,value){
  const el=$(id);
  if(!el||value===undefined||value===null)return;
  if(el.type==='checkbox')el.checked=!!value;
  else if([...el.options||[]].length===0||[...el.options].some(o=>o.value===String(value)||o.text===String(value)))el.value=String(value);
}
function hydrateDirectorFromIdea(text){
  const source=String(text||'');
  const brief=source.split(/\n\s*【短剧导演简报】/)[1]||'';
  if(!brief.trim())return false;
  const read=(label)=>{const match=brief.match(new RegExp('^'+label+'：([^\\n]*)','m'));return match?match[1].trim():'';};
  const platform=read('发布平台');
  const length=read('目标成片时长').replace(/[^\d]/g,'');
  const genre=read('剧情类型');
  const pace=read('节奏');
  const hook=read('黄金3秒策略');
  const reversal=read('反转强度');
  const ending=read('结尾策略');
  const dialogue=read('对白密度');
  const payoff=read('核心爽点/必拍桥段');
  const series=brief.match(/^连续剧：是；剧名《([^》]+)》；第(\d+)集/m);
  setDirectorField('director-platform',platform);
  setDirectorField('director-length',length);
  setDirectorField('director-genre',genre);
  setDirectorField('director-pace',pace);
  setDirectorField('director-hook',hook);
  setDirectorField('director-reversal',reversal);
  setDirectorField('director-ending',ending);
  setDirectorField('director-dialogue',dialogue);
  if(payoff)setDirectorField('director-payoff',payoff);
  setDirectorField('series-mode',!!series);
  if(series){setDirectorField('series-name',series[1]);setDirectorField('episode-no',series[2]);}
  toggleSeriesMode();
  return true;
}
function hydrateDirectorFromProject(project){
  const matched=hydrateDirectorFromIdea(project?.idea||'');
  const cfg=project?.render_config||{};
  if(cfg.style){
    if([...$('style').options].some(o=>o.value===cfg.style||o.text===cfg.style))$('style').value=cfg.style;
    else {$('style').value='__custom__';$('styleCustom').value=cfg.style;}
    toggleCustomStyle();
  }
  if(cfg.shot_duration!==undefined)$('shotDuration').value=String(cfg.shot_duration);
  if(cfg.shot_count!==undefined)$('shotCount').value=String(cfg.shot_count);
  if(cfg.prompt_skill_mode!==undefined)$('prompt-skill-mode').value=String(cfg.video_skill_id||cfg.prompt_skill_mode);
  if($('script-skill-mode'))$('script-skill-mode').value=String(cfg.script_skill_id||'auto');
  loadSkills(String(cfg.video_skill_id||cfg.prompt_skill_mode||'auto'),String(cfg.script_skill_id||'auto'));
  if(cfg.aspect_ratio)setResolutionUI(cfg.aspect_ratio,Number(cfg.megapixels)||0.4);
  updateDirectorPreview();
  return matched;
}
function setDirectorStatus(text,kind='muted'){
  const el=$('director-match-status');if(!el)return;
  el.textContent=text;
  el.className='text-xs '+(kind==='ok'?'text-green-400':kind==='warn'?'text-yellow-300':kind==='error'?'text-red-400':'text-gray-500');
}
function invalidateDirectorMatch(storyChanged=false){
  if(applyingDirectorMatch)return;
  if(directorConfirmedSignature&&directorConfirmedSignature===directorSignature())return;
  directorConfirmedSignature='';
  const button=$('director-confirm-btn');
  if(storyChanged){
    directorMatched=false;
    if(button)button.disabled=true;
    setDirectorStatus('故事已变化，请重新让 AI 匹配','warn');
  }else if(directorMatched){
    if(button)button.disabled=false;
    setDirectorStatus('方案已调整，请再次确认','warn');
  }
}
async function autoMatchDirector(){
  const idea=$('idea').value.trim();
  if(idea.length<6){alert('请先输入较完整的故事梗概');$('idea').focus();return;}
  const button=$('director-match-btn');button.disabled=true;button.textContent='AI 分析中…';setDirectorStatus('正在分析人物、冲突和传播节奏…','warn');
  try{
    const response=await fetch('/api/director/match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea})});
    const raw=await response.text();
    let result;
    try{result=JSON.parse(raw);}
    catch(e){
      const html=/^\s*</.test(raw);
      throw new Error(html
        ? `导演匹配接口返回了网页错误（HTTP ${response.status}），请重启短剧服务后刷新页面`
        : `导演匹配接口返回格式异常（HTTP ${response.status}）`);
    }
    if(!response.ok||!result.ok)throw new Error(result.msg||'匹配失败');
    const d=result.director||{},set=(id,value)=>{if($(id)&&value!==undefined)$(id).value=String(value);};
    applyingDirectorMatch=true;
    set('director-platform',d.platform);set('director-length',d.length);set('director-genre',d.genre);set('director-pace',d.pace);
    set('director-hook',d.hook);set('director-reversal',d.reversal);set('director-ending',d.ending);set('director-dialogue',d.dialogue);
    set('director-payoff',d.payoff);set('shotCount',d.shot_count);set('shotDuration',d.shot_duration);
    if(d.style&&[...$('style').options].some(o=>o.value===d.style||o.text===d.style))$('style').value=d.style;
    setResolutionUI(d.aspect_ratio||'9:16 (Portrait)',0.4);
    $('series-mode').checked=!!d.series_mode;toggleSeriesMode();
    if(d.series_mode&&!$('series-name').value.trim())$('series-name').value='未命名系列';
    applyingDirectorMatch=false;
    directorMatched=true;directorConfirmedSignature='';
    $('director-confirm-btn').disabled=false;
    setDirectorStatus(`AI 已匹配${d.reason?'：'+d.reason:''}`,'ok');
    updateDirectorPreview();queueDraftSave();syncMainConfig();
  }catch(error){
    applyingDirectorMatch=false;directorMatched=false;$('director-confirm-btn').disabled=true;
    setDirectorStatus(error.message,'error');alert('AI 导演匹配失败：'+error.message);
  }finally{button.disabled=false;button.textContent='AI 自动匹配导演台';}
}
function confirmDirectorSettings(){
  if(!directorMatched){alert('请先点击“AI 自动匹配导演台”');return;}
  if($('series-mode').checked&&!$('series-name').value.trim()){alert('已匹配为连续剧，请填写剧名');$('series-name').focus();return;}
  directorConfirmedSignature=directorSignature();
  setDirectorStatus('导演方案已确认，可以生成剧本','ok');
  $('director-confirm-btn').disabled=true;
  flashDraftStatus('导演方案已确认');saveDraft();
}
function toggleDirectorPanel(){const body=$('director-body');const hide=!body.classList.contains('hidden');body.classList.toggle('hidden',hide);$('director-toggle').textContent=hide?'展开':'收起';}
function toggleSeriesMode(){const on=$('series-mode').checked;['series-name','episode-no','prev-summary'].forEach(id=>$(id).classList.toggle('hidden',!on));updateDirectorPreview();queueDraftSave();}
function applyDirectorPreset(name,btn){
  document.querySelectorAll('.director-chip').forEach(x=>x.classList.remove('active'));if(btn)btn.classList.add('active');
  const set=(id,v)=>{if($(id))$(id).value=v;};
  if(name==='douyin60'){set('director-platform','抖音');set('director-length','60');set('director-genre','爽剧 / 逆袭');set('director-pace','快：2~5秒一信息点');set('director-hook','先给结果，再解释原因');set('director-reversal','中：至少2次认知变化');set('director-ending','卡在最大悬念，逼追下一集');set('director-dialogue','中：对白推动剧情');setResolutionUI('9:16 (Portrait)',0.4);$('shotCount').value='10';$('shotDuration').value='auto';}
  if(name==='reverse30'){set('director-platform','抖音');set('director-length','30');set('director-genre','悬疑反转');set('director-pace','快：2~5秒一信息点');set('director-hook','直接爆发冲突');set('director-reversal','强：前后身份/局势翻盘');set('director-ending','强爽点收尾');set('director-dialogue','高：强对白/短句交锋');setResolutionUI('9:16 (Portrait)',0.4);$('shotCount').value='6';$('shotDuration').value='auto';}
  if(name==='story90'){set('director-platform','抖音');set('director-length','90');set('director-genre','都市情感');set('director-pace','剧情：6~10秒一信息点');set('director-hook','情绪崩溃瞬间');set('director-reversal','中：至少2次认知变化');set('director-ending','本集闭环 + 新危机');set('director-dialogue','中：对白推动剧情');setResolutionUI('9:16 (Portrait)',0.5);$('shotCount').value='12';$('shotDuration').value='auto';}
  if(name==='serial'){set('director-platform','抖音');set('director-length','60');set('director-genre','系统流');set('director-pace','中快：4~7秒一信息点');set('director-hook','巨大金额/身份反差');set('director-reversal','中：至少2次认知变化');set('director-ending','卡在最大悬念，逼追下一集');$('series-mode').checked=true;toggleSeriesMode();setResolutionUI('9:16 (Portrait)',0.4);$('shotCount').value='10';}
  updateDirectorPreview();queueDraftSave();syncMainConfig();invalidateDirectorMatch(false);
}
function buildDirectorBrief(){
  const get=id=>$(id)?.value?.trim?.()||'';
  const lines=[
    '【短剧导演简报】',
    `发布平台：${get('director-platform')}`,
    `目标成片时长：约${get('director-length')}秒`,
    `画面风格：${getStyleValue()||'电影写实'}`,
    `画幅：${get('resolution').split('|')[0]||'9:16 (Portrait)'}`,
    `镜头数：${get('shotCount')==='auto'?'由AI按故事节奏决定':get('shotCount')+'个'}；单镜时长：${get('shotDuration')==='auto'?'由AI按动作和台词决定':get('shotDuration')+'秒'}`,
    `视频提示词技能：${({'auto':'自动识别','dialogue':'MiniMax 文戏','action':'MiniMax 武戏','anime_action':'二次元武戏','none':'基础 H3'})[get('prompt-skill-mode')]||'自动识别'}`,
    `剧情类型：${get('director-genre')}`,
    `节奏：${get('director-pace')}`,
    `黄金3秒策略：${get('director-hook')}`,
    `反转强度：${get('director-reversal')}`,
    `结尾策略：${get('director-ending')}`,
    `对白密度：${get('director-dialogue')}`,
    `核心爽点/必拍桥段：${get('director-payoff')||'根据故事自动提炼，但必须在中段前出现第一次明确回报'}`,
    `角色一致性：${$('director-consistency')?.checked?'强约束；五官、发型、年龄和体型保持一致；同一场连续戏服装连续，跨时间和活动合理换装；每镜逐角色写明具体服装，避免全剧固定一套衣服':'普通'}`,
  ];
  if($('series-mode')?.checked){lines.push(`连续剧：是；剧名《${get('series-name')||'未命名系列'}》；第${get('episode-no')||1}集`);if(typeof SERIES_CURRENT!=='undefined'&&SERIES_CURRENT?.id)lines.push(`系列ID：${SERIES_CURRENT.id}`);if(get('prev-summary'))lines.push(`上一集承接：${get('prev-summary')}`);}
  lines.push('结构硬要求：');
  lines.push('1. 0~3秒必须出现结果、冲突、危险、金额、身份反差或反常识信息之一，禁止用空镜和慢铺垫开场。');
  lines.push('2. 每4~8秒至少推进一次新信息、人物关系、目标、阻碍或情绪变化；避免连续镜头表达同一件事。');
  lines.push('3. 台词尽量短句、口语化、可表演；能用动作表达的不要让旁白解释。');
  lines.push('4. 中段必须有一次明显局势变化；如设置为中/强反转，则至少安排两次观众认知变化。');
  lines.push('5. 每个镜头都要写清主体、动作、情绪、景别/机位、环境连续性，并服务剧情，不做无意义炫技镜头。');
  lines.push('6. 结尾严格执行所选结尾策略；连载模式必须留下具体未解决事件，而不是泛泛“欲知后事如何”。');
  return lines.join('\n');
}
function buildDirectorIdea(raw){return `${raw.trim()}\n\n${buildDirectorBrief()}`;}
function stripDirectorBrief(text){return String(text||'').split(/\n\s*【短剧导演简报】/)[0].trim();}
function updateDirectorPreview(){if($('director-preview'))$('director-preview').textContent=buildDirectorBrief();}
async function copyDirectorBrief(){try{await navigator.clipboard.writeText(buildDirectorBrief());flashDraftStatus('导演简报已复制');}catch(e){}}
function normalizeStoryText(value){return String(value??'').replace(/\r\n?/g,'\n').split('\n').filter(line=>line.trim()!=='').join('\n');}
function setStoryText(value){const text=normalizeStoryText(value);$('idea').value=text;return text;}
let storyChatState={story:'',history:[],undo:null}, storyChatBusy=false;
function openStoryEdit(){
  syncStoryChat();
  loadStoryChatModels();
  $('story-edit-modal').classList.replace('hidden','flex');
  AIChat.resize($('story-chat-input'));
  $('story-chat-input').focus();
}
function closeStoryEdit(){
  $('story-edit-modal').classList.replace('flex','hidden');
  $('story-chat-open')?.focus();
}
async function loadStoryChatModels(){
  const select=$('story-chat-model');if(!select)return;
  try{
    const data=await fetchAvailableLLMModels(),selected=select.value;
    const models=[...new Set((data.models||[]).filter(Boolean))];
    select.replaceChildren(new Option(data.current?`使用当前 LLM（${data.current}）`:'使用当前 LLM',''),...models.map(model=>new Option(model,model)));
    select.value=models.includes(selected)?selected:'';
  }catch(_){select.title='模型列表获取失败，可使用当前 LLM';}
}
function editStoryText(text){
  $('idea').value=text;
  $('idea').dispatchEvent(new Event('input',{bubbles:true}));
}
function syncStoryChat(){
  const story=$('idea').value;
  if($('story-edit-text')&&$('story-edit-text').value!==story)$('story-edit-text').value=story;
  if(storyChatState.story!==story)storyChatState={story,history:[],undo:null};
  renderStoryChat();
}
function renderStoryChat(){
  const box=$('story-chat-messages');if(!box)return;
  AIChat.render(box,storyChatState.history);
  $('story-chat-undo').disabled=storyChatBusy||!storyChatState.undo;
}
function applyStoryChatText(text,fullScript){
  setStoryText(text);
  importedFullScript=fullScript?$('idea').value:'';
  $('script-import-clear')?.classList.toggle('hidden',!fullScript);
  if($('script-import-status'))$('script-import-status').textContent=fullScript?'完整剧本已由 AI 修改':'支持 TXT、Markdown、DOCX；导入后会保留原剧情进行结构化';
  storyChatState.story=$('idea').value;
  updateIdeaCount();invalidateDirectorMatch(true);saveDraft();updateDirectorPreview();
}
function undoStoryChat(){
  syncStoryChat();const previous=storyChatState.undo;if(storyChatBusy||!previous)return;
  storyChatState.history=previous.history;storyChatState.undo=null;
  applyStoryChatText(previous.story,previous.fullScript);renderStoryChat();
  $('story-chat-status').textContent='已撤销上次 AI 修改并保存草稿';
}
async function sendStoryChat(){
  if(storyChatBusy)return;
  syncStoryChat();
  const input=$('story-chat-input'),message=input.value.trim(),story=$('idea').value;
  const status=$('story-chat-status');
  if(!story.trim()||!message){status.textContent=!story.trim()?'请先输入故事正文':'请输入修改要求';return;}
  const state=storyChatState,pid=currentPid,history=state.history.slice(),fullScript=!!importedFullScript&&story===importedFullScript;
  storyChatBusy=true;$('story-chat-send').disabled=true;input.disabled=true;
  state.history.push({role:'user',content:message});renderStoryChat();status.textContent='AI 正在修改故事…';
  try{
    const response=await fetch('/api/story/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea:story,message,history,model:$('story-chat-model')?.value||''})});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.msg||'AI 修改失败');
    if(typeof result.story!=='string'||!result.story.trim())throw new Error('AI 没有返回故事正文');
    if(state!==storyChatState||pid!==currentPid||$('idea').value!==story){
      status.textContent='正文或项目已变化，未自动覆盖。AI 结果保留在下方，可复制。';
      const preview=document.createElement('textarea');preview.readOnly=true;preview.value=result.story;
      preview.className='w-full bg-black/30 rounded-lg p-3 text-sm mt-3';preview.rows=6;preview.setAttribute('aria-label','未应用的 AI 修改结果');
      $('story-chat-messages').append(preview);return;
    }
    state.undo={story,fullScript,history};state.history.push({role:'assistant',content:result.reply||'已更新故事正文。'});
    state.history=state.history.slice(-20);
    applyStoryChatText(result.story,fullScript);input.value='';status.textContent='故事已更新并保存，可继续提出修改要求';
  }catch(error){
    if(state===storyChatState){state.history=history;renderStoryChat();}
    status.textContent='修改失败：'+error.message;
  }finally{
    storyChatBusy=false;$('story-chat-send').disabled=false;input.disabled=false;
    $('story-chat-undo').disabled=!storyChatState.undo;
  }
}
function updateIdeaCount(){if($('idea-count'))$('idea-count').textContent=`${$('idea').value.length} 字`;syncStoryChat();}
let importedFullScript='';
async function importFullScript(input){
  const file=input?.files?.[0];input.value='';if(!file)return;
  const status=$('script-import-status');status.textContent='正在读取剧本…';status.className='text-xs text-yellow-300';
  try{
    let text='';
    if(file.name.toLowerCase().endsWith('.docx')){
      const form=new FormData();form.append('file',file);
      const response=await fetch('/api/script/import-text',{method:'POST',body:form});
      const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.msg||'DOCX读取失败');text=result.text||'';
    }else text=await file.text();
    text=normalizeStoryText(text).trim();
    if(text.length<20)throw new Error('剧本内容过短，请检查文件');
    importedFullScript=text;setStoryText(text);updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);
    $('script-import-clear').classList.remove('hidden');status.textContent=`已导入 ${file.name} · ${text.length} 字，将按原剧本结构化`;status.className='text-xs text-green-400';
    $('idea').scrollIntoView({behavior:'smooth',block:'center'});
  }catch(error){status.textContent=error.message;status.className='text-xs text-red-300';}
}
function clearImportedScript(){
  importedFullScript='';$('idea').value='';updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);
  $('script-import-clear').classList.add('hidden');$('script-import-status').textContent='支持 TXT、Markdown、DOCX；导入后会保留原剧情进行结构化';$('script-import-status').className='text-xs text-gray-500';
}
function collectDraft(){const d={storyChat:storyChatState,directorMatched,directorConfirmedSignature,generationReference,idea:$('idea').value,fullScriptImport:!!importedFullScript&&$('idea').value===importedFullScript,style:$('style').value,styleCustom:$('styleCustom').value,shotDuration:$('shotDuration').value,shotCount:$('shotCount').value,shotRulesVersion:2,resolution:$('resolution').value,h3Steps:$('h3Steps').value,customAssets:$('customAssets').checked,manualMode:$('manualMode').checked,promptBatchMode:$('promptBatchMode').checked,subtitleEnabled:$('subtitleEnabled').checked};directorIds().forEach(id=>{const el=$(id);if(el)d[id]=el.type==='checkbox'?el.checked:el.value;});return d;}
function saveDraft(){try{localStorage.setItem(DRAFT_KEY,JSON.stringify(collectDraft()));flashDraftStatus('草稿已保存');}catch(e){}}
function saveLastView(){
  if(!currentPid)return;
  try{
    const data={
      pid:String(currentPid),
      scrollY:Math.max(0,Math.round(window.scrollY||0)),
      savedAt:Date.now()
    };
    localStorage.setItem(LAST_VIEW_KEY,JSON.stringify(data));
    const url=new URL(window.location.href);
    url.hash=`project=${encodeURIComponent(data.pid)}&scrollY=${data.scrollY}`;
    history.replaceState({lastView:data},'',url.toString());
  }catch(e){}
}
function clearLastView(){
  try{localStorage.removeItem(LAST_VIEW_KEY);}catch(e){}
  try{
    const url=new URL(window.location.href);
    url.hash='';
    history.replaceState({},'',url.toString());
  }catch(e){}
}
function readLastView(){
  try{
    const value=JSON.parse(localStorage.getItem(LAST_VIEW_KEY)||'null');
    return value&&value.pid?value:null;
  }catch(e){}
  try{
    const hash=String(window.location.hash||'').replace(/^#/,'');
    const params=new URLSearchParams(hash);
    const pid=params.get('project');
    if(pid)return {pid,scrollY:Number(params.get('scrollY'))||0};
  }catch(e){}
  return window.history.state?.lastView||null;
}
async function restoreLastView(){
  const last=readLastView();
  if(!last)return;
  restoringLastView=true;
  try{
    await openProject(String(last.pid),{restoreScrollY:Number(last.scrollY)||0});
  }catch(e){
    clearLastView();
  }finally{
    restoringLastView=false;
  }
}
function queueDraftSave(){clearTimeout(draftTimer);draftTimer=setTimeout(saveDraft,500);updateDirectorPreview();}
function flashDraftStatus(t){if(!$('draft-status'))return;$('draft-status').textContent=t;clearTimeout(window._draftFlash);window._draftFlash=setTimeout(()=>{$('draft-status').textContent='草稿自动保存';},1600);}
function restoreDirectorDraftState(d){
  directorMatched=!!d.directorMatched;
  directorConfirmedSignature='';
  if(!directorMatched&&!d.fullScriptImport&&d.idea)directorMatched=hydrateDirectorFromIdea(d.idea);
  if(directorMatched&&d.directorConfirmedSignature===directorSignature()){
    directorConfirmedSignature=d.directorConfirmedSignature;
    setDirectorStatus('已恢复已确认的导演方案，可以生成剧本','ok');
  }else if(directorMatched){
    setDirectorStatus('已恢复导演方案，请确认后生成剧本','warn');
  }else setDirectorStatus('输入梗概后先让 AI 匹配');
  $('director-confirm-btn').disabled=!directorMatched||!!directorConfirmedSignature;
}
function restoreDraft(silent=false){try{const raw=localStorage.getItem(DRAFT_KEY);if(!raw){if(!silent)flashDraftStatus('暂无本地草稿');return;}const d=JSON.parse(raw);if(d.storyChat&&d.storyChat.story===d.idea&&Array.isArray(d.storyChat.history))storyChatState=d.storyChat;setGenerationReference(d.generationReference||null);const legacyRules=Number(d.shotRulesVersion||0)<2;const normalizedIdea=normalizeStoryText(d.idea??'');if(d.idea!==undefined)setStoryText(normalizedIdea);if(d.fullScriptImport&&normalizedIdea){importedFullScript=normalizedIdea;$('script-import-clear')?.classList.remove('hidden');if($('script-import-status'))$('script-import-status').textContent='已恢复完整剧本草稿';}if(d.style!==undefined)$('style').value=d.style;if(d.styleCustom!==undefined)$('styleCustom').value=d.styleCustom;['shotDuration','shotCount','resolution','h3Steps'].forEach(id=>{if(d[id]!==undefined&&$(id)){let value=String(d[id]);if(legacyRules&&(id==='shotDuration'||id==='shotCount'))value='auto';if(id==='shotDuration'&&value!=='auto'&&(parseInt(value)||0)<8)value='auto';$(id).value=value;}});['customAssets','manualMode'].forEach(id=>{if(d[id]!==undefined)$(id).checked=!!d[id];});if(d.subtitleEnabled!==undefined)$('subtitleEnabled').checked=!!d.subtitleEnabled;$('promptBatchMode').checked=true;directorIds().forEach(id=>{if(d[id]===undefined||!$(id))return;$(id).type==='checkbox'?$(id).checked=!!d[id]:$(id).value=d[id]??'';});renderSkillSelectors(d['prompt-skill-mode']||'auto',d['script-skill-mode']||'auto');toggleCustomStyle();toggleSeriesMode();updateIdeaCount();updateDirectorPreview();restoreDirectorDraftState(d);if(!silent)flashDraftStatus('已恢复草稿');}catch(e){if(!silent)flashDraftStatus('草稿恢复失败');}}
function clearDraft(){if(!confirm('清空当前创意和本地草稿？'))return;localStorage.removeItem(DRAFT_KEY);setGenerationReference(null);$('idea').value='';$('director-payoff').value='';updateIdeaCount();updateDirectorPreview();flashDraftStatus('已清空');}
async function openTomatoDownloader(){
  // 在用户点击时立即创建窗口，避免等待服务启动后被浏览器拦截。
  const popup=window.open('about:blank','_blank');
  if(popup)popup.opener=null;
  const button=document.querySelector('button[onclick="openTomatoDownloader()"]');
  if(button){button.disabled=true;button.textContent='⏳ 启动下载器…';}
  try{
    const response=await fetch('/api/tomato-downloader/start',{method:'POST'});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.msg||'番茄下载器启动失败');
    const url=result.url||`http://${location.hostname}:18423/`;
    if(popup&&!popup.closed)popup.location.href=url;
    else alert(`下载器已启动，请打开：${url}`);
  }catch(error){
    if(popup&&!popup.closed)popup.close();
    alert(error.message||'番茄下载器启动失败');
  }finally{
    if(button){button.disabled=false;button.textContent='📚 番茄下载';}
  }
}
let NOVEL_BOOKS=[],NOVEL_CURRENT=null,NOVEL_CHAPTERS=[],NOVEL_CHAPTER_INDEX=0,NOVEL_SELECTED_CHAPTERS=new Set(),NOVEL_HIGHLIGHTS_CACHE=[];
function closeNovelViewer(){$('novel-viewer-modal').classList.replace('flex','hidden');}
async function openNovelViewer(){
  $('novel-viewer-modal').classList.replace('hidden','flex');
  await Promise.all([loadNovelBooks(),loadNovelQueueSeries()]);
}
async function loadNovelQueueSeries(){
  const select=$('novel-queue-series');
  if(!select)return;
  try{
    const result=await(await fetch('/api/series')).json();
    const list=Array.isArray(result)?result:[];
    DRAMA_PROJECT_LIST=list;
    select.replaceChildren(new Option('请选择目标剧项目',''));
    list.forEach(item=>select.add(new Option(`${item.name||'未命名剧'} · ${item.episode_count||0}集`,item.id)));
    const preferred=SERIES_CURRENT?.id||list.find(item=>item.name===NOVEL_CURRENT?.title)?.id;
    if(preferred&&list.some(item=>item.id===preferred))select.value=preferred;
    updateNovelQueueStartEpisode();
  }catch(error){
    select.replaceChildren(new Option('剧项目读取失败',''));
  }
}
function updateNovelQueueStartEpisode(){
  const select=$('novel-queue-series'),input=$('novel-queue-start-episode');
  if(!select||!input)return;
  const item=DRAMA_PROJECT_LIST.find(x=>String(x.id)===String(select.value));
  if(item?.episode_count)input.value=Number(item.episode_count)+1;
}
function selectNovelAllChapters(){
  if(!NOVEL_CHAPTERS.length)return;
  NOVEL_SELECTED_CHAPTERS=new Set(NOVEL_CHAPTERS.map(chapter=>chapter.index));
  document.querySelectorAll('#novel-chapter-list input[type="checkbox"]').forEach(box=>{box.checked=true;});
  $('novel-selected-count').textContent=`已选${NOVEL_SELECTED_CHAPTERS.size}章`;
}
function renderNovelBooks(){
  const query=($('novel-book-search')?.value||'').trim().toLowerCase();
  const list=NOVEL_BOOKS.filter(book=>!query||`${book.title} ${book.author} ${book.file_name}`.toLowerCase().includes(query));
  $('novel-book-count').textContent=`${list.length}本`;
  $('novel-book-list').innerHTML=list.length?list.map(book=>`
    <button type="button" data-novel-file="${escapeHtml(book.file_name)}" onclick="event.preventDefault();event.stopPropagation();selectNovelBook(this.dataset.novelFile)" class="novel-chapter-item w-full text-left ${NOVEL_CURRENT?.file_name===book.file_name?'active':''}">
      <div class="font-bold truncate">${escapeHtml(book.title||book.file_name)}</div>
      <div class="text-[10px] text-gray-500 mt-1">${escapeHtml(book.author||'作者未知')} · ${book.chapter_count||0}章 · ${String(book.format||'').toUpperCase()}</div>
    </button>`).join(''):'<div class="workspace-muted">暂无已下载的 EPUB/TXT 小说</div>';
}
async function loadNovelBooks(){
  $('novel-book-list').innerHTML='<div class="workspace-muted">正在读取小说库…</div>';
  try{
    const result=await(await fetch('/api/novel-viewer/books')).json();
    if(!result.ok)throw new Error(result.msg||'读取失败');
    NOVEL_BOOKS=result.books||[];renderNovelBooks();
    if(NOVEL_CURRENT&&NOVEL_BOOKS.some(book=>book.file_name===NOVEL_CURRENT.file_name))await selectNovelBook(NOVEL_CURRENT.file_name,true);
  }catch(error){$('novel-book-list').innerHTML=`<div class="text-xs text-red-300 p-2">${escapeHtml(error.message)}</div>`;}
}
async function selectNovelBook(fileName,keepChapter=false){
  $('novel-reader-title').textContent='正在打开小说…';
  $('novel-reader-content').textContent='正在读取目录，请稍候…';
  try{
    const result=await(await fetch(`/api/novel-viewer/book?file=${encodeURIComponent(fileName)}`)).json();
    if(!result.ok)throw new Error(result.msg||'打开小说失败');
    NOVEL_CURRENT={file_name:fileName,...(result.book||{})};NOVEL_CHAPTERS=result.chapters||[];NOVEL_SELECTED_CHAPTERS=new Set();
    $('novel-meta').innerHTML=`<div class="font-bold text-sm gold truncate">${escapeHtml(NOVEL_CURRENT.title||fileName)}</div><div class="mt-1">${escapeHtml(NOVEL_CURRENT.author||'作者未知')} · ${NOVEL_CHAPTERS.length}章</div>`;
    const scope=$('novel-highlight-scope');
    scope.replaceChildren(new Option('当前章节','current'),new Option('选中章节','selected'));
    for(let start=1;start<=NOVEL_CHAPTERS.length;start+=100){
      const end=Math.min(start+99,NOVEL_CHAPTERS.length);
      scope.add(new Option(`第 ${start}–${end} 章`,`range:${start}:${end}`));
    }
    scope.add(new Option('整本小说','all'));
    scope.value='current';
    $('novel-chapter-list').innerHTML=NOVEL_CHAPTERS.map(chapter=>`
      <div class="flex items-center gap-1 ${NOVEL_CHAPTER_INDEX===chapter.index?'active':''}">
        <input type="checkbox" class="accent-yellow-500 shrink-0" title="选择本章用于AI分析" onchange="toggleNovelChapter(${chapter.index},this.checked);event.stopPropagation()">
        <button type="button" onclick="selectNovelChapter(${chapter.index})" class="novel-chapter-item flex-1 text-left">
        ${chapter.index}. ${escapeHtml(chapter.title)} <span class="text-[10px] text-gray-600">(${chapter.length}字)</span>
        </button>
      </div>`).join('');
    renderNovelBooks();
    await loadNovelQueueSeries();
    const index=keepChapter?Math.min(Math.max(NOVEL_CHAPTER_INDEX,1),NOVEL_CHAPTERS.length):1;
    await selectNovelChapter(index);
  }catch(error){$('novel-reader-content').textContent=error.message||'打开小说失败';}
}
function toggleNovelChapter(index,checked){
  if(checked)NOVEL_SELECTED_CHAPTERS.add(index);else NOVEL_SELECTED_CHAPTERS.delete(index);
  $('novel-selected-count').textContent=`已选${NOVEL_SELECTED_CHAPTERS.size}章`;
}
async function queueNovelSelectedEpisodes(){
  if(!NOVEL_CURRENT){alert('请先选择一本小说');return;}
  const chapters=novelSelectedChapters(),seriesId=$('novel-queue-series')?.value||'';
  const startEpisode=Math.max(1,parseInt($('novel-queue-start-episode')?.value)||1);
  if(!seriesId){alert('请选择目标剧项目');return;}
  if(!chapters.length){alert('请先勾选要制作的章节');return;}
  const button=$('novel-queue-btn'),status=$('novel-ai-status');
  if(!confirm(`确定把选中的${chapters.length}章创建为第${startEpisode}集开始的连续剧，并加入自动化队列吗？`))return;
  button.disabled=true;status.textContent='正在创建剧集并加入队列…';status.className='text-xs text-yellow-300';
  try{
    const response=await fetch('/api/novel-viewer/queue-series',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:NOVEL_CURRENT.file_name,series_id:seriesId,chapters,start_episode:startEpisode})});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.msg||'批量排队失败');
    status.textContent=`已创建${result.created?.length||0}集，已加入队列`;status.className='text-xs text-green-400';
    await loadDramaProjects(false);refreshRenderQueue();
  }catch(error){status.textContent=error.message||'批量排队失败';status.className='text-xs text-red-400';alert(status.textContent);}
  finally{button.disabled=false;}
}
async function selectNovelChapter(index){
  if(!NOVEL_CURRENT)return;
  try{
    const result=await(await fetch(`/api/novel-viewer/chapter?file=${encodeURIComponent(NOVEL_CURRENT.file_name)}&chapter=${index}`)).json();
    if(!result.ok)throw new Error(result.msg||'读取章节失败');
    NOVEL_CHAPTER_INDEX=result.chapter.index;
    $('novel-reader-title').textContent=result.chapter.title||`第${index}章`;
    $('novel-reader-content').textContent=result.chapter.text||'本章暂无文字';
    document.querySelectorAll('.novel-chapter-item').forEach(item=>item.classList.remove('active'));
    document.querySelectorAll('#novel-chapter-list .novel-chapter-item')[index-1]?.classList.add('active');
    $('novel-reader-content').scrollTop=0;
  }catch(error){$('novel-reader-content').textContent=error.message||'读取章节失败';}
}
function sendCurrentNovelChapterToStory(){
  if(!NOVEL_CURRENT||!NOVEL_CHAPTER_INDEX){
    alert('请先选择一章');return;
  }
  const chapter=NOVEL_CHAPTERS.find(item=>item.index===NOVEL_CHAPTER_INDEX);
  const text=($('novel-reader-content')?.textContent||'').trim();
  if(!text||text==='请选择章节'){
    alert('当前章节没有可发送的正文');return;
  }
  const bookTitle=NOVEL_CURRENT.title||NOVEL_CURRENT.file_name||'小说';
  const chapterTitle=chapter?.title||`第${NOVEL_CHAPTER_INDEX}章`;
  $('idea').value=`《${bookTitle}》·${chapterTitle}\n\n${text}`;
  updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);
  closeNovelViewer();
  $('idea').scrollIntoView({behavior:'smooth',block:'center'});
  $('idea').focus();
  flashDraftStatus(`已将${chapterTitle}发送到故事窗口`);
}
function novelChapterMove(step){
  const next=NOVEL_CHAPTER_INDEX+step;
  if(next>=1&&next<=NOVEL_CHAPTERS.length)selectNovelChapter(next);
}
function novelSelectedChapters(){
  return NOVEL_SELECTED_CHAPTERS.size?[...NOVEL_SELECTED_CHAPTERS].sort((a,b)=>a-b):(NOVEL_CHAPTER_INDEX?[NOVEL_CHAPTER_INDEX]:[]);
}
function novelScopeChapters(){
  const scope=$('novel-highlight-scope')?.value||'current';
  if(scope==='current')return NOVEL_CHAPTER_INDEX?[NOVEL_CHAPTER_INDEX]:[];
  if(scope==='selected')return [...NOVEL_SELECTED_CHAPTERS].sort((a,b)=>a-b);
  if(scope.startsWith('range:')){
    const [,start,end]=scope.split(':').map(Number);
    return Number.isFinite(start)&&Number.isFinite(end)?Array.from({length:end-start+1},(_,offset)=>start+offset):[];
  }
  return [];
}
async function extractNovelHighlights(){
  if(!NOVEL_CURRENT){alert('请先选择一本小说');return;}
  const button=$('novel-highlights-btn'),status=$('novel-ai-status'),output=$('novel-ai-output');
  button.disabled=true;status.textContent='正在提取精彩片段…';status.className='text-xs text-yellow-300';
  try{
    const scope=$('novel-highlight-scope').value;
    let chapters=[];
    if(scope==='current')chapters=[NOVEL_CHAPTER_INDEX];
    else if(scope==='selected')chapters=[...NOVEL_SELECTED_CHAPTERS].sort((a,b)=>a-b);
    else if(scope.startsWith('range:')){
      const [,start,end]=scope.split(':').map(Number);
      chapters=Array.from({length:end-start+1},(_,offset)=>start+offset);
    }
    const result=await(await fetch('/api/novel-viewer/highlights',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:NOVEL_CURRENT.file_name,chapters,scope})})).json();
    if(!result.ok)throw new Error(result.msg||'提取失败');
    NOVEL_HIGHLIGHTS_CACHE=result.highlights||[];
    output.innerHTML=NOVEL_HIGHLIGHTS_CACHE.map((item,index)=>`<div class="novel-highlight"><strong class="gold">${index+1}. ${escapeHtml(item.title||'精彩片段')}</strong><div class="mt-1">${escapeHtml(item.excerpt||'')}</div><div class="mt-1 text-gray-400">精彩原因：${escapeHtml(item.reason||'')}</div><div class="mt-1 text-cyan-300">视频钩子：${escapeHtml(item.hook||'')}</div><div class="flex flex-wrap gap-2 mt-2"><button type="button" onclick="generateNovelExcerptScript(${index})" class="text-xs px-3 py-1.5 rounded glass hover:bg-cyan-400/20 text-cyan-300">📜 按原文生成剧本</button><button type="button" onclick="useNovelHighlight(${index})" class="text-xs px-3 py-1.5 rounded glass hover:bg-yellow-400/20 text-yellow-300">🎬 用此片段创作短剧</button></div></div>`).join('');
    output.classList.remove('hidden');status.textContent=result.scope==='all'?`已完成 · 已分析整本小说（${result.segment_count||0}段）`: `已完成 · 使用第${(result.chapters||[]).join('、')}章`;status.className='text-xs text-green-400';
  }catch(error){status.textContent=error.message||'提取失败';status.className='text-xs text-red-400';alert(status.textContent);}
  finally{button.disabled=false;}
}
function useNovelHighlight(index){
  const item=NOVEL_HIGHLIGHTS_CACHE[index];
  if(!item)return;
  const source=[item.title,item.excerpt,item.hook].filter(Boolean).join('\n');
  $('idea').value=source;
  updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);
  closeNovelViewer();
  $('idea').scrollIntoView({behavior:'smooth',block:'center'});
  $('idea').focus();
  flashDraftStatus('精彩片段已回填，请编辑后匹配导演台');
}
async function generateNovelExcerptScript(index){
  if(!NOVEL_CURRENT)return;
  const item=NOVEL_HIGHLIGHTS_CACHE[index];
  if(!item)return;
  const status=$('novel-ai-status'),output=$('novel-ai-output'),button=document.querySelectorAll('.novel-highlight')[index]?.querySelector('button');
  if(button){button.disabled=true;button.textContent='⏳ 正在调取原文…';}
  status.textContent='正在从原小说章节中定位真实段落并生成剧本…';status.className='text-xs text-yellow-300';
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),180000);
  try{
    const response=await fetch('/api/novel-viewer/excerpt-script',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:NOVEL_CURRENT.file_name,chapters:novelScopeChapters(),highlight:item}),signal:controller.signal});
    const raw=await response.text();
    let result;
    try{result=JSON.parse(raw);}catch(e){throw new Error(`剧本接口返回异常（HTTP ${response.status}），请重试`);}
    if(!response.ok)throw new Error(result.msg||'生成失败');
    if(!result.ok)throw new Error(result.msg||'生成失败');
    output.textContent=result.script||'';output.classList.remove('hidden');
    status.textContent=`原文剧本已生成 · 使用第${(result.chapters||[]).join('、')}章`;status.className='text-xs text-green-400';
  }catch(error){const message=error.name==='AbortError'?'生成超过3分钟，已停止等待；请缩小章节范围后重试':(error.message||'生成失败');status.textContent=message;status.className='text-xs text-red-400';alert(message);}
  finally{clearTimeout(timeout);if(button){button.disabled=false;button.textContent='📜 按原文生成剧本';}}
}
async function generateNovelTrailerScript(){
  if(!NOVEL_CURRENT){alert('请先选择一本小说');return;}
  const button=$('novel-script-btn'),status=$('novel-ai-status'),output=$('novel-ai-output');
  button.disabled=true;status.textContent='AI正在生成剧本…';status.className='text-xs text-yellow-300';
  try{
    const mode=$('novel-script-mode').value;
    const result=await(await fetch('/api/novel-viewer/trailer-script',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:NOVEL_CURRENT.file_name,mode})})).json();
    if(!result.ok)throw new Error(result.msg||'生成失败');
    output.textContent=result.script||'';output.classList.remove('hidden');
    status.textContent=`${mode}剧本已生成 · 已分析整本小说`;status.className='text-xs text-green-400';
  }catch(error){status.textContent=error.message||'生成失败';status.className='text-xs text-red-400';alert(status.textContent);}
  finally{button.disabled=false;}
}
function applyCreationDefaults(){
  $('style').value='电影写实';$('styleCustom').value='';toggleCustomStyle();
  $('shotDuration').value='auto';$('shotCount').value='auto';
  setResolutionUI('16:9 (Widescreen)',0.4);$('h3Steps').value=8;
}
async function newProject(){
  const running=!!es||$('btn-run')?.disabled;
  if(running&&!confirm('当前项目正在生成，确定终止并新建吗？已生成的内容会保留在历史项目中。'))return;
  const hasWork=!!currentPid||!!SCRIPT_DATA||!!$('idea').value.trim();
  if(!running&&hasWork&&!confirm('确定回到初始创作界面吗？当前页面内容和本地草稿会清空，历史项目不会删除。'))return;
  if(running&&currentPid){
    try{await fetch(`/api/pipeline/${encodeURIComponent(currentPid)}/cancel`,{method:'POST'});}catch(e){}
  }
  if(es){es.close();es=null;}
  if(resynthES){resynthES.close();resynthES=null;}
  if(editPoll){clearInterval(editPoll);editPoll=null;}
  localStorage.removeItem(DRAFT_KEY);
  clearLastView();
  window.studioAssetsConfirmed=false;
  setCurrentProjectId(null);setGenerationReference(null);window._projIdea='';window._pendingScriptIdea='';
  ['continue-bar','resynth-bar','assets-confirm-bar','shots-confirm-bar','prompt-batch-bar','render-groups','script-review-bar'].forEach(id=>$(id)?.remove());
  closeScriptPreview();
  ['pipeline-box','script-box','shots-box','final-box'].forEach(id=>$(id)?.classList.add('hidden'));
  $('idea').value='';$('char-list').innerHTML='';$('scene-list').innerHTML='';$('prop-list').innerHTML='';$('shot-grid').innerHTML='';$('log').innerHTML='';
  SERIES_CURRENT=null;$('series-name').value='';$('episode-no').value=1;$('prev-summary').value='';
  $('proj-title').textContent='';SHOT_DATA={};SCRIPT_DATA=null;scriptChatHistory=[];renderScriptChat();directorMatched=false;directorConfirmedSignature='';
  $('director-payoff').value='';$('series-mode').checked=false;toggleSeriesMode();
  updateIdeaCount();updateDirectorPreview();setDirectorStatus('输入梗概后先让 AI 匹配');$('director-confirm-btn').disabled=true;
  applyCreationDefaults();
  renderStages();flashDraftStatus('已回到初始创作界面');
  window.scrollTo({top:0,behavior:'smooth'});
  return true;
}
function clearLogs(){if($('log'))$('log').innerHTML='';}
async function copyLogs(){const text=[...$('log').children].map(x=>x.textContent).join('\n');try{await navigator.clipboard.writeText(text);log('日志已复制','text-green-400');}catch(e){}}
function startRunClock(){runStartedAt=Date.now();clearInterval(runClockTimer);const tick=()=>{const sec=Math.floor((Date.now()-runStartedAt)/1000);const m=Math.floor(sec/60),s=sec%60;if($('run-clock'))$('run-clock').textContent=`已运行 ${m}:${String(s).padStart(2,'0')}`;};tick();runClockTimer=setInterval(tick,1000);}
function stopRunClock(){clearInterval(runClockTimer);runClockTimer=null;}
function initV2UX(){
  initModalScrollGuard();
  const idea=$('idea');idea.addEventListener('paste',()=>setTimeout(()=>{const normalized=normalizeStoryText(idea.value);if(idea.value!==normalized){const end=normalized.length;idea.value=normalized;idea.setSelectionRange(end,end);updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);}},0));idea.addEventListener('input',()=>{if(importedFullScript&&idea.value!==importedFullScript){importedFullScript='';$('script-import-clear')?.classList.add('hidden');if($('script-import-status')){$('script-import-status').textContent='剧本已编辑，当前按故事创意处理';$('script-import-status').className='text-xs text-gray-500';}}updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);});
  document.querySelectorAll('#director-body select,#director-body input').forEach(el=>{el.addEventListener('change',()=>{queueDraftSave();invalidateDirectorMatch(false);});el.addEventListener('input',()=>{queueDraftSave();invalidateDirectorMatch(false);});});
  ['style','styleCustom','shotDuration','shotCount','resolution'].forEach(id=>$(id)?.addEventListener('change',()=>{queueDraftSave();invalidateDirectorMatch(false);}));
  ['h3Steps','customAssets','manualMode','promptBatchMode','subtitleEnabled'].forEach(id=>$(id)?.addEventListener('change',queueDraftSave));
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){if(e.target?.closest('[data-ai-chat],#story-edit-modal'))return;e.preventDefault();if(!$('btn-run').disabled)runPipeline();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveDraft();}if(e.key==='Escape'){if($('story-edit-modal')?.classList.contains('flex'))closeStoryEdit();['nodes-modal','settings-modal','proj-modal','drama-modal','remake-modal','edit-modal','image-edit-modal','single-modal','series-modal','novel-viewer-modal','episode-manager-modal','script-preview-modal','skills-modal'].forEach(id=>{const m=$(id);if(m&&m.classList.contains('flex'))m.classList.replace('flex','hidden');});}});
  restoreDraft(true);
  // 保留草稿中的连续剧设置，避免恢复后改变已确认方案。
  toggleSeriesMode();
  updateIdeaCount();updateDirectorPreview();if(!directorMatched)setDirectorStatus('输入梗概后先让 AI 匹配');
}

// Read the HTTP response before parsing SSE, so rejected requests retain their
// actual server message. Never replay this task-starting request automatically.
class PipelineStream extends EventTarget {
  constructor(url,payload={}){
    super();this.readyState=0;this.controller=new AbortController();
    setTimeout(()=>this.read(url,payload),0);
  }
  close(){this.readyState=2;this.controller.abort();}
  async read(url,payload={}){
    try{
      const form=new FormData();Object.entries(payload||{}).forEach(([key,value])=>{if(value)form.append(key,value);});
      const response=await fetch(url,{method:'POST',headers:window.PLATFORM?.csrf?{'X-CSRF-Token':window.PLATFORM.csrf}:{},body:form,signal:this.controller.signal});
      if(!response.ok){
        const text=await response.text();let message;
        try{
          const data=JSON.parse(text);message=data.msg||data.error;
          if(data.code==='reference_sync_required'){
            this.dispatchEvent(new MessageEvent('reference_sync_required',{data:JSON.stringify(data)}));
            this.close();return;
          }
        }catch{}
        throw new Error(message||`生成请求失败（HTTP ${response.status}），请刷新页面检查登录状态和项目权限`);
      }
      if(!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('生成接口未返回事件流，请刷新页面重新登录');
      this.readyState=1;
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      while(this.readyState!==2){
        const {value,done}=await reader.read();
        if(done)throw new Error('生成连接中断；后台任务可能仍在运行，请重新打开当前项目查看进度');
        buffer+=decoder.decode(value,{stream:true});
        let match;
        while((match=/\r?\n\r?\n/.exec(buffer))){
          const frame=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);
          let event='message';const data=[];
          for(const line of frame.split(/\r?\n/)){
            if(line.startsWith('event:'))event=line.slice(6).trim();
            if(line.startsWith('data:'))data.push(line.slice(5).replace(/^ /,''));
          }
          if(data.length)this.dispatchEvent(new MessageEvent(event,{data:data.join('\n')}));
          if(this.readyState===2)return;
        }
      }
    }catch(error){
      if(this.controller.signal.aborted)return;
      this.dispatchEvent(new MessageEvent('error',{data:JSON.stringify({msg:error.message})}));
      this.close();
    }
  }
}
let scriptProgressTimer=null,scriptProgressStarted=0,scriptProgressActive=false;
function updateScriptProgress(info={}){
  const box=$('script-progress'),bar=$('script-progress-bar');if(!box||!bar)return;
  box.classList.remove('hidden');
  if(info.reset){clearInterval(scriptProgressTimer);scriptProgressStarted=Date.now();scriptProgressActive=true;
    const tick=()=>{$('script-progress-time').textContent=`已用 ${Math.floor((Date.now()-scriptProgressStarted)/1000)} 秒`;};
    tick();scriptProgressTimer=setInterval(tick,1000);
  }
  $('script-progress-phase').textContent=info.phase||'准备生成剧本';
  const total=Math.max(1,Number(info.total)||7),done=Math.max(0,Math.min(total,Number(info.done)||0));
  bar.max=total;
  if(done>0||info.status){bar.value=done;}else bar.removeAttribute('value');
  $('script-progress-count').textContent=info.status==='done'?'100%':info.status?'':done?`阶段 ${done}/${total}`:'生成中';
  if(info.status){clearInterval(scriptProgressTimer);scriptProgressTimer=null;scriptProgressActive=false;}
}
function stopScriptProgress(phase='生成已停止'){
  if(scriptProgressActive)updateScriptProgress({phase,status:'stopped',done:Number($('script-progress-bar').value)||0});
}
function runPipeline(continuePid,overrideIdea){
  if(generationReferenceBusy){alert('参考图正在保存，请稍后再开始生成');return;}
  const rawIdea=$('idea').value.trim();
  const fullScript=!continuePid&&importedFullScript&&rawIdea===importedFullScript?importedFullScript:'';
  if(!continuePid&&!rawIdea){alert('先输入你的故事创意吧');return;}
  if(!continuePid&&!fullScript&&directorConfirmedSignature!==directorSignature()){invalidateDirectorMatch(false);alert(directorMatched?'导演方案已调整，请点击“确认导演方案”后生成，无需重新匹配。':'请先让 AI 自动匹配导演台，再点击“确认导演方案”');return;}
  const style=getStyleValue();
  if(!style){alert('选择了自定义画风，请输入画风描述');$('styleCustom').classList.add('border-red-400');$('styleCustom').focus();return;}
  const idea=overrideIdea||(continuePid?'':fullScript?fullScript:buildDirectorIdea(rawIdea));
  $('continue-bar')?.remove();
  $('btn-run').disabled=true;$('btn-run').textContent='剧本生成中…';startRunClock();saveDraft();
  $('btn-cancel-pipeline').classList.remove('hidden');
  $('btn-cancel-pipeline').disabled=false;$('btn-cancel-pipeline').textContent='⏹ 终止制作';
  $('pipeline-box').classList.remove('hidden');
  updateScriptProgress({reset:true,phase:continuePid?'正在读取项目剧本':'正在提交剧本生成任务'});
  if(!continuePid){
    window.studioAssetsConfirmed=false;
    $('script-box').classList.add('hidden');$('shots-box').classList.add('hidden');$('final-box').classList.add('hidden');
    $('char-list').innerHTML='';$('scene-list').innerHTML='';$('shot-grid').innerHTML='';$('log').innerHTML='';SHOT_DATA={};
  }
  renderStages();
  const dur=$('shotDuration').value, cnt=$('shotCount').value;
  const [asp,mp]=$('resolution').value.split('|');
  const steps=Math.max(4,Math.min(25,parseInt($('h3Steps').value)||8));$('h3Steps').value=steps;
  const skillMode=$('prompt-skill-mode')?.value||'auto';
  const scriptSkill=$('script-skill-mode')?.value||'auto';
  const url=`/api/pipeline/run?style=${encodeURIComponent(style)}&shot_duration=${dur}&shot_count=${cnt}&skill_mode=${encodeURIComponent(skillMode)}&script_skill=${encodeURIComponent(scriptSkill)}&subtitle=${$('subtitleEnabled').checked?1:0}&aspect_ratio=${encodeURIComponent(asp)}&megapixels=${mp}&h3_steps=${steps}&custom_assets=${$('customAssets').checked?1:0}&manual=${$('manualMode').checked?1:0}&prompt_batch=${$('promptBatchMode').checked?1:0}&script_review=1${!continuePid&&generationReference?.id?`&asset_reference_id=${encodeURIComponent(generationReference.id)}`:''}${continuePid?`&pid=${continuePid}`:''}`;
  window._sseFinished=false;
  window._sseReconnectLogged=false;
  es=new PipelineStream(url,{idea,full_script_import:fullScript?'1':''});
  es.addEventListener('reference_sync_required',e=>{
    endRun();showReferenceSyncBar();
    log('参考图已更换，请点击“识别新图并预览修改”，确认同步后继续生成。','text-yellow-300');
    $('reference-sync-bar')?.scrollIntoView({behavior:'smooth',block:'center'});
  });
  es.addEventListener('start',e=>{const d=JSON.parse(e.data);setCurrentProjectId(d.pid);saveLastView();if($('side-process-project'))$('side-process-project').textContent=d.pid;log(`项目创建: ${d.pid}`,'gold');});
  es.addEventListener('stage',e=>{
    const d=JSON.parse(e.data);
    if(d.status==='running'){setStage(d.stage,'stage-active');log(`【${d.name}】${d.msg||'开始...'}`);}
    else if(d.status==='done'){setStage(d.stage,'stage-done');log(`【${d.name}】完成`,'text-green-400');
      if(d.stage===1&&d.script){
        // 续跑会发送缓存剧本；已有分镜卡片时保留视频，只在首次载入时重建布局。
        const hasCards=!!$('shot-grid')?.children.length;
        if(!d.cached||!hasCards)renderScript(d.script);
      }}
  });
  es.addEventListener('script_progress',e=>updateScriptProgress(JSON.parse(e.data)));
  es.addEventListener('script_ready',e=>{
    updateScriptProgress({done:7,total:7,status:'done',phase:'剧本已生成，可以查阅'});
    const d=JSON.parse(e.data);renderScript(d.script||{});showScriptReviewBar(d);
    log(d.msg||'剧本已生成，请查阅确认','gold');
  });
  es.addEventListener('agent_wait',e=>{const d=JSON.parse(e.data);if(d.wait_for==='script_confirm')showScriptReviewBar(d);log(d.msg||'等待确认后继续制作','gold');});
  es.addEventListener('script_regenerate_requested',e=>{
    const d=JSON.parse(e.data);window._scriptRegenerateRequested=true;log(d.msg||'已准备按新的导演台重新生成剧本','text-yellow-300');
  });
  es.addEventListener('wait_assets',e=>{const d=JSON.parse(e.data);log(d.msg,'gold');showAssetUploadUI();});
  es.addEventListener('asset',e=>{const d=JSON.parse(e.data);addAssetCard(d);log(`${d.name||'资产'}${d.server?` → ${d.server}`:''} 已完成`,'text-green-400');});
  es.addEventListener('progress',e=>{const d=JSON.parse(e.data);log(`进度 ${d.done}/${d.total}`);});
  es.addEventListener('shot_status',e=>{const d=JSON.parse(e.data);log(d.msg);
    const card=$('shot-'+d.index);
    if(card){const slot=card.querySelector('.video-slot');
      if(d.status==='render')showShotRenderProgress(d.index,{percent:0,elapsed:0,eta:0,phase:'H3准备渲染'});
      else if(slot&&d.status==='prompt_ready')slot.innerHTML=`<span class="text-green-400">提示词已就绪，等待渲染…</span>`;
      else if(slot)slot.innerHTML=`<span class="gold" style="animation:pulse 1.2s infinite;display:inline-block">⏳ AI撰写提示词中…</span>`;}
  });
  es.addEventListener('shot_render_progress',e=>{const d=JSON.parse(e.data);updateShotRenderProgress(d);});
  es.addEventListener('shot',e=>{const d=JSON.parse(e.data);SHOT_DATA[d.index]=d;addShotCard(d);if(d.review)applyShotReview(d.index,d.review);log(`第${d.index}镜视频完成`,'text-green-400');});
  es.addEventListener('shot_review',e=>{const d=JSON.parse(e.data);applyShotReview(d.index,d);if(d.score!=null)log(`镜头${d.index} AI审片：${d.score}分${d.attempt?` · 自动重做${d.attempt}次`:''}`,d.score>=72?'text-green-400':'text-yellow-300');});
  es.addEventListener('shot_prompt_ready',e=>{const d=JSON.parse(e.data);if(d.index<=0)return;if($('promptBatchMode').checked)showShotBatchEditor(d.index,d.prompt,d.duration||8,d.camera||SHOT_DATA[d.index]?.camera||'');else showShotConfirm(d.index,d.prompt,d.duration||8,d.camera||SHOT_DATA[d.index]?.camera||'');});
  es.addEventListener('prompt_batch_ready',e=>{const d=JSON.parse(e.data);showPromptBatchBar(d);if(d.msg)log(d.msg,'gold');});
  es.addEventListener('shot_error',e=>{const d=JSON.parse(e.data);SHOT_DATA[d.index]={...(SHOT_DATA[d.index]||{index:d.index}),index:d.index,refs:d.refs||[],prompt:d.prompt||''};showShotError(d.index,d.msg||'生成失败');});
  es.addEventListener('wait_resynth',e=>{const d=JSON.parse(e.data);showResynthUI(d);});
  es.addEventListener('asset_confirm_wait',e=>{const d=JSON.parse(e.data);openAssetEdit(d.key,d.url,d.prompt);});
  es.addEventListener('assets_ready',e=>{const d=JSON.parse(e.data);showAssetsConfirmBar(d);});
  es.addEventListener('shots_ready',e=>{const d=JSON.parse(e.data);showShotsConfirmBar(d);});
  es.addEventListener('shot_video_ready',e=>{const d=JSON.parse(e.data);openShotEdit(d.index,d.video_url,d.prompt);});
  es.addEventListener('final',e=>{const d=JSON.parse(e.data);showFinal(d);});
  es.addEventListener('cancelled',e=>{const d=JSON.parse(e.data);log(d.msg||'制作已终止','text-yellow-300');endRun();});
  es.addEventListener('error',e=>{if(!e.data)return;const d=JSON.parse(e.data);stopScriptProgress('剧本生成失败：'+d.msg);setStage(d.stage||1,'stage-err');log(`❌ ${d.msg}`,'text-red-400');endRun();});
  es.addEventListener('end',e=>{
    window._sseFinished=true;
    const shouldRegenerate=!!window._scriptRegenerateRequested;window._scriptRegenerateRequested=false;
    const pid=currentPid;endRun();
    if(shouldRegenerate&&pid)setTimeout(()=>runPipeline(pid,window._pendingScriptIdea||undefined),200);
  });

}
function endRun(){stopScriptProgress();if(es){es.close();es=null;}stopRunClock();$('btn-run').disabled=false;$('btn-run').textContent='生成剧本';const b=$('btn-cancel-pipeline');if(b){b.classList.add('hidden');b.disabled=false;b.textContent='⏹ 终止制作';}refreshStatus();}
async function cancelPipeline(){
  if(!currentPid||!es)return;
  if(!confirm('确定终止当前制作吗？已生成的资产和分镜会保留，可稍后继续。'))return;
  const b=$('btn-cancel-pipeline');b.disabled=true;b.textContent='正在终止…';
  try{
    const r=await (await fetch(`/api/pipeline/${encodeURIComponent(currentPid)}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'}})).json();
    log(r.msg||'已发送终止请求','text-yellow-300');
    stopScriptProgress('生成已取消');
    if(es){es.close();es=null;}stopRunClock();$('btn-run').disabled=false;$('btn-run').textContent='生成剧本';
    b.classList.add('hidden');b.disabled=false;b.textContent='⏹ 终止制作';refreshStatus();
  }catch(e){log('终止请求失败: '+e.message,'text-red-400');b.disabled=false;b.textContent='⏹ 终止制作';}
}

function buildFullScriptText(s){
  const lines=[`《${s.title||'未命名短剧'}》`,'',`剧情简介：${s.synopsis||'暂无剧情简介'}`,'','角色'];
  (s.characters||[]).forEach((c,i)=>lines.push(`${i+1}. ${c.name||'未命名角色'}：${c.personality||'性格未说明'}。${c.appearance||''}`));
  lines.push('','场景');
  (s.scenes||[]).forEach((sc,i)=>lines.push(`${i+1}. ${sc.name||'未命名场景'}：${sc.description||''}`));
  lines.push('','道具');
  (s.props||[]).forEach((p,i)=>lines.push(`${i+1}. ${p.name||'未命名道具'}：${p.description||''}`));
  lines.push('','分镜脚本');
  (s.shots||[]).forEach(sh=>{
    lines.push('',`【镜头 ${sh.index||''}】${sh.scene||''} · ${sh.duration||8}秒 · ${sh.camera||'固定中景'}`,`画面动作：${sh.action||''}`);
    const dialogue=(sh.dialogue||[]).map(d=>`${d.speaker||'角色'}：${d.line||''}${d.tone?`（${d.tone}）`:''}`).join('；');
    if(dialogue)lines.push(`对白：${dialogue}`);
  });
  return lines.join('\n');
}
function openScriptPreview(){
  renderScriptChat();
  $('script-preview-modal')?.classList.replace('hidden','flex');
  setTimeout(()=>$('script-chat-input')?.focus(),0);
}
function closeScriptPreview(event){
  if(event&&event.target&&event.target.id!=='script-preview-modal')return;
  $('script-preview-modal')?.classList.replace('flex','hidden');
}
function renderScriptChat(){
  const box=$('script-chat-messages');if(!box)return;
  if(!scriptChatHistory.length){
    box.innerHTML='<div class="text-[11px] text-gray-500">你可以直接说“把第1镜改成雨夜追逐”“加强结尾反转”或“减少对白、增加动作”。</div>';
    return;
  }
  box.innerHTML=scriptChatHistory.map(item=>`<div class="flex ${item.role==='user'?'justify-end':''}">
    <div class="max-w-[88%] rounded-lg px-2.5 py-2 text-xs whitespace-pre-wrap ${item.role==='user'?'bg-cyan-400/15 text-cyan-100':'bg-black/25 text-gray-300'}">${escapeHtml(item.content)}</div>
  </div>`).join('');
  box.scrollTop=box.scrollHeight;
}
async function sendScriptChat(){
  if(!currentPid){$('script-chat-status').textContent='当前没有可修改的项目';return;}
  const input=$('script-chat-input'),text=(input?.value||'').trim();
  if(!text)return;
  const button=$('script-chat-send'),status=$('script-chat-status');
  button.disabled=true;input.disabled=true;status.textContent='AI 正在理解修改要求并重写相关剧本内容…';
  scriptChatHistory.push({role:'user',content:text});renderScriptChat();input.value='';
  try{
    const response=await fetch(`/api/project/${encodeURIComponent(currentPid)}/script/chat`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,history:scriptChatHistory.slice(0,-1)})
    });
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok)throw new Error(result.msg||result.error||'AI修改失败');
    scriptChatHistory=result.chat_history||[...scriptChatHistory,{role:'assistant',content:result.reply||'剧本已更新，请继续查阅。'}];
    SCRIPT_DATA=result.script||SCRIPT_DATA;
    renderScript(SCRIPT_DATA);
    if($('script-preview-title'))$('script-preview-title').textContent=`${SCRIPT_DATA.title||'未命名短剧'} · 完整剧本`;
    if($('script-preview-text'))$('script-preview-text').textContent=buildFullScriptText(SCRIPT_DATA);
    status.textContent='剧本已更新；请继续查阅，确认后再继续制作。';
    log('已通过 AI 对话更新剧本','text-green-400');
  }catch(error){
    scriptChatHistory.push({role:'assistant',content:'修改失败：'+error.message});
    status.textContent='修改失败，请调整说法后重试。';
  }finally{
    renderScriptChat();button.disabled=false;input.disabled=false;input.focus();
  }
}
function renderShotScriptSegment(sh){
  const dialogue=(sh.dialogue||[]).map(d=>`${d.speaker||'角色'}：${d.line||''}${d.tone?`（${d.tone}）`:''}`).join('；');
  const scene=escapeHtml(sh.scene||'未指定');
  // 衔接镜头沿用普通镜头卡片；展示时只取用户描述，内部连续性约束仍保留给生成器。
  const rawAction=String(sh.action||'暂无动作描述');
  const action=sh.is_bridge
    ? (rawAction.match(/用户要求：([^\n]*)/)?.[1]||rawAction)
    : rawAction;
  const actionBrief=escapeHtml(action.length>72?`${action.slice(0,72)}…`:action);
  const summary=escapeHtml(`${sh.scene||'镜头'}中，${action.length>90?`${action.slice(0,90)}…`:action}`);
  return `<details class="shot-script-segment">
    <summary>
      <span class="shot-script-summary"><span class="shot-script-intro"><strong>镜头概括：</strong>${summary}</span></span>
      <span class="shot-script-more" aria-hidden="true"></span>
    </summary>
    <div class="shot-script-detail">
      <div><strong>场景：</strong>${scene}</div>
      <div><strong>动作：</strong>${escapeHtml(action)}</div>
      ${dialogue?`<div><strong>对白：</strong>${escapeHtml(dialogue)}</div>`:''}
    </div>
  </details>`;
}
function renderScript(s){
  SCRIPT_DATA=s;SHOT_DATA={};
  $('script-box').classList.remove('hidden');$('shots-box').classList.remove('hidden');
  $('shot-grid').innerHTML='';
  $('proj-title').textContent=s.title||'';
  let summary=$('script-summary');
  if(!summary){
    summary=document.createElement('div');
    summary.id='script-summary';
    summary.className='glass rounded-2xl p-5 card-in';
    $('script-box').prepend(summary);
  }
  summary.innerHTML=`<div class="flex items-center gap-3"><h3 class="font-bold text-lg gold">📝 ${escapeHtml(s.title||'未命名短剧')}</h3><span class="tag">剧本查阅</span></div>
    <p class="text-sm text-gray-300 mt-3 leading-7">${escapeHtml(s.synopsis||'暂无剧情简介')}</p>
    <div class="flex flex-wrap gap-2 mt-4">
      <button type="button" onclick="openScriptPreview()" class="text-xs px-4 py-2 rounded-lg glass hover:bg-yellow-400/20 text-yellow-200 transition">查看与修改剧本</button>
      <button type="button" onclick="openCurrentProjectRemake('script')" class="text-xs px-4 py-2 rounded-lg glass hover:bg-yellow-400/20">↩ 返回重做剧本</button>
      <button type="button" onclick="openCurrentProjectRemake('asset')" class="text-xs px-4 py-2 rounded-lg glass hover:bg-yellow-400/20">↩ 重新生成资产提示词和图片</button>
    </div><p class="text-xs text-gray-500 mt-2">返回重做会创建新版本。重做剧本后重新生成资产；重做资产则保留当前剧本，按剧本重新构造图片提示词。</p>`;
  if($('script-preview-title'))$('script-preview-title').textContent=`${s.title||'未命名短剧'} · 完整剧本`;
  if($('script-preview-text'))$('script-preview-text').textContent=buildFullScriptText(s);
  log(`剧本《${s.title}》: ${(s.shots||[]).length}个分镜`,'gold');
  $('char-list').innerHTML=(s.characters||[]).map(c=>`
    <div class="asset-card asset-character bg-black/30 rounded-xl p-3 card-in" id="card-char-${c.name}">
      <div class="asset-title"><div class="asset-title-text font-bold text-sm gold" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div></div>
      <div class="text-xs text-gray-500 mt-1 asset-description">${c.personality||''}</div>
      <div class="text-xs text-gray-400 mt-1 line-clamp-2 asset-description">${c.appearance||''}</div>
      <div class="img-slot mt-2"></div>
      <button class="audio-btn asset-action-btn rounded glass hover:bg-white/10 transition text-gray-300 mt-2" onclick="pickRoleAudio('${c.name}',this)" title="上传参考音色" aria-label="上传参考音色">🎙️</button>
    </div>`).join('');
  $('scene-list').innerHTML=(s.scenes||[]).map(sc=>`
    <div class="asset-card bg-black/30 rounded-xl p-3 card-in" id="card-scene-${sc.name}">
      <div class="asset-title"><div class="asset-title-text font-bold text-sm" title="${escapeHtml(sc.name)}">${escapeHtml(sc.name)}</div></div>
      <div class="text-xs text-gray-400 mt-1 line-clamp-2 asset-description">${sc.description||''}</div>
      <div class="img-slot mt-2"></div>
    </div>`).join('');
  $('prop-list').innerHTML=(s.props||[]).map(pp=>`
    <div class="asset-card bg-black/30 rounded-xl p-3 card-in" id="card-prop-${pp.name}">
      <div class="asset-title"><div class="asset-title-text font-bold text-sm" style="color:#8fd3f4" title="${escapeHtml(pp.name)}">${escapeHtml(pp.name)}</div></div>
      <div class="text-xs text-gray-400 mt-1 line-clamp-2 asset-description">${pp.description||''}</div>
      <div class="img-slot mt-2"></div>
    </div>`).join('');
  (s.shots||[]).forEach(sh=>{
    SHOT_DATA[sh.index]={index:sh.index,duration:sh.duration,camera:sh.camera||'',is_bridge:!!sh.is_bridge,prompt:sh.prompt||''};
    $('shot-grid').innerHTML+=`
      <div class="bg-black/30 rounded-xl p-3 card-in" id="shot-${sh.index}">
        <div class="flex items-center gap-2 mb-2"><span class="tag">镜头 ${sh.index}</span><span id="shot-meta-${sh.index}" class="text-xs text-gray-500">${sh.duration}s · ${sh.camera||''}</span>
          <div class="flex-1"></div>
        </div>
        ${SHOT_DATA[sh.index]?.reference_video_stale?'<div class="text-xs text-yellow-300">参考图已同步，视频待重新生成</div>':''}
        ${renderShotScriptSegment(sh)}
        <div class="video-slot text-center text-xs text-gray-600 py-4 bg-black/30 rounded-lg">
          <div>等待生成…</div>
          <button onclick="remakeShot(${sh.index})" class="shot-action-btn rounded glass hover:bg-yellow-400/20 transition text-gray-300 mt-3" title="使用当前提示词和参考图重新生成" aria-label="使用当前提示词和参考图重新生成">🔄</button>
        </div>
      </div>`;
  });
}
function addAssetCard(d){
  const prefix=d.type==='character'?'char':(d.type==='prop'?'prop':'scene');
  const card=$(`card-${prefix}-${d.name}`);
  if(card){const slot=card.querySelector('.img-slot');if(slot){
    if(d.prompt)card.dataset.prompt=d.prompt;
    const cardPrompt=()=>card.dataset.prompt||[...card.querySelectorAll('.asset-description')]
      .map(el=>el.textContent.trim()).filter(Boolean).join('\n');
    slot.querySelectorAll('img').forEach(im=>im.remove());
    slot.querySelectorAll('.asset-image-wrap').forEach(el=>el.remove());
    if(d.url){
      card.classList.add('has-asset-image');
      const wrap=document.createElement('div');wrap.className='asset-image-wrap card-in';
      const img=document.createElement('img');img.src=d.url;img.className='rounded-lg w-full';
      img.title='点击查看图片';
      const hover=document.createElement('div');hover.className='asset-hover-text text-xs';
      hover.textContent=card.querySelector('.asset-description')?.textContent?.trim()||d.prompt||'点击查看图片';
      wrap.append(img,hover);
      wrap.onclick=()=>{
        openImageLightbox(img.src,d.name);
      };
      slot.insertBefore(wrap,slot.firstChild);
    }else{
      card.classList.remove('has-asset-image');
    }
    if(d.url){
      if(!slot.querySelector('.asset-actions')){
        const box=document.createElement('div');box.className='asset-actions mt-2';
        const editButton=document.createElement('button');
        editButton.type='button';
        editButton.className='asset-action-btn rounded glass hover:bg-yellow-400/20 transition text-gray-300';
        editButton.title='编辑提示词并重新生成这张图片';
        editButton.setAttribute('aria-label','编辑提示词并重新生成图片');
        editButton.textContent='✏️';
        editButton.onclick=(event)=>{
          event.stopPropagation();
          regenerateAsset(prefix,d.name);
        };
        box.appendChild(editButton);
        slot.appendChild(box);
      }
    }
    if(d.url){
      const safeName=String(d.name||'').replace(/[\\'"\/]/g,'');
      let replace=slot.querySelector('.asset-replace-btn');
      if(!replace){
        replace=document.createElement('button');
        replace.type='button';
        replace.className='asset-replace-btn asset-action-btn rounded glass hover:bg-white/10 transition text-gray-300';
        replace.title='上传新的图片替换当前资产';
        replace.setAttribute('aria-label','上传新的图片替换当前资产');
        replace.onclick=(event)=>{event.stopPropagation();replaceAssetImage(prefix,d.name,replace);};
        replace.textContent='📤';
        slot.querySelector('.asset-actions')?.appendChild(replace);
      }
      const actions=slot.querySelector('.asset-actions');
      const audio=card.querySelector('.audio-btn');
      if(audio&&actions){audio.classList.remove('mt-2');actions.append(audio);}
      if(actions&&!actions.querySelector('.asset-history-btn')){
        const history=document.createElement('button');
        history.type='button';history.className='asset-history-btn asset-action-btn rounded glass';
        history.textContent='🕘';history.title='选择历史图片版本';history.setAttribute('aria-label',history.title);
        history.onclick=()=>showAssetCardVersions(card,`${prefix}_${d.name}`,actions);
        actions.append(history);
      }
    }
  }}
  log(`参考图完成: ${d.name}${d.cached?'(缓存)':''}`);
}
async function showAssetCardVersions(card,key,actions){
  const pid=currentPid;
  actions.querySelector('.asset-version-controls')?.remove();
  const box=document.createElement('span');box.className='asset-version-controls';
  box.style.cssText='display:flex;align-items:center;gap:6px;min-width:0';
  box.textContent='读取版本…';actions.append(box);
  try{
    const response=await fetch(`/api/project/${encodeURIComponent(pid)}/asset/${encodeURIComponent(key)}/versions`,{cache:'no-store'});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||result.msg||'读取失败');
    if(currentPid!==pid||!card.isConnected)return;
    box.textContent='';
    const select=document.createElement('select');select.setAttribute('aria-label','历史图片版本');select.style.cssText='background:#202426;color:inherit;max-width:180px';
    for(const [i,v] of (result.versions||[]).entries()){
      const option=document.createElement('option');option.value=v.id;option.textContent=`版本 ${result.versions.length-i}${v.id===result.current_version_id?'（当前）':''}`;option.dataset.url=v.url||'';option.selected=v.id===result.current_version_id;select.append(option);
    }
    if(!select.options.length){box.textContent='暂无历史版本';return;}
    const preview=document.createElement('button');preview.type='button';preview.textContent='预览';
    preview.onclick=()=>{const url=select.selectedOptions[0]?.dataset.url;if(url)openImageLightbox(url,'历史图片版本');};
    const restore=document.createElement('button');restore.type='button';restore.textContent='恢复';
    restore.onclick=async()=>{
      if(currentPid!==pid)return;
      restore.disabled=true;
      try{
        const r=await fetch(`/api/project/${encodeURIComponent(pid)}/asset/${encodeURIComponent(key)}/select_version`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version_id:select.value})});
        const data=await r.json();if(!r.ok||data.error)throw new Error(data.error||data.msg||'恢复失败');
        if(currentPid!==pid)return;
        updateAssetCardImg(key,data.url);card.dataset.prompt=data.prompt||'';
        await showAssetCardVersions(card,key,actions);
      }catch(e){alert(e.message);}finally{restore.disabled=false;}
    };
    box.append(select,preview,restore);
  }catch(e){box.textContent='历史版本读取失败';box.title=e.message;}
}
function showReferenceSyncBar(){
  let bar=$('reference-sync-bar');
  if(!bar){bar=document.createElement('div');bar.id='reference-sync-bar';bar.className='glass rounded-xl p-4 mb-3';}
  const host=$('studio-asset-controls')||$('script-box');
  host.classList.remove('hidden');host.prepend(bar);
  bar.innerHTML='<div class="text-yellow-300 text-sm">参考图已更新：请先同步受影响镜头的外观、服装和视频提示词，再重新生成。</div><button class="btn-gold rounded px-3 py-2 mt-2 text-sm">识别新图并预览修改</button>';
  bar.querySelector('button').onclick=()=>previewReferenceSync(bar.querySelector('button'));
}
function openReferenceSyncApproval(){
  showReferenceSyncBar();
  const bar=$('reference-sync-bar');
  const button=bar?.querySelector('button');
  if(button){
    log('参考图已更新，正在打开同步确认…','text-yellow-300');
    previewReferenceSync(button);
  }
}
async function previewReferenceSync(button,afterApply){
  const pid=currentPid;button.disabled=true;button.textContent='正在识别新图并同步镜头…';
  try{
    const r=await(await fetch(`/api/project/${pid}/reference-sync`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    if(!r.ok)throw new Error(r.msg||'同步失败');
    if(currentPid!==pid)return;
    const dialog=document.createElement('dialog');dialog.className='rounded-xl bg-gray-900 text-gray-200 p-5';dialog.style.cssText='width:min(1000px,95vw);max-height:85vh;overflow:auto';
    dialog.innerHTML=`<h3 class="text-lg gold">确认参考图同步 · ${r.changes.length} 个镜头</h3><p class="text-sm my-3">只修改当前集。确认后保存描述，已有视频需重新生成。</p><pre class="whitespace-pre-wrap text-sm">${escapeHtml(Object.entries(r.descriptions).map(([k,v])=>k+'：'+v).join('\n'))}</pre>`;
    for(const c of r.changes){const section=document.createElement('details');section.className='my-3 border border-white/20 rounded p-3';section.innerHTML=`<summary>镜头 ${c.index} · 查看修改前后</summary>`;for(const [key,label] of [['wardrobe','服装'],['action','动作'],['prompt','视频提示词']]){const block=document.createElement('div');block.innerHTML=`<strong>${label}</strong><div class="grid md:grid-cols-2 gap-3"><pre class="whitespace-pre-wrap text-xs p-2 bg-black/20">修改前\n${escapeHtml(c.before[key])}</pre><pre class="whitespace-pre-wrap text-xs p-2 bg-black/20">修改后\n${escapeHtml(c[key])}</pre></div>`;section.appendChild(block);}dialog.appendChild(section);}
    const apply=document.createElement('button');apply.className='btn-gold rounded px-4 py-2';apply.textContent='确认并保存同步结果';
    apply.onclick=async()=>{apply.disabled=true;try{const result=await(await fetch(`/api/project/${pid}/reference-sync`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({apply:true,token:r.token})})).json();if(!result.ok)throw new Error(result.msg);dialog.close();dialog.remove();if(currentPid===pid){await openProject(pid);if(currentPid===pid&&afterApply)afterApply();}}catch(e){alert(e.message);apply.disabled=false;}};
    const cancel=document.createElement('button');cancel.textContent='暂不修改';cancel.className='ml-4';cancel.onclick=()=>{dialog.close();dialog.remove();};dialog.append(apply,cancel);document.body.appendChild(dialog);dialog.showModal();
  }catch(e){alert(e.message);}finally{button.disabled=false;button.textContent='识别新图并预览修改';}
}
function replaceAssetImage(prefix,name,button){
  if(!currentPid){alert('没有活动项目');return;}
  const input=document.createElement('input');
  input.type='file';input.accept='image/png,image/jpeg,image/webp';
  input.onchange=async()=>{
    if(!input.files[0])return;
    const key=`${prefix}_${name}`;
    const form=new FormData();form.append('pid',currentPid);form.append('key',key);form.append('file',input.files[0]);
    const old=button.textContent;button.disabled=true;button.textContent='上传替换中…';
    try{
      const response=await fetch('/api/upload_asset',{method:'POST',body:form});
      const result=await response.json();
      if(!response.ok||!result.ok)throw new Error(result.msg||result.error||'上传失败');
      const kind=prefix==='char'?'character':(prefix==='prop'?'prop':'scene');
      addAssetCard({type:kind,name,url:result.url+'?t='+Date.now(),cached:false});
      log(`资产「${name}」已更换，请预览并确认提示词同步`,'text-green-400');
      if(result.sync_required)showReferenceSyncBar();
    }catch(error){alert('更换图片失败：'+error.message);}
    finally{button.disabled=false;button.textContent=old;}
  };
  input.click();
}
function openImageLightbox(url,name=''){
  if(!url)return;
  let box=$('image-lightbox'),img=$('image-lightbox-img'),caption=$('image-lightbox-caption');
  if(!box||!img)return;
  // 脱离所有弹窗和层叠上下文，保证大图始终位于最顶层。
  document.body.appendChild(box);
  box.setAttribute('style','position:fixed!important;inset:0!important;z-index:2147483647!important;display:flex!important;align-items:center;justify-content:center;background:rgba(0,0,0,.92);');
  box.classList.add('open');
  img.src=url+(url.includes('?')?'&':'?')+'t='+Date.now();
  img.alt=name?`${name}参考图`:'资产大图预览';
  if(caption)caption.textContent=name||'';
}
function closeImageLightbox(event){
  if(event&&event.target&&event.target.id!=='image-lightbox'&&event.target.tagName!=='BUTTON')return;
  const box=$('image-lightbox');if(box){box.classList.remove('open');box.removeAttribute('style');}
}
// 打开参考图编辑窗口：可编辑提示词再重新生成（不满意单独重做这一张，不影响其它资产与已成功镜头）
function regenerateAsset(prefix,name){
  if(!currentPid){alert('没有活动项目');return;}
  const key=prefix+'_'+name;
  const card=$(`card-${prefix}-${name}`);const slot=card?card.querySelector('.img-slot'):null;const im=slot?slot.querySelector('img'):null;
  const prompt=card?.dataset?.prompt||[...(card?.querySelectorAll('.asset-description')||[])]
    .map(el=>el.textContent.trim()).filter(Boolean).join('\n');
  openAssetEdit(key,im?im.src:null,prompt);
}
// 上传角色参考音色（可选）：绑定到角色资产，跨镜头保持音色一致
function pickRoleAudio(name,btn){
  const inp=document.createElement('input');inp.type='file';inp.accept='audio/*,.wav,.mp3,.flac,.ogg,.m4a';
  inp.onchange=async()=>{
    if(!inp.files[0])return;
    const key='char_'+name;
    const fd=new FormData();fd.append('pid',currentPid);fd.append('key',key);fd.append('file',inp.files[0]);
    const orig=btn.innerHTML;btn.innerHTML='音色上传中...';btn.disabled=true;
    try{
      const r=await(await fetch('/api/upload_role_audio',{method:'POST',body:fd})).json();
      if(r.ok){btn.innerHTML='🎙️ 已设音色 ✅（点此更换）';btn.disabled=false;log(`已绑定「${name}」参考音色，跨镜头音色将保持一致`,'text-green-400');}
      else{alert('音色上传失败: '+(r.msg||''));btn.innerHTML=orig;btn.disabled=false;}
    }catch(e){alert('音色上传失败: '+e.message);btn.innerHTML=orig;btn.disabled=false;}
  };
  inp.click();
}
// 自定义参考图模式：为每张资产卡片注入上传按钮 + 底部"继续生成"按钮
function showAssetUploadUI(){
  document.querySelectorAll('[id^="card-char-"],[id^="card-scene-"],[id^="card-prop-"]').forEach(card=>{
    const slot=card.querySelector('.img-slot');
    if(!slot||slot.dataset.uploadReady)return;
    slot.dataset.uploadReady='1';
    const m=card.id.match(/^card-(char|scene|prop)-(.+)$/);
    if(!m)return;
    const key=m[1]+'_'+m[2];
    const btn=document.createElement('button');
    btn.className='text-xs px-3 py-2 rounded-lg glass hover:bg-white/10 transition w-full text-gray-300 mt-2';
    btn.innerHTML='📤 上传参考图';
    let pendingFile=null;
    btn.onclick=()=>{
      const inp=document.createElement('input');inp.type='file';inp.accept='image/png,image/jpeg,image/webp';
      inp.onchange=async()=>{
        const file=pendingFile||inp.files[0];pendingFile=null;if(!file)return;
        const fd=new FormData();fd.append('pid',currentPid);fd.append('key',key);fd.append('file',file);
        btn.innerHTML='上传中...';btn.disabled=true;
        try{
          const r=await(await fetch('/api/upload_asset',{method:'POST',body:fd})).json();
          if(r.ok){
            const kind=m[1]==='char'?'character':(m[1]==='prop'?'prop':'scene');
            addAssetCard({type:kind,name:m[2],url:r.url+'?t='+Date.now(),cached:false});
            btn.innerHTML='🔄 重新上传';btn.disabled=false;
            log('已上传自定义参考图: '+m[2],'text-green-400');
            if(r.sync_required)showReferenceSyncBar();
          }else{alert('上传失败: '+(r.msg||''));btn.innerHTML='📤 上传参考图';btn.disabled=false;}
        }catch(e){alert('上传失败: '+e.message);btn.innerHTML='📤 上传参考图';btn.disabled=false;}
      };
      inp.click();
    };
    const dropTarget=slot;
    ['dragenter','dragover'].forEach(type=>dropTarget.addEventListener(type,e=>{e.preventDefault();dropTarget.classList.add('is-dragover');}));
    ['dragleave','drop'].forEach(type=>dropTarget.addEventListener(type,e=>{e.preventDefault();dropTarget.classList.remove('is-dragover');}));
    dropTarget.addEventListener('drop',e=>{const file=[...(e.dataTransfer?.files||[])].find(f=>f.type.startsWith('image/'));if(!file)return;pendingFile=file;btn.click();setTimeout(()=>{const input=document.querySelector('input[type=file]:focus');},0);});
    slot.appendChild(btn);
  });
  if(!$('assets-continue-btn')){
    const cbtn=document.createElement('button');
    cbtn.id='assets-continue-btn';
    cbtn.className='btn-gold px-8 py-3 rounded-xl text-base w-full mt-4';
    cbtn.textContent='✅ 参考图就绪，继续生成（未上传的空缺将由AI自动生成）';
    cbtn.onclick=async()=>{
      cbtn.disabled=true;cbtn.textContent='正在确认（AI识别上传图外观中，请稍候）...';
      try{
        const r=await(await fetch('/api/confirm_assets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pid:currentPid})})).json();
        if(r.ok){cbtn.remove();log(`参考图已确认${r.rewritten?`，AI已按上传图重写${r.rewritten}条外观描述`:''}，流水线继续`,'text-green-400');
          if(!es){runPipeline(currentPid);}}
        else{alert('确认失败: '+(r.msg||''));cbtn.disabled=false;cbtn.textContent='✅ 参考图就绪，继续生成';}
      }catch(e){alert('确认失败: '+e.message);cbtn.disabled=false;cbtn.textContent='✅ 参考图就绪，继续生成';}
    };
    $('script-box').appendChild(cbtn);
    if (!loadingProjectView) cbtn.scrollIntoView({behavior:'smooth',block:'center'});
  }
}
let resynthES=null, editMode=null, editKeyRef=null, editPoll=null, editChatHistory=[];
let shotReferenceView=null;
const shotReferenceUploads=new Set();
let imageEditKeyRef='';
function editShow(){const modal=$('edit-modal');if(!modal)return;if(modal.parentElement!==document.body)document.body.appendChild(modal);modal.classList.replace('hidden','flex');}
let modalScrollLocks=0;
function lockModalScroll(){modalScrollLocks++;document.documentElement.classList.add('modal-open');document.body.classList.add('modal-open');}
function unlockModalScroll(){modalScrollLocks=Math.max(0,modalScrollLocks-1);if(!modalScrollLocks){document.documentElement.classList.remove('modal-open');document.body.classList.remove('modal-open');}}
function closeEdit(){const m=$('edit-modal');if(m&&m.classList.contains('flex')){m.classList.replace('flex','hidden');unlockModalScroll();}}
function initModalScrollGuard(){
  const sync=()=>{const open=[...document.querySelectorAll('[id$="-modal"],.image-lightbox')].filter(x=>x.classList.contains('flex')||getComputedStyle(x).display!=='none');const active=open.length>0;document.documentElement.classList.toggle('modal-open',active);document.body.classList.toggle('modal-open',active);};
  const observer=new MutationObserver(sync);document.querySelectorAll('[id$="-modal"],.image-lightbox').forEach(m=>observer.observe(m,{attributes:true,attributeFilter:['class','style']}));
  document.addEventListener('wheel',e=>{const modal=e.target.closest?.('[id$="-modal"],.image-lightbox');if(document.body.classList.contains('modal-open')&&!modal)e.preventDefault();},{passive:false});
  sync();
}
function editMsg(t){const el=$('edit-msg');if(el)el.textContent=t||'';}
function editRenderPreview(kind,url){
  const box=$('edit-preview');box.innerHTML='';
  if(!url){box.innerHTML='<div class="text-gray-600 text-sm">等待内容…</div>';return;}
  if(kind==='asset')box.innerHTML=`<img src="${url}" class="max-w-full max-h-full rounded-lg" style="max-height:40vh;">`;
  else box.innerHTML=`<video src="${url}" playsinline preload="metadata" controls class="max-w-full max-h-full rounded-lg" style="width:100%;height:100%;object-fit:contain;"></video>`;
}
function assetKeyParts(key){const m=String(key).match(/^(char|scene|prop)_(.+)$/)||[null,'char',key];return {prefix:m[1],name:m[2]};}
function updateAssetCardImg(key,url){
  try{const {prefix,name}=assetKeyParts(key);const card=$(`card-${prefix}-${name}`);const slot=card?card.querySelector('.img-slot'):null;const im=slot?slot.querySelector('img'):null;if(im)im.src=url+(url.includes('?')?'&':'?')+'t='+Date.now();}catch(e){}
}
async function loadImageModels(selectIds){
  const selects=(selectIds||[]).map(id=>$(id)).filter(Boolean);
  if(!selects.length)return;
  selects.forEach(select=>select.replaceChildren(new Option('正在获取图片模型…','')));
  try{
    const response=await fetch('/api/image-models',{cache:'no-store'});
    const data=await readJsonResponse(response);
    const models=[...new Set((data.models||[]).filter(Boolean))];
    selects.forEach(select=>{
      select.replaceChildren(
        new Option(data.current?`使用默认模型（${data.current}）`:'使用默认图片模型',''),
        ...models.map(model=>new Option(model,model))
      );
      select.dataset.provider=data.provider||'';
      select.title=data.provider==='jimeng'?'即梦图片模型':`ComfyUI 图片模型${data.endpoint?` · ${data.endpoint}`:''}`;
    });
  }catch(error){
    selects.forEach(select=>select.replaceChildren(new Option('模型列表获取失败，使用默认模型','')));
  }
}
function imageEditMsg(text){
  const el=$('image-edit-msg');
  if(el)el.textContent=text||'';
}
function renderImageEditPreview(url){
  const box=$('image-edit-preview');
  if(!box)return;
  box.innerHTML=url
    ? `<img src="${url}${url.includes('?')?'&':'?'}t=${Date.now()}" class="max-w-full max-h-full rounded-lg object-contain" style="max-height:42vh;" alt="图片修改预览">`
    : '<div class="text-gray-600 text-sm">等待图片…</div>';
}
async function loadImageVersions(){
  const box=$('image-edit-versions');
  if(!box||!currentPid||!imageEditKeyRef)return;
  box.innerHTML='<div class="text-xs text-gray-500">正在读取历史版本…</div>';
  try{
    const result=await(await fetch(`/api/project/${currentPid}/asset/${encodeURIComponent(imageEditKeyRef)}/versions`,{cache:'no-store'})).json();
    const versions=result.versions||[];
    if(!versions.length){box.innerHTML='';return;}
    const options=versions.map((version,position)=>{
      const date=version.created?new Date(version.created*1000).toLocaleString():'';
      const current=version.id===result.current_version_id?'（当前）':'';
      return `<option value="${escapeHtml(version.id)}" data-url="${escapeHtml(version.url||'')}">版本 ${versions.length-position} ${current} · ${escapeHtml(version.label||'图片版本')} · ${escapeHtml(date)}</option>`;
    }).join('');
    box.innerHTML=`<label class="field-label">历史图片版本</label>
      <div class="flex items-center gap-2">
        <select id="image-edit-version-select" class="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs">${options}</select>
        <button type="button" class="px-3 py-2 rounded-lg glass text-xs" onclick="previewImageVersion()">预览</button>
        <button type="button" class="px-3 py-2 rounded-lg glass text-xs" onclick="restoreImageVersion()">恢复</button>
      </div>`;
  }catch(error){box.innerHTML='<div class="text-xs text-gray-500">历史版本读取失败</div>';}
}
function previewImageVersion(){
  const selected=$('image-edit-version-select')?.selectedOptions?.[0];
  if(selected?.dataset?.url)renderImageEditPreview(selected.dataset.url);
}
async function restoreImageVersion(){
  if(!currentPid||!imageEditKeyRef)return;
  const versionId=$('image-edit-version-select')?.value;
  if(!versionId)return;
  const button=[...($('image-edit-versions')?.querySelectorAll('button')||[])].find(el=>el.textContent.includes('恢复'));
  if(button)button.disabled=true;
  try{
    const response=await fetch(`/api/project/${currentPid}/asset/${encodeURIComponent(imageEditKeyRef)}/select_version`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version_id:versionId})
    });
    const result=await response.json();
    if(!response.ok||result.error)throw new Error(result.error||'恢复失败');
    renderImageEditPreview(result.url);
    updateAssetCardImg(imageEditKeyRef,result.url);
    $('image-edit-prompt').value=result.prompt||'';
    const {prefix,name}=assetKeyParts(imageEditKeyRef);
    const card=$(`card-${prefix}-${name}`);
    if(card)card.dataset.prompt=result.prompt||'';
    imageEditMsg('已恢复历史图片版本。');
    loadImageVersions();
  }catch(error){imageEditMsg('恢复失败：'+error.message);}
  finally{if(button)button.disabled=false;}
}
function openImageEdit(key,url,prompt){
  imageEditKeyRef=key;
  $('image-edit-title').textContent='✏️ 修改图片 · '+key.replace(/^(char|scene|prop)_/,'');
  $('image-edit-prompt').value=ASSET_EDIT_DATA[key]?.prompt??prompt??'';
  $('image-edit-model').value='';
  $('image-edit-redraw').disabled=false;
  $('image-edit-confirm').disabled=false;
  $('image-edit-versions').innerHTML='';
  $('image-edit-chat-messages').innerHTML=''; $('image-edit-chat-input').value='';
  AIChat.render($('image-edit-chat-messages'),ASSET_EDIT_DATA[key]?.chat_history||[]);AIChat.resize($('image-edit-chat-input'));
  renderImageEditPreview(url);
  const ref=$('image-edit-reference-card');
  if(ref) ref.innerHTML=url
    ? `<div class="text-[10px] text-gray-500 mb-1">当前资产参考图</div><button type="button" class="shot-reference-card has-image" onclick="openImageLightbox('${String(url).replace(/'/g,"\\'")}','参考图')"><img src="${String(url).replace(/'/g,"\\'")}" alt="当前资产参考图"><span>当前图片</span></button>`
    : '<div class="text-xs text-gray-500">暂无参考图</div>';
  imageEditMsg('可修改提示词并选择图片模型，确认后会替换当前资产。');
  $('image-edit-modal').classList.replace('hidden','flex');
  loadImageModels(['image-edit-model']); loadImageEditChatModels();
  loadImageVersions();
}
async function fetchAvailableLLMModels(){
  const r=await fetch('/api/llm/models',{cache:'no-store'}); const d=await r.json();
  if(!r.ok||d.ok===false)throw new Error(d.msg||d.error||'模型列表不可用');
  return d;
}
async function loadImageEditChatModels(){const s=$('image-edit-chat-model');if(!s)return;try{const d=await fetchAvailableLLMModels();s.replaceChildren(new Option(d.current?`使用当前 LLM（${d.current}）`:'使用当前 LLM',''),...(d.models||[]).filter(Boolean).map(m=>new Option(m,m)));}catch(_){s.replaceChildren(new Option('使用当前 LLM',''));}}
async function sendImageEditChat(){
  if(!currentPid||!imageEditKeyRef)return;
  const input=$('image-edit-chat-input'), message=(input?.value||'').trim(); if(!message)return;
  const pid=currentPid,key=imageEditKeyRef;
  const box=$('image-edit-chat-messages'); const add=(role,text)=>AIChat.append(box,role,text);
  add('user',message); input.value='';
  const history=[...box.children].map(el=>({role:el.dataset.role,content:el.dataset.content}));
  try{const r=await fetch(`/api/project/${pid}/asset/${encodeURIComponent(key)}/prompt-chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:$('image-edit-prompt').value,message,history,model:$('image-edit-chat-model')?.value||''})}); const d=await r.json(); if(!r.ok||!d.ok)throw new Error(d.error||d.msg||'AI请求失败'); if(currentPid===pid){ASSET_EDIT_DATA[key]={...(ASSET_EDIT_DATA[key]||{}),prompt:d.prompt,chat_history:d.chat_history||[...history,{role:'assistant',content:d.reply}],edit_revisions:d.edit_revisions||[]};const {prefix,name}=assetKeyParts(key);const card=$(`card-${prefix}-${name}`);if(card)card.dataset.prompt=d.prompt;} if(currentPid!==pid||imageEditKeyRef!==key)return; $('image-edit-prompt').value=d.prompt; add('assistant',d.reply||'已更新提示词。'); imageEditMsg('AI已修改并保存提示词与对话，请检查后重新生成。');}catch(e){add('assistant','修改失败：'+e.message);}
}
document.addEventListener('keydown',e=>{
  if(e.key!=='Enter'||e.shiftKey||e.isComposing)return;
  if(e.target?.id==='script-chat-input'){e.preventDefault();sendScriptChat();}
});
function closeImageEdit(event){
  if(event&&event.target&&event.target.id!=='image-edit-modal')return;
  $('image-edit-modal')?.classList.replace('flex','hidden');
}
async function redrawImageEdit(){
  if(!currentPid||!imageEditKeyRef)return;
  const prompt=$('image-edit-prompt').value.trim();
  if(!prompt){imageEditMsg('提示词不能为空');return;}
  const button=$('image-edit-redraw');
  button.disabled=true;
  $('image-edit-confirm').disabled=true;
  imageEditMsg('正在重新生成图片，请稍候…');
  try{
    const image_model=$('image-edit-model')?.value||'';
    const response=await fetch(`/api/project/${currentPid}/asset/${encodeURIComponent(imageEditKeyRef)}/regenerate`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt,image_model})
    });
    const result=await response.json();
    if(!response.ok||result.error)throw new Error(result.error||'图片生成失败');
    renderImageEditPreview(result.url);
    updateAssetCardImg(imageEditKeyRef,result.url);
    const {prefix,name}=assetKeyParts(imageEditKeyRef);
    const card=$(`card-${prefix}-${name}`);
    if(card)card.dataset.prompt=result.prompt||prompt;
    imageEditMsg(`已使用${result.provider==='jimeng'?'即梦 API':'ComfyUI'}重新生成，请检查预览。`);
  }catch(error){
    imageEditMsg('生成失败：'+error.message);
  }finally{
    button.disabled=false;
    $('image-edit-confirm').disabled=false;
  }
}
async function confirmImageEdit(){
  if(!currentPid||!imageEditKeyRef)return;
  const button=$('image-edit-confirm');
  button.disabled=true;
  try{
    const response=await fetch(`/api/project/${currentPid}/asset/${encodeURIComponent(imageEditKeyRef)}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:$('image-edit-prompt').value.trim()})});
    const result=await response.json();
    if(!response.ok||result.error)throw new Error(result.error||'确认失败');
    imageEditMsg('图片资产已确认。');
    log(`参考图「${imageEditKeyRef.replace(/^(char|scene|prop)_/,'')}」已确认`,'text-green-400');
    setTimeout(()=>closeImageEdit(),250);
  }catch(error){
    imageEditMsg('确认失败：'+error.message);
    button.disabled=false;
  }
}
function updateShotCardIfPresent(idx,url){
  const card=$('shot-'+idx);if(!card)return;
  const slot=card.querySelector('.video-slot');
  let v=card.querySelector('video');
  if(!v&&slot){
    slot.innerHTML=`<div class="shot-video-wrap"><video src="${url}" controls playsinline preload="metadata" class="w-full rounded-lg"></video></div>`;
    v=slot.querySelector('video');
  }
  if(v){v.src=url;v.removeAttribute('poster');v.dataset.previewReady='';v.load();enableVideoAudio(v);prepareShotVideoPreview(v);}
  if(SHOT_DATA[idx])SHOT_DATA[idx].video_url=url;
}
function openAssetEdit(key,url,prompt){
  editMode='asset';editKeyRef=key;closeEdit();
  $('edit-title').textContent='✏️ 修改图片 · '+key.replace(/^(char|scene|prop)_/,'');
  $('edit-sub').textContent='图片资产';$('edit-sub').classList.remove('hidden');
  $('edit-redraw').textContent='🔄 用此提示词重新生成';$('edit-redraw').disabled=false;
  $('edit-chat-box').classList.remove('hidden');$('edit-reorg').classList.add('hidden');
  $('edit-video-settings').classList.remove('hidden');$('edit-video-settings').style.display='grid';
  $('edit-video-model-box').classList.add('hidden');$('edit-video-duration-box').classList.add('hidden');
  $('edit-image-model-box').classList.remove('hidden');
  $('edit-prompt').value=ASSET_EDIT_DATA[key]?.prompt??prompt??'';
  editRenderPreview('asset',url);editMsg('图片已生成，请检查效果；不满意可修改提示词重新生成。');
  const ref=$('edit-reference-images');
  ref.before($('edit-video-settings'));
  ref.classList.remove('hidden');ref.innerHTML=url?`<div class="text-xs font-bold text-cyan-200 mb-2">参考图</div><button type="button" class="shot-reference-card has-image" onclick="openImageLightbox('${String(url).replace(/'/g,"\\'")}','参考图')"><img src="${String(url).replace(/'/g,"\\'")}" alt="参考图"><span>当前图片</span></button>`:'<div class="text-xs text-gray-500">暂无参考图</div>';
  editShow();loadImageModels(['edit-image-model']);
}
function openShotEdit(idx,url,prompt){
  editMode='shot';editKeyRef=idx;closeEdit();
  $('edit-title').textContent='🎥 分镜 '+idx+' · 请复查';
  $('edit-sub').classList.add('hidden');
  $('edit-redraw').textContent='🔄 用此提示词重新渲染';
  $('edit-redraw').disabled=false;
  $('edit-reorg').classList.add('hidden');
  $('edit-chat-box').classList.remove('hidden');
  $('edit-video-model-box').classList.remove('hidden');
  $('edit-video-duration-box').classList.remove('hidden');
  $('edit-video-settings').classList.remove('hidden');
  $('edit-video-settings').style.display='grid';
  // 参数栏放在左列视频与参考图之间，由四宫格的 settings 区域承载。
  $('edit-reference-images').before($('edit-video-settings'));
  const shotDuration=Number(SHOT_DATA[idx]?.duration||8);
  $('edit-video-duration').value=String([8,10,12,15].includes(shotDuration)?shotDuration:8);
  $('edit-image-model-box').classList.add('hidden');
  loadEditVideoModels();
  loadEditChatModels();
  $('edit-chat-messages').innerHTML='';
  $('edit-chat-input').value='';
  AIChat.resize($('edit-chat-input'));
  $('edit-chat-input').disabled=false;
  $('edit-chat-send').disabled=false;
  editChatHistory=structuredClone(SHOT_DATA[idx]?.chat_history||[]);
  renderEditChat();
  $('edit-prompt').value=SHOT_DATA[idx]?.prompt??prompt??'';
  editRenderPreview('shot',url);editMsg('视频已生成，请检查效果；不满意可改提示词重新渲染，满意后点「满意，继续下一步」。');
  loadShotReferenceImages(idx);
  editShow();
}
async function loadShotReferenceImages(idx){
  const box=$('edit-reference-images'); if(!box)return;
  const pid=currentPid;
  box.classList.remove('hidden'); box.innerHTML='<div class="text-xs text-gray-400">正在加载本镜参考图…</div>';
  try{
    const response=await fetch('/api/project/'+encodeURIComponent(pid),{cache:'no-store'});
    const data=await response.json();
    if(!response.ok||!data.ok)throw new Error(data.msg||'参考图加载失败');
    if(currentPid!==pid||Number(editKeyRef)!==Number(idx))return;
    const project=data.project||{};
    const shot=(project.script?.shots||[]).find(s=>Number(s.index)===Number(idx)) || (project.shots||[]).find(s=>Number(s.index)===Number(idx)) || {};
    const assets=Object.fromEntries((project.assets||[]).map(a=>[a.key,a]));
    const items=[...(shot.characters||[]).map(name=>({kind:'角色',name,key:'char_'+name})),
      ...(shot.scene?[{kind:'场景',name:shot.scene,key:'scene_'+shot.scene}]:[]),
      ...(shot.props||[]).map(name=>({kind:'道具',name,key:'prop_'+name})),
      ...(shot.reference_images||[]).map((key,n)=>({kind:'本镜',name:'添加图片 '+(n+1),key,extra:true}))];
    box.innerHTML='<div class="flex items-center justify-between mb-2"><div class="text-xs font-bold text-cyan-200">本镜参考图</div><div class="text-[10px] text-gray-500">点击查看 · 拖入或悬停更换</div></div>';
    const grid=document.createElement('div');grid.className='flex flex-wrap gap-2';box.appendChild(grid);
    shotReferenceView={pid,index:Number(idx),grid,items,baseCount:items.length};
    items.forEach(item=>grid.appendChild(createShotReferenceCard(item.kind,item.name,item.key,assets[item.key]||{},item.extra)));
    appendShotReferenceAdd(grid,shot,assets);
  }catch(error){box.innerHTML='<div class="text-xs text-gray-500">参考图加载失败</div>';}
}
function createShotReferenceCard(kind,name,key,asset,isExtra){
  const card=document.createElement('div');card.className='shot-reference-card'+(asset.url?' has-image':'');card.dataset.assetKey=key;card.dataset.extra=isExtra?'1':'0';
  const preview=document.createElement('div');preview.className='shot-reference-preview';preview.tabIndex=0;preview.setAttribute('role','button');preview.title='点击图片查看，或拖入图片替换';
  let title=null;
  let replaceOverlay=null;
  const setPreview=(url)=>{
    preview.replaceChildren();
    if(url){const img=document.createElement('img');img.src=url+(url.includes('?')?'&':'?')+'t='+Date.now();img.alt=kind+' · '+name;preview.appendChild(img);card.classList.add('has-image');}
    else{const empty=document.createElement('span');empty.textContent='暂无图片';preview.appendChild(empty);card.classList.remove('has-image');}
    if(replaceOverlay)preview.appendChild(replaceOverlay);
    if(title)preview.appendChild(title);
  };
  replaceOverlay=document.createElement('button');replaceOverlay.type='button';replaceOverlay.className='shot-reference-change';replaceOverlay.textContent='更换';replaceOverlay.title='更换图片';
  replaceOverlay.onclick=(event)=>{event.stopPropagation();chooseShotReferenceFile(key,card,replaceOverlay,setPreview,!!isExtra);};
  setPreview(asset.url||'');
  preview.onclick=()=>{const img=preview.querySelector('img');if(img)openImageLightbox(img.src,kind+' · '+name);};
  preview.onkeydown=(event)=>{if((event.key==='Enter'||event.key===' ')&&event.target===preview){event.preventDefault();preview.click();}};
    title=document.createElement('div');title.className='shot-reference-title text-[11px] text-gray-200 truncate';title.title=kind+' · '+name;title.textContent=kind+' · '+name;
  const status=document.createElement('div');status.className='shot-reference-status hidden';
  preview.appendChild(title);
  card.append(preview,status);
  ['dragenter','dragover'].forEach(type=>card.addEventListener(type,event=>{event.preventDefault();event.stopPropagation();card.classList.add('is-dragover');}));
  ['dragleave','drop'].forEach(type=>card.addEventListener(type,event=>{event.preventDefault();event.stopPropagation();card.classList.remove('is-dragover');}));
  card.addEventListener('drop',event=>{const file=[...(event.dataTransfer?.files||[])].find(item=>item.type.startsWith('image/'));if(file)uploadShotReferenceFile(file,key,card,replaceOverlay,setPreview,!!isExtra);});
  return card;
}
function appendShotReferenceAdd(grid,shot){
  const add=document.createElement('button');add.type='button';add.className='shot-reference-add';add.textContent='＋ 添加图片';add.title='为本镜添加一张独立参考图';
  const refresh=()=>{const base=(shot.characters||[]).length+(shot.scene?1:0)+(shot.props||[]).length;const extra=grid.querySelectorAll('.shot-reference-card[data-extra="1"]').length;const full=base+extra;add.disabled=full>=9;add.title=add.disabled?'每个镜头最多 9 张参考图':'为本镜添加一张独立参考图';add.style.opacity=add.disabled?'.45':'1';};
  add.onclick=()=>{if(add.disabled)return;const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.onchange=()=>{const file=input.files?.[0];if(file)uploadShotReferenceFile(file,'',null,add,null,true);};input.click();};
  grid.appendChild(add);refresh();shotReferenceView.refreshAdd=refresh;
}
function chooseShotReferenceFile(key,card,button,setPreview,isExtra){
  const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';
  input.onchange=()=>{const file=input.files?.[0];if(file)uploadShotReferenceFile(file,key,card,button,setPreview,!!isExtra);};
  input.click();
}
async function uploadShotReferenceFile(file,key,card,button,setPreview,isExtra){
  const pid=shotReferenceView?.pid||currentPid;
  if(!pid||!file)return;
  const busyKey=key||'__new__';
  if(shotReferenceUploads.has(busyKey))return;
  shotReferenceUploads.add(busyKey);
  if(card)card.setAttribute('aria-busy','true');
  if(button)button.disabled=true;
  const status=card?.querySelector('.shot-reference-status');
  if(status){status.textContent='正在保存…';status.classList.remove('hidden');}
  try{
    const form=new FormData();form.append('pid',pid);form.append('file',file);
    let endpoint='/api/upload_asset';
    if(isExtra){endpoint='/api/project/'+encodeURIComponent(pid)+'/shot/'+Number(shotReferenceView.index)+'/reference-images';if(key)form.append('key',key);}
    else form.append('key',key);
    const response=await fetch(endpoint,{method:'POST',headers:window.PLATFORM?.csrf?{'X-CSRF-Token':window.PLATFORM.csrf}:{},body:form});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.msg||result.error||'上传失败');
    if(isExtra&&result.reference&&!key){
      const item=result.reference;
      const add=shotReferenceView.grid.querySelector('.shot-reference-add');
      const newCard=createShotReferenceCard('本镜','添加图片 '+(shotReferenceView.grid.querySelectorAll('.shot-reference-card').length+1),item.key,item,true);
      shotReferenceView.grid.insertBefore(newCard,add);
      if(shotReferenceView.refreshAdd)shotReferenceView.refreshAdd();
    }else if(setPreview)setPreview(result.url);
    if(status){status.textContent='已保存';status.classList.remove('hidden');}
    if(!isExtra){updateAssetCardImg(key,result.url);if(result.sync_required)showReferenceSyncBar();}
    log('本镜参考图'+(isExtra?'已添加':'已更换'),'text-green-400');
  }catch(error){
    if(status){status.textContent='保存失败，请重试';status.classList.remove('hidden');}
    alert((isExtra?'添加':'更换')+'参考图失败：'+error.message);
  }finally{
    shotReferenceUploads.delete(busyKey);
    if(card)card.removeAttribute('aria-busy');
    if(button)button.disabled=false;
  }
}
async function loadEditChatModels(){const s=$('edit-chat-model');if(!s)return;try{const d=await fetchAvailableLLMModels();s.replaceChildren(new Option(d.current?`使用当前 LLM（${d.current}）`:'使用当前 LLM',''),...(d.models||[]).filter(Boolean).map(m=>new Option(m,m)));}catch(_){s.replaceChildren(new Option('使用当前 LLM',''));}}
async function loadEditVideoModels(){
  const select=$('edit-video-model');
  if(!select)return;
  select.replaceChildren(new Option('正在获取官方视频模型…',''));
  try{
    const cfg=await(await fetch('/api/config')).json();
    if(cfg.media_provider!=='jimeng'){
      select.replaceChildren(new Option('当前使用 ComfyUI',''));
      return;
    }
    const response=await fetch('/api/jimeng/models',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({base_url:cfg.jimeng_base_url,api_key:cfg.jimeng_api_key,type:'video'})
    });
    const data=await readJsonResponse(response);
    const current=cfg.jimeng_video_model||'';
    const models=[...new Set([current,...(data.models||[])].filter(Boolean))];
    select.replaceChildren(new Option('使用默认模型', ''),...models.map(model=>new Option(model,model)));
    select.value='';
  }catch(error){
    select.replaceChildren(new Option('模型列表获取失败，使用默认模型',''));
  }
}
function renderEditChat(){
  const box=$('edit-chat-messages');if(!box)return;
  AIChat.render(box,editChatHistory);
}
function resizeEditChatInput(){AIChat.resize($('edit-chat-input'));}
async function sendEditChat(){
  if(editMode!=='shot'||!currentPid)return;
  const pid=currentPid, index=editKeyRef, conversation=editChatHistory;
  const sameEditor=()=>currentPid===pid&&editMode==='shot'&&Number(editKeyRef)===Number(index)&&editChatHistory===conversation;
  const input=$('edit-chat-input'), text=(input?.value||'').trim();
  if(!text)return;
  const btn=$('edit-chat-send');btn.disabled=true;input.disabled=true;
  editChatHistory.push({role:'user',content:text});renderEditChat();input.value='';resizeEditChatInput();
  editChatHistory.push({role:'assistant',content:'AI 正在根据当前分镜调整提示词…'});renderEditChat();
  try{
    const history=editChatHistory.slice(0,-1);
    const r=await(await fetch(`/api/project/${pid}/shot/${index}/prompt-chat`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:$('edit-prompt').value.trim(),message:text,history,model:$('edit-chat-model')?.value||''})
    })).json();
    if(!r.ok||r.error)throw new Error(r.error||r.msg||'AI修改失败');
    if(currentPid===pid){
      SHOT_DATA[index]={...(SHOT_DATA[index]||{index}),prompt:r.prompt,chat_history:r.chat_history||[...conversation.slice(0,-1),{role:"assistant",content:r.reply}],edit_revisions:r.edit_revisions||[]};
      const shot=(SCRIPT_DATA?.shots||[]).find(s=>Number(s.index)===Number(index));
      if(shot)shot.prompt=r.prompt;
      const confirm=$('confirm-prompt-'+index);if(confirm)confirm.value=r.prompt;
      if(window._lastFinalData&&!$('final-box').classList.contains('hidden'))markFinalNeedsResynth();
    }
    if(!sameEditor())return;
    editChatHistory.pop();
    editChatHistory.push({role:'assistant',content:r.reply||'已按你的要求修改提示词，请检查下方文本。'});
    $('edit-prompt').value=r.prompt||$('edit-prompt').value;
    editMsg('AI 已修改并保存提示词；确认无误后点击「重新渲染」。');
  }catch(e){
    if(!sameEditor())return;
    editChatHistory.pop();editChatHistory.push({role:'assistant',content:'修改失败：'+e.message});
    editMsg('❌ '+e.message);
  }finally{
    if(sameEditor()){renderEditChat();btn.disabled=false;input.disabled=false;AIChat.resize(input);input.focus();}
  }
}
async function editRedraw(){
  const rerenderPid=currentPid, rerenderIndex=editKeyRef;
  const prompt=$('edit-prompt').value.trim();
  if(!prompt){editMsg('提示词为空');return;}
  const btn=$('edit-redraw');const orig=btn.innerHTML;btn.disabled=true;
  try{
    if(editMode==='asset'){
      editMsg('重新生成参考图中（约几十秒）…');
      const image_model=$('edit-image-model')?.value||'';
      const r=await(await fetch(`/api/project/${rerenderPid}/asset/${encodeURIComponent(editKeyRef)}/regenerate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,image_model})})).json();
      if(r.error){editMsg('❌ '+r.error);return;}
      editRenderPreview('asset',r.url+'?t='+Date.now());updateAssetCardImg(editKeyRef,r.url);
      editMsg(`已使用${r.provider==='jimeng'?'即梦 API':'ComfyUI'}重新生成，请检查这张参考图。`);
    }else{
      editMsg('正在重新渲染该镜（约几分钟）…');
      const r=await(await fetch(`/api/project/${rerenderPid}/shot/${rerenderIndex}/rerender`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,video_model:$('edit-video-model')?.value||'',duration:Number($('edit-video-duration')?.value||8)})})).json();
      if(r.error){editMsg('❌ '+r.error);return;}

      const vid=$('edit-preview video');if(vid)vid.parentNode.innerHTML='<div class="text-gray-500 text-sm">重渲染进行中，完成后自动刷新…</div>';
      startShotRerenderProgress(rerenderIndex);
      if(editPoll)clearInterval(editPoll);
      let rerenderFinished=false;
      const finishRerender=async(url)=>{
        if(rerenderFinished)return;
        rerenderFinished=true;
        clearInterval(editPoll);editPoll=null;
        if(currentPid!==rerenderPid)return;
        let finalUrl=url||'';
        // 以项目存档中的当前镜头为准，避免任务状态先返回而前端拿到旧地址。
        try{
          const projectResponse=await fetch(`/api/project/${rerenderPid}?t=${Date.now()}`,{cache:'no-store'});
          if(projectResponse.ok){
            const projectData=await projectResponse.json();
            const shot=(projectData.project?.shots||[]).find(item=>Number(item.index)===Number(rerenderIndex));
            if(shot?.video_url&&!shot.error){
              SHOT_DATA[rerenderIndex]={...(SHOT_DATA[rerenderIndex]||{}),...shot};
              if(projectData.project.previous_final)markFinalNeedsResynth();
              finalUrl=shot.video_url;
            }
          }
        }catch(e){}
        if(finalUrl){
          const cacheBustedUrl=finalUrl.includes('?')?`${finalUrl}&refresh=${Date.now()}`:`${finalUrl}?refresh=${Date.now()}`;
          updateShotCardIfPresent(rerenderIndex,cacheBustedUrl);
          if(Number(editKeyRef)===Number(rerenderIndex)){editRenderPreview('shot',cacheBustedUrl);editMsg('已重新渲染，请检查。');}
        }else{
          const card=$('shot-'+rerenderIndex);const slot=card?card.querySelector('.video-slot'):null;
          if(slot)slot.innerHTML='<div class="text-red-300 text-sm">重制完成，但没有返回视频地址，请刷新后重试</div>';
          editMsg('❌ 重制完成，但没有返回视频地址');
        }
      };
      let polling=false;
      editPoll=setInterval(async()=>{
        if(polling)return;polling=true;
        if(currentPid!==rerenderPid){polling=false;return;}
        try{
          const response=await fetch(`/api/project/${rerenderPid}/rerender/status/${r.task_id}?index=${encodeURIComponent(rerenderIndex)}`);
          if(!response.ok)throw new Error(`任务状态 HTTP ${response.status}`);
          const st=await response.json();
          if(st.status==='done')finishRerender(st.video_url);
          else if(st.status==='error'){
            clearInterval(editPoll);editPoll=null;
            const card=$('shot-'+rerenderIndex);const slot=card?card.querySelector('.video-slot'):null;
            if(slot)slot.innerHTML='<div class="text-red-300 text-sm">重制失败，请检查错误后重试</div>';
            editMsg('❌ '+st.msg);
          }else{
            updateShotRenderProgress({
              index:rerenderIndex,
              percent:st.progress||0,
              elapsed:st.elapsed||0,
              eta:st.eta||0,
              phase:st.phase||'重新渲染中',
              estimated:!!st.progress_estimated
            });
            const el=$('edit-msg');if(el)el.innerHTML=taskProgressHtml(st,'重新渲染中');
          }
        }catch(e){editMsg('重渲染连接暂时中断，正在自动重试…');}finally{polling=false;}
      },1000);
    }
  }catch(e){editMsg('❌ '+e.message);}
  btn.disabled=false;btn.innerHTML=orig;
}
async function editConfirm(){
  const prompt=$('edit-prompt').value.trim();
  try{
    if(editMode==='asset'){
      await fetch(`/api/project/${currentPid}/asset/${encodeURIComponent(editKeyRef)}/confirm`,{method:'POST'});
      log('参考图「'+editKeyRef.replace(/^(char|scene|prop)_/,'')+'」已确认，流程继续','text-green-400');
    }else{
      await fetch(`/api/project/${currentPid}/shot/${editKeyRef}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviewed:true,prompt})});
      log('分镜'+editKeyRef+'已确认，流程继续','text-green-400');
    }
    closeEdit();
  }catch(e){editMsg('❌ '+e.message);}
}
function editReorganize(){if(editMode==='shot')$('edit-chat-input')?.focus();else editMsg('参考图暂支持直接编辑提示词后重新生成。');}
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function formatRenderSeconds(sec){sec=Math.max(0,parseInt(sec)||0);const m=Math.floor(sec/60),s=sec%60;return `${m}:${String(s).padStart(2,'0')}`;}
function startShotRerenderProgress(idx){
  const card=$('shot-'+idx);if(!card)return;
  const slot=card.querySelector('.video-slot');if(!slot)return;
  slot.innerHTML='';
  showShotRenderProgress(idx,{percent:0,elapsed:0,eta:0,phase:'等待重渲染',estimated:false});
}
function showShotRenderProgress(idx,data={}){
  const card=$('shot-'+idx);if(!card)return;
  const slot=card.querySelector('.video-slot');if(!slot)return;
  if(slot.querySelector('video')&&!data.force)return;
  const pct=Math.max(0,Math.min(100,parseInt(data.percent)||0));
  const phase=data.phase||'H3渲染中';
  const elapsed=formatRenderSeconds(data.elapsed||0);
  const eta=formatRenderSeconds(data.eta||0);
  const approx=data.estimated?'≈':'';
  const attempt=data.attempt?` · 自动重做 ${data.attempt}`:'';
  slot.className='video-slot bg-black/30 rounded-lg p-4';
  slot.innerHTML=`<div class="shot-render-progress" data-progress-idx="${idx}">
    <div class="flex items-center justify-between text-xs mb-2 gap-2">
      <span class="gold truncate">⏳ ${escapeHtml(phase)}${attempt}</span>
      <span class="font-mono text-gray-300 progress-pct">${approx}${pct}%</span>
    </div>
    <div class="h-2.5 rounded-full bg-white/10 overflow-hidden">
      <div class="render-progress-fill h-full rounded-full transition-all duration-500" style="width:${pct}%;background:linear-gradient(90deg,#f5b942,#ff8a3d);"></div>
    </div>
    <div class="flex items-center justify-between mt-2 text-[11px] text-gray-500">
      <span class="progress-elapsed">已用 ${elapsed}</span>
      <span class="progress-eta">预计剩余 ${eta}${data.estimated?' · 估算':''}</span>
    </div>
  </div>`;
}
function updateShotRenderProgress(data){
  const idx=data.index;const card=$('shot-'+idx);if(!card)return;
  let box=card.querySelector('.shot-render-progress');
  if(!box){showShotRenderProgress(idx,data);box=card.querySelector('.shot-render-progress');if(!box)return;}
  const pct=Math.max(0,Math.min(100,parseInt(data.percent)||0));
  const fill=box.querySelector('.render-progress-fill');if(fill)fill.style.width=pct+'%';
  const pe=box.querySelector('.progress-pct');if(pe)pe.textContent=(data.estimated?'≈':'')+pct+'%';
  const el=box.querySelector('.progress-elapsed');if(el)el.textContent='已用 '+formatRenderSeconds(data.elapsed||0);
  const eta=box.querySelector('.progress-eta');if(eta)eta.textContent='预计剩余 '+formatRenderSeconds(data.eta||0)+(data.estimated?' · 估算':'');
  const title=box.querySelector('.gold');if(title)title.textContent='⏳ '+(data.phase||'H3渲染中')+(data.attempt?` · 自动重做 ${data.attempt}`:'');
}
function taskProgressHtml(t,label='H3渲染中'){
  const pct=Math.max(0,Math.min(100,parseInt(t.progress)||0));
  return `<div class="text-left"><div class="flex justify-between text-xs mb-1"><span>${escapeHtml(t.phase||label)}</span><span class="font-mono">${t.progress_estimated?'≈':''}${pct}%</span></div><div class="h-2 rounded-full bg-white/10 overflow-hidden"><div class="h-full rounded-full transition-all duration-500" style="width:${pct}%;background:linear-gradient(90deg,#f5b942,#ff8a3d);"></div></div><div class="flex justify-between mt-1 text-[11px] text-gray-500"><span>已用 ${formatRenderSeconds(t.elapsed||0)}</span><span>预计剩余 ${formatRenderSeconds(t.eta||0)}${t.progress_estimated?' · 估算':''}</span></div></div>`;
}
function updateShotMetaDisplay(idx,duration,camera){if(!SHOT_DATA[idx])SHOT_DATA[idx]={index:idx};if(duration!==undefined&&duration!==null)SHOT_DATA[idx].duration=parseInt(duration)||SHOT_DATA[idx].duration||8;if(camera!==undefined)SHOT_DATA[idx].camera=String(camera||'').trim();const meta=$('shot-meta-'+idx);if(meta){const d=SHOT_DATA[idx].duration||8;const c=SHOT_DATA[idx].camera||'';meta.textContent=`${d}s${c?` · ${c}`:''}`;}}
function setConfirmDuration(idx,val){const el=document.getElementById('confirm-duration-'+idx);if(el)el.value=String(val);}
function setConfirmCamera(idx,val){const el=document.getElementById('confirm-camera-'+idx);if(el)el.value=String(val||'');}
function showShotBatchEditor(idx,prompt,duration,camera){
  const card=$('shot-'+idx);
  if(!card||card.querySelector('video'))return;
  const slot=card.querySelector('.video-slot');
  if(!slot)return;
  if(!SHOT_DATA[idx])SHOT_DATA[idx]={index:idx};
  SHOT_DATA[idx].prompt=prompt;
  updateShotMetaDisplay(idx,duration||SHOT_DATA[idx].duration||8,camera!==undefined?camera:(SHOT_DATA[idx].camera||''));
  const curDuration=SHOT_DATA[idx].duration||8;
  const curCamera=SHOT_DATA[idx].camera||'';
  const shot=(SCRIPT_DATA?.shots||[]).find(shot=>shot.index===idx)||SHOT_DATA[idx];
  const intro=String(shot.action||shot.scene||'镜头提示词已就绪，可勾选后生成。');
  slot.innerHTML=`
    <div class="rounded-lg bg-black/40 border border-yellow-400/30 p-3" data-shot-batch-editor="1" data-shot-index="${idx}">
      <div class="flex items-center justify-between mb-2 gap-3">
        <label class="flex items-center gap-2 text-xs gold cursor-pointer"><input type="checkbox" id="batch-check-${idx}" class="accent-yellow-500" checked onchange="updatePromptBatchSelectionInfo()"> 生成这个镜头</label>
        <button type="button" class="text-xs px-2 py-1 rounded glass gold shrink-0" aria-expanded="false" aria-controls="batch-settings-${idx}" onclick="const panel=$('batch-settings-${idx}');const expanded=panel.classList.toggle('hidden')===false;this.setAttribute('aria-expanded',String(expanded));this.textContent=expanded?'收起':'修改'">修改</button>
      </div>
      <p class="text-left text-xs text-gray-400 leading-relaxed mb-0">${escapeHtml(intro.length>100?intro.slice(0,100)+'…':intro)}</p>
      <div id="batch-settings-${idx}" class="hidden mt-3">
      <div class="grid grid-cols-2 gap-2 mb-2">
        <label class="text-xs text-gray-400">时长（秒）
          <input id="confirm-duration-${idx}" type="number" min="8" max="15" value="${curDuration}" class="mt-1 w-full bg-black/40 border border-white/10 rounded-lg px-2 py-2 text-xs">
          <div class="flex flex-wrap gap-1 mt-2">
            ${[8,10,12,15].map(v=>`<button type="button" onclick="setConfirmDuration(${idx},${v})" class="text-[11px] px-2 py-1 rounded glass hover:bg-yellow-400/20 transition text-gray-300">${v}s</button>`).join('')}
          </div>
        </label>
        <label class="text-xs text-gray-400">景别/机位
          <input id="confirm-camera-${idx}" type="text" value="${escapeHtml(curCamera)}" placeholder="例如：固定中景 / 跟随镜头 / 推近特写" class="mt-1 w-full bg-black/40 border border-white/10 rounded-lg px-2 py-2 text-xs">
          <div class="flex flex-wrap gap-1 mt-2">
            ${['特写','近景','中景','全景','跟拍','推镜','拉镜','环绕','俯视','仰视'].map(v=>`<button type="button" onclick="setConfirmCamera(${idx},'${v}')" class="text-[11px] px-2 py-1 rounded glass hover:bg-yellow-400/20 transition text-gray-300">${v}</button>`).join('')}
          </div>
        </label>
      </div>
      </div>
    </div>`;
}
function promptSelectionBoxes(){
  return Array.from(document.querySelectorAll('input[id^="batch-check-"], .shot-rerender-check'));
}
function promptSelectionIndex(input){return parseInt(input.dataset.shotIndex||input.id.slice('batch-check-'.length));}
function collectPromptBatchEdits(){
  const editors=Array.from(document.querySelectorAll('[data-shot-batch-editor="1"]'));
  const indexes=new Set((SCRIPT_DATA?.shots||[]).map(shot=>Number(shot.index)));
  editors.forEach(el=>indexes.add(parseInt(el.getAttribute('data-shot-index'))));
  promptSelectionBoxes().forEach(input=>{
    const idx=promptSelectionIndex(input);
    if(Number.isFinite(idx))indexes.add(idx);
  });
  return [...indexes].sort((a,b)=>a-b).map(idx=>{
    const shot={...(SCRIPT_DATA?.shots||[]).find(s=>s.index===idx),...SHOT_DATA[idx]};
    return {
      index:idx,
      selected:promptSelectionBoxes().some(input=>promptSelectionIndex(input)===idx&&input.checked),
      prompt:(document.getElementById('confirm-prompt-'+idx)?.value||shot.prompt||'').trim(),
      duration:Math.max(8,Math.min(15,parseInt(document.getElementById('confirm-duration-'+idx)?.value)||shot.duration||8)),
      camera:(document.getElementById('confirm-camera-'+idx)?.value||shot.camera||'').trim()
    };
  });
}
function updatePromptBatchSelectionInfo(){
  const all=collectPromptBatchEdits();
  const selected=all.filter(x=>x.selected).length;
  const box=$('prompt-batch-selected');if(box)box.textContent=`已选 ${selected} / ${all.length} 镜`;
  const button=$('btn-batch-render');
  if(button&&!button.disabled)button.textContent=`🚀 生成选中 ${selected} 镜`;
  return {all,selected};
}
function setPromptShotSelection(predicate){
  promptSelectionBoxes().forEach(input=>{
    input.checked=!!predicate(promptSelectionIndex(input));
    if(input.classList.contains('shot-rerender-check'))input.closest('label')?.setAttribute('data-selected',input.checked?'true':'false');
  });
  updateRenderedSelectionCount();
  updatePromptBatchSelectionInfo();
  // 单镜重制/替换后重新开放分镜确认入口，避免旧的待确认状态被清掉。
  const scripted = SCRIPT_DATA?.shots || [];
  const rendered = scripted.length > 0 && scripted.every(s => SHOT_DATA[s.index]?.video_url && !SHOT_DATA[s.index]?.error);
  if (rendered && $('final-box')?.classList.contains('hidden') && !$('shots-confirm-bar')) {
    showShotsConfirmBar({shots: scripted.map(s => SHOT_DATA[s.index])});
  }
}
function selectAllPromptShots(flag=true){setPromptShotSelection(()=>flag);}
function applyPromptBatchRange(){
  const s=parseInt($('batch-shot-start')?.value)||1,e=parseInt($('batch-shot-end')?.value)||s;
  setPromptShotSelection(idx=>idx>=Math.min(s,e)&&idx<=Math.max(s,e));
}
async function loadRenderGroups(){
  const pid=currentPid;
  try{
    const data=await(await fetch(`/api/project/${pid}`)).json();
    if(pid!==currentPid||!data.ok)return;
    showRenderGroups(data.project.render_groups||[]);
    for(const [index,failure] of Object.entries(data.project.prompt_failures||{})){
      if(failure.status==='needs_edit'&&failure.prompt){
        const shot=(data.project.script?.shots||[]).find(s=>s.index===Number(index))||{};
        showShotBatchEditor(Number(index),failure.prompt,shot.duration,shot.camera);
        log(`第${index}镜草稿待修改：${(failure.problems||[]).join('；')}`);
      }
    }
  }catch(error){log('读取镜头分组失败：'+error.message);}
}
function showRenderGroups(groups){
  let box=$('render-groups');
  // 分组仅用于后台调度，前端不再展示，保持分镜区界面简洁。
  if(box)box.remove();
}
function showPromptBatchBar(data){
  loadRenderGroups();
  const drafts=new Map((data?.shots||[]).map(shot=>[shot.index,shot]));
  for(const scripted of SCRIPT_DATA?.shots||[]){
    const shot={...scripted,...SHOT_DATA[scripted.index],...drafts.get(scripted.index)};
    if(shot.video_url)continue;
    if(!$('batch-check-'+shot.index))showShotBatchEditor(shot.index,shot.prompt||'',shot.duration,shot.camera);
  }
  let bar=$('prompt-batch-bar');
  if(!bar){bar=document.createElement('div');bar.id='prompt-batch-bar';bar.className='glass rounded-2xl p-4 mb-4';const grid=$('shot-grid');$('shots-box').insertBefore(bar,grid);}
  const items=collectPromptBatchEdits();
  const total=items.length;
  const lastIndex=Math.max(1,...items.map(item=>item.index));
  bar.innerHTML=`<div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
    <div>
      <div class="font-bold gold">📝 全剧 ${total} 镜 · 批量生成</div>
      <div class="text-xs text-gray-400 mt-1">按范围、全选或清空可控制下方全部镜头。选中已有视频会重新生成并保存旧版本。</div>
    </div>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span id="prompt-batch-selected" class="tag">已选 0 / ${total} 镜</span>
      <input id="batch-shot-start" type="number" min="1" value="1" oninput="applyPromptBatchRange()" class="bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 w-16 text-center">
      <span class="text-gray-500">到</span>
      <input id="batch-shot-end" type="number" min="1" value="${lastIndex}" oninput="applyPromptBatchRange()" class="bg-black/30 border border-white/10 rounded-lg px-2 py-1.5 w-16 text-center">
      <button onclick="selectAllPromptShots(true)" class="px-3 py-1.5 rounded-lg glass hover:bg-white/10 transition">全选</button>
      <button onclick="selectAllPromptShots(false)" class="px-3 py-1.5 rounded-lg glass hover:bg-white/10 transition">清空</button>
      <button id="btn-preview-render" onclick="generateSelectedShots(true)" class="px-4 py-2 rounded-lg glass hover:bg-yellow-400/20">⚡ 渲染小样</button>
      <button id="btn-batch-render" onclick="generateSelectedShots(false)" class="btn-gold px-4 py-2 rounded-lg">🚀 生成选中镜头</button>
      <button id="btn-render-missing" onclick="generateSelectedShots(false,true)" class="btn-gold px-4 py-2 rounded-lg">🚀 生成全部未完成镜头</button>
    </div>
  </div>`;
  setTimeout(updatePromptBatchSelectionInfo,0);
}
async function generateSelectedShots(preview=false,allMissing=false){
  if(!currentPid){log('❌ 尚未加载项目，无法渲染小样','text-red-400');return;}
  if(preview ? $('btn-preview-render')?.disabled : $('btn-batch-render')?.disabled)return;
  const edits=collectPromptBatchEdits();
  let selected=edits.filter(item=>item.selected).map(item=>item.index);
  if(!allMissing&&!selected.length){alert('请勾选镜头，或点击“生成全部未完成镜头”');return;}
  const setBusy=busy=>{
    const button=$('btn-batch-render');
    const previewButton=$('btn-preview-render');
    if(button)button.disabled=busy;
    if(previewButton)previewButton.disabled=busy;
    if($('btn-render-missing'))$('btn-render-missing').disabled=busy;
    if(button&&busy)button.textContent=preview?'⚡ 小样生成中...':'🎬 批量生成中...';
    if(!busy)updatePromptBatchSelectionInfo();
  };
  setBusy(true);
  try{
    if(allMissing){
      // Include an explicit full selection for servers still finishing a render
      // on the previous version; upgraded servers also resolve scope=missing.
      const latest=await(await fetch(`/api/project/${currentPid}`,{cache:'no-store'})).json();
      if(!latest.ok)throw new Error(latest.msg||'读取完整剧本失败');
      const rendered=new Map((latest.project.shots||[]).map(shot=>[shot.index,shot]));
      selected=(latest.project.script?.shots||[]).filter(shot=>{
        const result=rendered.get(shot.index)||{};
        return !result.video_url||result.error||result.continuity_stale||result.reference_video_stale;
      }).map(shot=>shot.index);
      if(!selected.length){log('全部镜头已有视频，无需重复生成','gold');setBusy(false);return;}
    }
    const r=await(await fetch(`/api/project/${currentPid}/shots/batch_update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({shots:edits.filter(item=>item.prompt)})})).json();
    if(!r.ok){alert(r.msg||'保存批量提示词失败');setBusy(false);return;}
    const indexes=selected.join(',');
    const streamNonce=Date.now().toString(36);
    const streamUrl=`/api/project/${currentPid}/shots/render_selected_stream?indexes=${encodeURIComponent(indexes)}${allMissing?'&scope=missing':''}${preview?'&preview=1':''}&_stream=${streamNonce}`;
    // 用 fetch 读取 SSE，避免 EventSource 把服务端 error 事件吞成笼统的连接错误。
    const sseListeners={}; let sseClosed=false;
    const es2={
      addEventListener(name,fn){(sseListeners[name]||(sseListeners[name]=[])).push(fn);},
      close(){sseClosed=true;},
      emit(name,data){for(const fn of (sseListeners[name]||[])){try{fn({data});}catch(err){console.error(err);}}},
      onerror:null
    };
    (async()=>{
      try{
        const response=await fetch(streamUrl,{headers:{Accept:'text/event-stream',...(window.PLATFORM?.csrf?{'X-CSRF-Token':window.PLATFORM.csrf}:{})}});
        if(!response.ok){let detail=`HTTP ${response.status}`, code='';try{const body=await response.json();detail=body.msg||body.error||detail;code=body.code||'';}catch(_){}const error=new Error(detail);error.code=code;throw error;}
        log(preview?'小样任务已连接，开始渲染…':'批量渲染任务已连接…','text-green-400');
        const reader=response.body?.getReader(); if(!reader)throw new Error('浏览器不支持流式读取');
        const decoder=new TextDecoder(); let buffer='';
        while(!sseClosed){
          const part=await reader.read(); if(part.done)break;
          buffer+=decoder.decode(part.value,{stream:true});
          const blocks=buffer.split(/\r?\n\r?\n/); buffer=blocks.pop()||'';
          for(const block of blocks){
            const event=(block.match(/^event:\s*(.+)$/m)||[])[1]||'message';
            const data=(block.match(/^data:\s*(.*)$/m)||[])[1]||'';
            es2.emit(event,data);
          }
        }
        if(!sseClosed)es2.emit('end','');
      }catch(err){
        if(!sseClosed){
          const detail=err?.message||String(err);
          es2.emit('error',JSON.stringify({msg:detail,code:err?.code||''}));
          if(es2.onerror)es2.onerror({data:JSON.stringify({msg:detail,code:err?.code||''})});
        }
      }
    })();
    es2.addEventListener('start',e=>{const d=JSON.parse(e.data);const submitted=d.indexes||selected;log(`本次提交 ${submitted.length} / 全剧 ${d.total||SCRIPT_DATA?.shots?.length||0} 镜：${submitted.join('、')}`,'gold');});
    es2.addEventListener('render_groups',e=>showRenderGroups(JSON.parse(e.data).groups||[]));
    es2.addEventListener('stage',e=>{const d=JSON.parse(e.data);if(d.status==='running'){setStage(d.stage,'stage-active');log(`【${d.name}】${d.msg||'开始...'}`);}else if(d.status==='done'){setStage(d.stage,'stage-done');log(`【${d.name}】完成`,'text-green-400');}});
    es2.addEventListener('progress',e=>{const d=JSON.parse(e.data);log(`选中镜头进度 ${d.done}/${d.total}`);});
    es2.addEventListener('shot_status',e=>{const d=JSON.parse(e.data);log(d.msg);const card=$('shot-'+d.index);if(card){const slot=card.querySelector('.video-slot');if(d.status==='render')showShotRenderProgress(d.index,{percent:0,elapsed:0,eta:0,phase:'H3准备渲染'});else if(d.status==='prompt_ready')slot.innerHTML=`<span class="text-green-400">提示词已就绪，等待渲染…</span>`;else if(slot)slot.innerHTML=`<span class="gold" style="animation:pulse 1.2s infinite;display:inline-block">⏳ AI撰写提示词中…</span>`;}});
    es2.addEventListener('shot_render_progress',e=>{const d=JSON.parse(e.data);updateShotRenderProgress(d);});
    es2.addEventListener('shot',e=>{const d=JSON.parse(e.data);SHOT_DATA[d.index]=d;addShotCard(d);log(`第${d.index}镜视频完成`,'text-green-400');updatePromptBatchSelectionInfo();});
    es2.addEventListener('shot_error',e=>{const d=JSON.parse(e.data);SHOT_DATA[d.index]={...(SHOT_DATA[d.index]||{index:d.index}),index:d.index,refs:d.refs||[],prompt:d.prompt||''};showShotError(d.index,d.msg||'生成失败');});
    es2.addEventListener('render_selected_done',e=>{const d=JSON.parse(e.data);if(preview){if(confirm('小样已生成，是否确认通过并允许生成正常尺寸视频？')){localStorage.setItem(`preview-approved:${currentPid}`,'1');log('小样审查通过，可以生成正常尺寸视频。','gold');}else log('小样待审查，确认通过后才可生成正常尺寸。','text-yellow-300');}else if(d.all_rendered){log('全部镜头已生成完成；请逐镜复查，确认后使用底部按钮合成成片。','gold');}else{log('选中的镜头已生成完成；你可以继续勾选其余镜头批量生成。','gold');}});
    let serverError=false;
    es2.addEventListener('error',e=>{
      serverError=true;
      try{
        const d=JSON.parse(e.data||'{}');
        if(d.code==='reference_sync_required'||/参考图已更新/.test(d.msg||'')){
          log('参考图已更新，请确认同步提示词后再渲染小样','text-yellow-300');
          openReferenceSyncApproval();
        }else{log(`❌ ${d.msg||'批量生成失败'}`,'text-red-400');loadRenderGroups();}
      }
      catch(_){log('❌ 批量生成失败：服务器未返回具体错误','text-red-400');}
    });
    es2.addEventListener('end',()=>{setBusy(false);es2.close();});
    es2.onerror=e=>{
      es2.close();setBusy(false);
      if(!serverError)log('批量生成连接中断，请检查失败镜头后重试（可能是登录会话或服务器重启）','text-red-400');
    };
  }catch(e){alert('批量生成失败: '+e.message);setBusy(false);}
}
// 手动确认模式：某镜提示词就绪后展示可编辑的提示词，用户确认/修改后再渲染
function showShotConfirm(idx,prompt,duration,camera){
  const card=$('shot-'+idx);
  if(!card||card.querySelector('video'))return;
  const slot=card.querySelector('.video-slot');
  if(!slot||slot.querySelector('textarea'))return;
  if(!SHOT_DATA[idx])SHOT_DATA[idx]={index:idx};
  SHOT_DATA[idx].prompt=prompt;
  updateShotMetaDisplay(idx,duration||SHOT_DATA[idx].duration||8,camera!==undefined?camera:(SHOT_DATA[idx].camera||''));
  const curDuration=SHOT_DATA[idx].duration||8;
  const curCamera=SHOT_DATA[idx].camera||'';
  slot.innerHTML=`
    <div class="rounded-lg bg-black/40 border border-yellow-400/30 p-3">
      <div class="flex items-center justify-between mb-2"><span class="text-xs gold">✏️ 该镜生成前可先修改：提示词 / 时长 / 景别</span>
        <button onclick="autoConfirmSkip(${idx})" class="text-xs px-2 py-1 rounded glass hover:bg-white/10 transition text-gray-300">⏭️ 不修改，直接生成</button></div>
      <div class="grid grid-cols-2 gap-2 mb-2">
        <label class="text-xs text-gray-400">时长（秒）
          <input id="confirm-duration-${idx}" type="number" min="8" max="15" value="${curDuration}" class="mt-1 w-full bg-black/40 border border-white/10 rounded-lg px-2 py-2 text-xs">
          <div class="flex flex-wrap gap-1 mt-2">
            ${[8,10,12,15].map(v=>`<button type="button" onclick="setConfirmDuration(${idx},${v})" class="text-[11px] px-2 py-1 rounded glass hover:bg-yellow-400/20 transition text-gray-300">${v}s</button>`).join('')}
          </div>
        </label>
        <label class="text-xs text-gray-400">景别/机位
          <input id="confirm-camera-${idx}" type="text" value="${escapeHtml(curCamera)}" placeholder="例如：固定中景 / 跟随镜头 / 推近特写" class="mt-1 w-full bg-black/40 border border-white/10 rounded-lg px-2 py-2 text-xs">
          <div class="flex flex-wrap gap-1 mt-2">
            ${['特写','近景','中景','全景','跟拍','推镜','拉镜','环绕','俯视','仰视'].map(v=>`<button type="button" onclick="setConfirmCamera(${idx},'${v}')" class="text-[11px] px-2 py-1 rounded glass hover:bg-yellow-400/20 transition text-gray-300">${v}</button>`).join('')}
          </div>
        </label>
      </div>
      <textarea id="confirm-prompt-${idx}" rows="7" class="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-xs resize-y font-mono">${escapeHtml(prompt)}</textarea>
      <button onclick="confirmShot(${idx})" class="btn-gold w-full mt-2 py-2 rounded-lg text-xs">✅ 确认并生成此镜</button>
    </div>`;
  slot.scrollIntoView({behavior:'smooth',block:'center'});
}
function autoConfirmSkip(idx){confirmShot(idx,true);}
async function confirmShot(idx,skip){
  const prompt=skip?'' : (document.getElementById('confirm-prompt-'+idx)?.value||'');
  const duration=Math.max(8,Math.min(15,parseInt(document.getElementById('confirm-duration-'+idx)?.value)||SHOT_DATA[idx]?.duration||8));
  const camera=(document.getElementById('confirm-camera-'+idx)?.value||SHOT_DATA[idx]?.camera||'').trim();
  if(!currentPid)return;
  try{
    await fetch(`/api/project/${currentPid}/shot/${idx}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,skip:!!skip,duration,camera})});
    updateShotMetaDisplay(idx,duration,camera);
    const card=$('shot-'+idx);const slot=card?card.querySelector('.video-slot'):null;
    if(slot)slot.innerHTML=`<span class="gold" style="animation:pulse 1.2s infinite;display:inline-block">⏳ 已确认：${duration}s${camera?` · ${escapeHtml(camera)}`:''}，H3渲染视频中，请稍候…</span>`;
    log(`镜头${idx}已确认，按 ${duration}s${camera?` / ${camera}`:''} 开始手动生成该镜`,'gold');
  }catch(e){alert('确认失败: '+e.message);}
}
// 分镜生成失败：标红卡片，并给出"立即重制"入口（只重做该镜，其余保留）
function showShotError(idx,msg){
  const card=$('shot-'+idx);
  if(SHOT_DATA[idx])SHOT_DATA[idx].error=msg;
  if(card){card.style.border='1px solid rgba(239,69,101,.55)';}
  const slot=card?card.querySelector('.video-slot'):null;
  if(slot&&!slot.querySelector('video')&&!slot.querySelector('textarea')){
    slot.innerHTML=`<div class="text-center text-xs py-4" style="color:#ef4565">❌ ${escapeHtml(msg)}</div>
      <div class="text-center mt-1"><button onclick="remakeShot(${idx})" class="text-xs px-3 py-1.5 rounded-lg btn-gold">🔄 立即重制此镜</button></div>`;
  }else if(card){
    let err=card.querySelector('.shot-err');
    if(!err){err=document.createElement('div');err.className='shot-err text-xs mt-2';err.style.color='#ef4565';card.appendChild(err);}
    err.textContent='❌ '+msg;
  }
  log('镜头'+idx+'生成失败: '+msg,'text-red-400');
}
function enableVideoAudio(video){
  if(!video)return;
  video.muted=false;
  video.defaultMuted=false;
  video.volume=1;
}
// 有失败镜：展示"重新合成"按钮（重制完失败镜后点它，仅合并已成功分镜）
function showResynthUI(d){
  const old=$('resynth-bar');if(old)old.remove();
  const bar=document.createElement('div');
  bar.id='resynth-bar';
  bar.className='glass rounded-2xl p-5 mt-4 text-center';
  bar.innerHTML=`<div class="text-red-400 text-sm mb-2">⚠️ ${escapeHtml(d.msg||'有分镜生成失败')}</div>
    <button onclick="submitResynth()" id="btn-resynth" class="btn-gold px-8 py-2.5 rounded-xl text-sm">✅ 重新合成成片（仅合并已成功分镜）</button>`;
  $('shots-box').appendChild(bar);
  if (!loadingProjectView) bar.scrollIntoView({behavior:'smooth',block:'center'});
}
function submitResynth(){
  if(!currentPid||!$('btn-resynth'))return;
  const btn=$('btn-resynth');btn.disabled=true;btn.textContent='合成中...';
  if(resynthES)resynthES.close();
  resynthES=new EventSource(`/api/project/${currentPid}/resynth`);
  resynthES.addEventListener('stage',e=>{const d=JSON.parse(e.data);
    if(d.status==='running'){setStage(d.stage,'stage-active');log(`【${d.name}】${d.msg||'合成中...'}`);}
    else if(d.status==='done'){setStage(d.stage,'stage-done');log(`【${d.name}】完成`,'text-green-400');}});
  resynthES.addEventListener('final',e=>{const d=JSON.parse(e.data);showFinal(d);const b=$('resynth-bar');if(b)b.remove();});
  resynthES.addEventListener('error',e=>{try{const d=JSON.parse(e.data);log('❌ '+d.msg,'text-red-400');setStage(4,'stage-err');}catch(_){ } endResynth();});
  resynthES.addEventListener('end',e=>{endResynth();});
  resynthES.onerror=()=>{endResynth();};
}
function endResynth(){if(resynthES){resynthES.close();resynthES=null;}const b=$('btn-resynth');if(b){b.disabled=false;b.textContent='✅ 重新合成成片';}refreshStatus();}
function startDirectResynth(){
  if(!currentPid||resynthES)return;
  const old=$('direct-resynth-status');if(old)old.remove();
  const status=document.createElement('div');status.id='direct-resynth-status';status.className='text-xs text-yellow-300 mt-3';status.textContent='正在重新合成成片…';$('shots-box')?.appendChild(status);
  resynthES=new EventSource(`/api/project/${encodeURIComponent(currentPid)}/resynth`);
  resynthES.addEventListener('stage',e=>{const d=JSON.parse(e.data);if(d.status==='running')log(`【${d.name}】${d.msg||'合成中...'}`,'gold');});
  resynthES.addEventListener('final',e=>{showFinal(JSON.parse(e.data));status.textContent='重新合成完成';setStage(3,'stage-done');});
  resynthES.addEventListener('error',e=>{try{const d=JSON.parse(e.data);status.textContent='合成失败：'+(d.msg||'未知错误');log(status.textContent,'text-red-400');}catch(_){status.textContent='合成连接失败';}endResynth();});
  resynthES.addEventListener('end',()=>{if(resynthES){resynthES.close();resynthES=null;}});
  resynthES.onerror=()=>{};
}

// 手动环节确认：全部参考图生成完成后暂停，展示「全部满意→继续进入分镜」按钮（不满意的单张可点卡片上的[编辑/重生成]）
function showAssetsConfirmBar(d){
  window.studioAssetsConfirmed=false;
  const old=$('assets-confirm-bar');if(old)old.remove();
  const bar=document.createElement('div');
  bar.id='assets-confirm-bar';
  bar.className='glass rounded-2xl p-5 mt-4 text-center';
  bar.innerHTML=`<div class="text-yellow-300 text-sm mb-1">🖼️ 全部参考图已生成（共${(d.assets||[]).length}张）</div>
    <div class="text-gray-400 text-xs mb-3">请逐张检查；不满意的点卡片下方「🔄 编辑/重生成」可改提示词后单独重做。全部满意后点下方按钮进入分镜视频环节。</div>
    <button onclick="confirmAssetsBatch()" id="btn-assets-continue" class="btn-gold px-8 py-2.5 rounded-xl text-sm">✅ 全部满意，继续进入分镜</button>`;
  $('script-box').appendChild(bar);
  if (!loadingProjectView) bar.scrollIntoView({behavior:'smooth',block:'center'});
}
async function confirmAssetsBatch(){
  if(!currentPid||!$('btn-assets-continue'))return;
  const btn=$('btn-assets-continue');btn.disabled=true;btn.textContent='正在进入分镜视频环节...';
  try{
    const r=await(await fetch(`/api/project/${currentPid}/asset/confirm_all`,{method:'POST'})).json();
    if(!r.ok)throw new Error(r.error||r.msg||'确认失败');
    window.studioAssetsConfirmed=true;
    const b=$('assets-confirm-bar');if(b)b.remove();
    log('参考图环节全部确认，进入分镜视频生成','text-green-400');
    if(!es)runPipeline(currentPid);
  }catch(e){alert('确认失败: '+e.message);btn.disabled=false;btn.textContent='✅ 全部满意，继续进入分镜';}
}
function showScriptReviewBar(data){
  $('continue-bar')?.remove();
  const old=$('script-review-bar');if(old)old.remove();
  const bar=document.createElement('div');
  bar.id='script-review-bar';
  bar.className='soft-panel rounded-xl p-4 mt-4 border border-yellow-400/30';
  bar.innerHTML=`<div class="flex flex-wrap items-center gap-3">
    <div><div class="font-bold text-sm text-yellow-200">剧本已生成，请先查阅</div><div class="text-xs text-gray-500 mt-1">确认后才会生成参考图和视频；需要调整时返回导演台重新生成。</div></div>
    <div class="flex-1"></div>
    <button id="script-regenerate-btn" onclick="regenerateScriptFromDirector()" class="text-xs px-4 py-2 rounded-lg glass hover:bg-yellow-400/20">调整导演台并重生成</button>
    <button id="script-confirm-btn" onclick="confirmScriptAndContinue()" class="btn-gold px-5 py-2 rounded-lg text-xs">确认剧本，继续制作</button>
  </div>`;
  $('script-box').appendChild(bar);
  if (!loadingProjectView) bar.scrollIntoView({behavior:'smooth',block:'center'});
}
async function confirmScriptAndContinue(){
  if(!currentPid)return;
  const button=$('script-confirm-btn');if(button){button.disabled=true;button.textContent='确认中…';}
  try{
    const r=await(await fetch(`/api/project/${encodeURIComponent(currentPid)}/script/confirm`,{method:'POST',headers:{'Content-Type':'application/json'}})).json();
    if(!r.ok)throw new Error(r.msg||'确认失败');
    $('script-review-bar')?.remove();log(r.msg||'剧本已确认，继续生成资产','text-green-400');
    if(!es)runPipeline(currentPid);
  }catch(e){alert('确认剧本失败：'+e.message);if(button){button.disabled=false;button.textContent='确认剧本，继续制作';}}
}
async function regenerateScriptFromDirector(){
  if(!currentPid){alert('当前没有待确认的剧本项目');return;}
  if(directorConfirmedSignature!==directorSignature()){alert('导演台内容已变化，请先点击“确认导演方案”');return;}
  const button=$('script-regenerate-btn')||$('remake-script-start');if(button){button.disabled=true;button.textContent='准备中…';}
  const newIdea=buildDirectorIdea($('idea').value.trim());
  saveDraft();
  try{
    const r=await(await fetch(`/api/project/${encodeURIComponent(currentPid)}/script/regenerate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea:newIdea})})).json();
    if(!r.ok)throw new Error(r.msg||'无法重新生成');
    $('script-review-bar')?.remove();
    $('script-box').classList.add('hidden');$('shots-box').classList.add('hidden');
    $('continue-bar')?.remove();
    log('已按新的导演台方案重新生成剧本','gold');
    window._pendingScriptIdea=newIdea;
    // 让当前 SSE 自然收到重生成事件并结束，再由 end 处理器开启下一次生成。
    if(es)log('正在切换到新的剧本生成任务…','text-yellow-300');
    else runPipeline(currentPid,newIdea);
  }catch(e){alert('重新生成剧本失败：'+e.message);if(button){button.disabled=false;button.textContent='调整导演台并重生成';}}
}
// 手动环节确认：全部分镜视频自动生成完成后暂停，展示「全部满意→继续合成」按钮（不满意的镜头点卡片[✏️ 编辑]改提示词重新渲染）
function showShotsConfirmBar(d){
  const old=$('shots-confirm-bar');if(old)old.remove();
  const bar=document.createElement('div');
  bar.id='shots-confirm-bar';
  bar.className='glass rounded-2xl p-5 mt-4 text-center';
  bar.innerHTML=`<div class="text-yellow-300 text-sm mb-1">🎥 全部分镜视频已生成（共${(d.shots||[]).length}镜）</div>
    <div class="text-gray-400 text-xs mb-3">请逐镜观看检查；不满意的点镜头卡片「✏️ 编辑」改提示词后可「🔄 重新渲染」单独重做。全部满意后点下方按钮合成成片。</div>
    <button onclick="confirmShotsBatch()" id="btn-shots-continue" class="btn-gold px-8 py-2.5 rounded-xl text-sm">✅ 全部满意，继续合成</button>`;
  $('shots-box').appendChild(bar);
  // 项目详情加载时先创建确认条、后恢复 SHOT_DATA；此时按钮不能被
  // 外层步骤刷新逻辑误判为不可用。
  const scripted = SCRIPT_DATA?.shots || [];
  const rendered = scripted.length > 0 && scripted.every(s => {
    const shot = SHOT_DATA[s.index] || (d.shots || []).find(x => x.index === s.index);
    return shot?.video_url && !shot?.error;
  });
  const button = $('btn-shots-continue');
  if (button && rendered) button.disabled = false;
  if (!loadingProjectView) bar.scrollIntoView({behavior:'smooth',block:'center'});
}
async function confirmShotsBatch(){
  if(!currentPid||!$('btn-shots-continue'))return;
  const btn=$('btn-shots-continue');btn.disabled=true;btn.textContent='正在合成成片...';
  try{
    const r=await(await fetch(`/api/project/${currentPid}/shot/confirm_all`,{method:'POST'})).json();
    if(!r.ok)throw new Error(r.error||r.msg||'确认失败');
    const b=$('shots-confirm-bar');if(b)b.remove();
    log('分镜环节全部确认，进入视频合成','text-green-400');
    // Close the waiting SSE before continuing; a stale `es` reference
    // otherwise prevents runPipeline from starting the synthesis run.
    if(es){es.close();es=null;}
    runPipeline(currentPid);
  }catch(e){alert('确认失败: '+e.message);btn.disabled=false;btn.textContent='✅ 全部满意，继续合成';}
}

async function insertBridgeShot(idx,button){
  const ordered=SCRIPT_DATA?.shots||[];
  const position=ordered.findIndex(s=>s.index===idx);
  if(position<0){alert('找不到这个镜头');return;}
  if(position>0&&!SHOT_DATA[ordered[position-1].index]?.video_url){alert('请先生成上一镜视频');return;}
  const description=prompt('描述两段视频接不上的地方，以及希望补充的动作或转场：\n例如：上一镜人物还坐着，下一镜已在门口，需要补起身走向门口。');
  if(!description?.trim())return;
  const pid=currentPid;
  button.disabled=true;
  try{
    const result=await(await fetch(`/api/project/${pid}/shot/${idx}/bridge`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description,duration:8})})).json();
    if(!result.ok)throw new Error(result.msg||'插入失败');
    if(currentPid!==pid)return;
    await openProject(pid);
    $('shot-'+result.index)?.scrollIntoView({behavior:'smooth',block:'center'});
    log(`已插入第${result.index}镜，可继续生成该镜视频，完成后重新合成。`,'text-green-400');
  }catch(error){alert(error.message);}finally{button.disabled=false;}
}
function generateBridgeShot(idx,button){
  const pid=currentPid;
  button.disabled=true;button.textContent='正在生成视频…';
  // 统一走项目分镜渲染流程；后端会按当前项目补齐提示词、参考图和连续性依赖。
  const stream=new EventSource(`/api/project/${pid}/shots/render_selected_stream?indexes=${encodeURIComponent(idx)}&_stream=${Date.now()}`);
  stream.addEventListener('shot_status',e=>{if(currentPid===pid)log(JSON.parse(e.data).msg);});
  stream.addEventListener('shot_render_progress',e=>{if(currentPid===pid)updateShotRenderProgress(JSON.parse(e.data));});
  stream.addEventListener('shot',e=>{if(currentPid===pid){const d=JSON.parse(e.data);SHOT_DATA[d.index]=d;addShotCard(d);}});
  stream.addEventListener('shot_error',e=>{const d=JSON.parse(e.data);if(currentPid===pid)log(d.msg||'视频生成失败','text-red-400');});
  const finish=()=>{stream.close();button.disabled=false;button.textContent='生成视频';};
  stream.addEventListener('end',()=>{finish();if(currentPid===pid)openProject(pid);});
  stream.addEventListener('error',e=>{finish();if(currentPid===pid){let msg='生成连接中断，请刷新项目查看结果';try{if(e.data)msg=JSON.parse(e.data).msg||msg;}catch(_){}log(msg,'text-red-400');}});
}
function showAudioReview(idx, report){
  if(!report)return;
  const card=$('shot-'+idx);if(!card)return;
  let box=$('audio-review-'+idx);
  if(!box){box=document.createElement('details');box.id='audio-review-'+idx;box.className='mt-2 text-xs rounded-lg p-2 bg-black/30';card.appendChild(box);}
  const label={passed:'通过',needs_review:'待复核',incomplete:'检查未完成',disabled:'未启用'}[report.status]||'未知';
  const details=[];
  if(report.dialogue){details.push('剧本台词：'+report.dialogue.expected,'实际转写：'+report.dialogue.actual);}
  if(report.speakers_match===false)details.push('模型判断的说话人数与剧本不一致，需人工复核。');
  for(const segment of report.segments||[]){
    const a=segment.analysis||{},m=a.ffmpeg||{};
    details.push(`片段 ${segment.offset}s：峰值 ${m.true_peak_dbfs??'未知'} dBFS；响度 ${m.integrated_loudness_lufs??'未知'} LUFS；清晰度 ${a.speech?.clarity_score??'未知'}`);
    if(m.clipping_risk)details.push('峰值风险：超过服务阈值，需复核音量。');
  }
  details.push(...(report.problems||[]).map(p=>p.description||p.type),...(report.errors||[]));
  details.push('转写与听音模型可能误判；此报告不代表说话人身份或口型已验证。');
  box.innerHTML=`<summary class="${report.passed?'text-green-300':'text-yellow-300'}">听音质检：${label} · 点击查看</summary><pre class="whitespace-pre-wrap mt-2 text-gray-300">${escapeHtml(details.join('\n'))}</pre>`;
}
function addShotCard(d){
  // 提示词草稿没有视频，必须保留 video-slot 供批量编辑器使用。
  if(!d.video_url){
    const raw=d.local_path||d.path||'';
    const m=String(raw).replaceAll('\\\\','/').match(/(?:^|\/)outputs\/([^/]+)\/(shot_[^/]+\.(?:mp4|webm))$/i);
    if(m)d.video_url=`/file/outputs/${encodeURIComponent(m[1])}/${encodeURIComponent(m[2])}`;
  }
  if(!d.video_url)return;
  const card=$('shot-'+d.index);
  if(!card)return;
  if(d.reference_video_stale&&!card.querySelector('.reference-stale')){const label=document.createElement('div');label.className='reference-stale text-xs text-yellow-300 mb-2';label.textContent='参考图已同步，视频待重新生成';card.prepend(label);}
  if(!d.reference_video_stale)card.querySelector('.reference-stale')?.remove();
  const existing=card.querySelector('video');
  if(existing){existing.src=d.video_url;enableVideoAudio(existing);existing.load();return;}
  const slot=card.querySelector('.video-slot');
  if(slot){slot.outerHTML=`<div class="shot-video-wrap"><video src="${d.video_url}" controls playsinline preload="metadata" class="w-full rounded-lg card-in"></video>
    <div class="flex flex-wrap gap-2 mt-2 items-center">
      <label class="shot-action-btn rounded glass cursor-pointer select-none" title="选择重制" aria-label="选择重制" onclick="toggleRenderedShotSelection(event,this)"><input type="checkbox" class="shot-rerender-check accent-yellow-500" data-shot-index="${d.index}" onchange="syncRenderedShotSelection(this)"></label>
      <button onclick="remakeShot(${d.index})" class="shot-action-btn rounded glass hover:bg-yellow-400/20 transition text-gray-300" title="使用当前提示词和参考图重新生成" aria-label="使用当前提示词和参考图重新生成">🔄</button>
      <button onclick="openShotEdit(${d.index},SHOT_DATA[${d.index}]&&SHOT_DATA[${d.index}].video_url,SHOT_DATA[${d.index}]&&SHOT_DATA[${d.index}].prompt)" class="shot-action-btn rounded glass hover:bg-yellow-400/20 transition text-gray-300" title="编辑/重渲染" aria-label="编辑/重渲染">✏️</button>
      <button onclick="restorePreviousShotVersion(${d.index})" class="shot-action-btn rounded glass hover:bg-yellow-400/20 transition" title="取上一版" aria-label="取上一版">↩️</button>
      <button onclick="toggleShotVersions(${d.index})" class="shot-action-btn rounded glass hover:bg-white/10 transition" title="历史版本" aria-label="历史版本">🕘</button>
      ${window.bridgeSupported&&(SCRIPT_DATA?.shots||[]).some(s=>s.index===d.index)?`<button onclick="insertBridgeShot(${d.index},this)" class="shot-action-btn rounded glass text-cyan-300 hover:bg-white/10" title="在本镜头前补充衔接镜头" aria-label="在本镜头前补充衔接镜头">↪️</button>`:''}
    </div>
    <div id="shot-version-panel-${d.index}" class="hidden mt-2 rounded-lg bg-black/30 border border-white/10 p-2"></div>
    <div id="review-${d.index}" class="hidden mt-2 text-xs rounded-lg px-2 py-1.5 bg-black/30"></div></div>`;
    const preview=card.querySelector('.shot-video-wrap video');
    if(preview)prepareShotVideoPreview(preview);}
  updateRenderedSelectionCount();
  updatePromptBatchSelectionInfo();
}
function prepareShotVideoPreview(video){
  if(!video||video.dataset.previewReady)return;
  video.dataset.previewReady='1';
  const capture=()=>{
    if(!video.videoWidth||!video.videoHeight)return;
    try{
      const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;
      canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
      video.poster=canvas.toDataURL('image/jpeg',.82);
      video.currentTime=0;
    }catch(_){/* 浏览器禁止读取媒体帧时仍保留视频本身 */}
  };
  video.addEventListener('loadeddata',capture,{once:true});
  video.addEventListener('error',()=>{video.removeAttribute('poster');},{once:true});
}
function updateRenderedSelectionCount(){
  const count=Array.from(document.querySelectorAll('.shot-rerender-check')).filter(box=>box.checked).length;
  if($('rerender-selected-count'))$('rerender-selected-count').textContent=`已选重制 ${count} 镜`;
}
function syncRenderedShotSelection(input){
  if(!input)return;
  input.closest('label')?.setAttribute('data-selected',input.checked?'true':'false');
  updateRenderedSelectionCount();
  updatePromptBatchSelectionInfo();
}
function toggleRenderedShotSelection(event,label){
  if(event?.target?.matches('input'))return;
  event?.preventDefault();
  const input=label?.querySelector('.shot-rerender-check');
  if(!input)return;
  input.checked=!input.checked;
  syncRenderedShotSelection(input);
}
function selectRenderedShots(flag){
  document.querySelectorAll('.shot-rerender-check').forEach(box=>{
    box.checked=!!flag;
    syncRenderedShotSelection(box);
  });
}
function selectedRenderedShotIndexes(){
  return Array.from(document.querySelectorAll('.shot-rerender-check'))
    .filter(box=>box.checked||box.closest('label')?.dataset.selected==='true')
    .map(box=>parseInt(box.dataset.shotIndex))
    .filter(Number.isFinite)
    .sort((a,b)=>a-b);
}
async function toggleShotVersions(idx){
  const panel=$('shot-version-panel-'+idx);if(!panel)return;
  if(!panel.classList.contains('hidden')){panel.classList.add('hidden');return;}
  panel.classList.remove('hidden');panel.innerHTML='<div class="text-xs text-gray-500 py-2">正在读取历史版本…</div>';
  try{
    const result=await(await fetch(`/api/project/${currentPid}/shot/${idx}/versions`)).json();
    if(!result.ok){panel.innerHTML=`<div class="text-xs text-red-300">${escapeHtml(result.msg||'读取失败')}</div>`;return;}
    const versions=result.versions||[];
    if(!versions.length){panel.innerHTML='<div class="text-xs text-gray-500">这个镜头暂时没有可用版本。</div>';return;}
    panel.dataset.currentUrl=SHOT_DATA[idx]?.video_url||$('shot-'+idx)?.querySelector('video')?.src||'';
    const options=versions.map((version,position)=>{const date=version.created?new Date(version.created*1000).toLocaleString():'';const current=version.id===result.current_version_id?'（当前）':'';return `<option value="${escapeHtml(version.id)}" data-url="${escapeHtml(version.url||'')}">版本 ${versions.length-position} ${current} · ${escapeHtml(version.label||'生成版本')} · ${escapeHtml(date)}</option>`;}).join('');
    panel.innerHTML=`<div class="text-xs gold mb-2">🕘 镜头${idx} 历史生成版本</div>
      <select id="shot-version-select-${idx}" class="w-full bg-black/40 border border-white/10 rounded-lg px-2 py-2 text-xs">${options}</select>
      <div class="flex gap-2 mt-2">
        <button onclick="previewShotVersion(${idx})" class="flex-1 text-xs px-2 py-1.5 rounded glass hover:bg-white/10 transition">▶ 预览</button>
        <button onclick="restoreShotCurrentPreview(${idx})" class="text-xs px-2 py-1.5 rounded glass hover:bg-white/10 transition">↩ 当前版本</button>
        <button onclick="selectShotVersion(${idx})" class="btn-gold flex-1 text-xs px-2 py-1.5 rounded">✅ 设为当前片段</button>
      </div>
      <div class="text-[11px] text-gray-500 mt-2">预览不会改变最终合成；设为当前片段后，合成和后续重制会使用该版本。</div>`;
  }catch(error){panel.innerHTML=`<div class="text-xs text-red-300">读取历史版本失败：${escapeHtml(error.message)}</div>`;}
}
function previewShotVersion(idx){const selected=$('shot-version-select-'+idx)?.selectedOptions?.[0];const video=$('shot-'+idx)?.querySelector('video');if(video&&selected?.dataset?.url){video.src=selected.dataset.url;video.load();}}
function restoreShotCurrentPreview(idx){const panel=$('shot-version-panel-'+idx);const url=SHOT_DATA[idx]?.video_url||panel?.dataset?.currentUrl||'';const video=$('shot-'+idx)?.querySelector('video');if(video&&url){video.src=url;video.load();}}
async function restorePreviousShotVersion(idx){
  try{
    const result=await(await fetch(`/api/project/${currentPid}/shot/${idx}/versions`,{cache:'no-store'})).json();
    const versions=result.versions||[];
    const previous=versions.find(version=>version.id!==result.current_version_id);
    if(!previous){log(`镜头${idx}没有可恢复的上一版`,'text-gray-400');return;}
    if(!confirm(`确定将镜头${idx}恢复为上一版？\n${previous.label||'历史版本'} · ${previous.created?new Date(previous.created*1000).toLocaleString():''}`))return;
    const selected=await(await fetch(`/api/project/${currentPid}/shot/${idx}/select_version`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version_id:previous.id})
    })).json();
    if(!selected.ok){alert(selected.msg||'恢复上一版失败');return;}
    SHOT_DATA[idx]={...(SHOT_DATA[idx]||{}),...selected.shot};
    const video=$('shot-'+idx)?.querySelector('video');
    if(video){video.src=selected.shot.video_url;video.load();}
    log(`镜头${idx}已恢复上一版，后续合成将使用该版本`,'gold');
  }catch(error){alert('读取或恢复上一版失败: '+error.message);}
}
async function selectShotVersion(idx){
  const versionId=$('shot-version-select-'+idx)?.value;if(!versionId)return;
  try{
    const result=await(await fetch(`/api/project/${currentPid}/shot/${idx}/select_version`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version_id:versionId})})).json();
    if(!result.ok){alert(result.msg||'切换版本失败');return;}
    SHOT_DATA[idx]={...(SHOT_DATA[idx]||{}),...result.shot};
    const video=$('shot-'+idx)?.querySelector('video');if(video){video.src=result.shot.video_url;video.load();}
    $('shot-version-panel-'+idx)?.classList.add('hidden');
    log(`镜头${idx}已切换到历史版本，后续重制与最终合成都将使用该版本`,'gold');
  }catch(error){alert('切换历史版本失败: '+error.message);}
}
function batchRerenderSelectedShots(){
  if(!currentPid)return;
  const indexes=selectedRenderedShotIndexes();
  if(!indexes.length){alert('请先勾选要重制的片段');return;}
  if(!confirm(`确定批量重制镜头 ${indexes.join('、')}？\n\n旧版本会自动保留在每个镜头的「历史版本」里。`))return;
  const button=$('btn-batch-rerender-current');if(button){button.disabled=true;button.textContent='🔄 批量重制中…';}
  const stream=new EventSource(`/api/project/${currentPid}/shots/render_selected_stream?indexes=${encodeURIComponent(indexes.join(','))}`);
  stream.addEventListener('stage',event=>{const data=JSON.parse(event.data);if(data.status==='running'){setStage(3,'stage-active');log(`【批量重制】${data.msg||''}`);}else if(data.status==='done'){setStage(3,'stage-done');}});
  stream.addEventListener('shot_status',event=>{const data=JSON.parse(event.data);showShotRenderProgress(data.index,{percent:0,phase:'准备重制',elapsed:0,eta:0});log(data.msg);});
  stream.addEventListener('shot_render_progress',event=>updateShotRenderProgress(JSON.parse(event.data)));
  stream.addEventListener('progress',event=>{const data=JSON.parse(event.data);log(`批量重制进度 ${data.done}/${data.total}`);});
  stream.addEventListener('shot',event=>{const data=JSON.parse(event.data);SHOT_DATA[data.index]=data;addShotCard(data);const box=document.querySelector(`.shot-rerender-check[data-shot-index="${data.index}"]`);if(box){box.checked=false;syncRenderedShotSelection(box);}updateRenderedSelectionCount();log(`镜头${data.index}重制完成，旧版本已保存`,'text-green-400');});
  stream.addEventListener('shot_error',event=>{const data=JSON.parse(event.data);showShotError(data.index,data.msg||'重制失败');});
  const finish=()=>{if(button){button.disabled=false;button.textContent='🔄 批量重制选中';}stream.close();refreshStatus();};
  stream.addEventListener('end',finish);stream.addEventListener('error',event=>{try{const data=JSON.parse(event.data);log('❌ '+data.msg,'text-red-400');}catch(_){}finish();});stream.onerror=()=>{};
}
function composeAllCurrentShots(){
  if(!currentPid)return;
  if(!confirm('确定按镜头顺序合成全部“当前片段”吗？\n\n如果某镜头切换过历史版本，将使用你目前设为当前的版本。'))return;
  const button=$('btn-compose-all-current');if(button){button.disabled=true;button.textContent='🎬 合成中…';}
  const stream=new EventSource(`/api/project/${currentPid}/resynth`);
  stream.addEventListener('stage',event=>{const data=JSON.parse(event.data);if(data.status==='running'){setStage(4,'stage-active');log(`【${data.name}】${data.msg||'合成中...'}`);}else if(data.status==='done'){setStage(4,'stage-done');log('全部当前片段合成完成','text-green-400');}});
  stream.addEventListener('final',event=>showFinal(JSON.parse(event.data)));
  const finish=()=>{if(button){button.disabled=false;button.textContent='🎬 合成全部当前片段';}stream.close();refreshStatus();};
  stream.addEventListener('end',finish);stream.addEventListener('error',event=>{try{const data=JSON.parse(event.data);log('❌ '+data.msg,'text-red-400');setStage(4,'stage-err');}catch(_){}finish();});stream.onerror=()=>{};
}
function applyShotReview(idx,r){
  const el=$('review-'+idx);if(!el)return;
  if(r.score==null){el.classList.remove('hidden');el.className='mt-2 text-xs rounded-lg px-2 py-1.5 bg-black/30 text-red-300';el.textContent='审片失败：'+(r.error||'未知错误');return;}
  const problems=(r.problems||[]).slice(0,2).join('；');
  el.classList.remove('hidden');el.className='mt-2 text-xs rounded-lg px-2 py-1.5 bg-black/30 '+(r.score>=80?'text-green-300':(r.score>=65?'text-yellow-300':'text-red-300'));
  el.textContent=`AI审片 ${r.score}分`+(problems?` · ${problems}`:'')+(r.attempt?` · 自动重做${r.attempt}次`:'');
}
async function reviewShot(idx){
  if(!currentPid)return;
  const el=$('review-'+idx);if(el){el.classList.remove('hidden');el.textContent='AI审片中…';el.className='mt-2 text-xs rounded-lg px-2 py-1.5 bg-black/30 text-gray-400';}
  try{
    const r=await(await fetch(`/api/project/${currentPid}/shot/${idx}/review`,{method:'POST'})).json();
    if(r.ok){applyShotReview(idx,r.review);log(`镜头${idx}手动审片完成：${r.review.score}分`,'gold');}
    else applyShotReview(idx,{score:null,error:r.msg||'审片失败'});
  }catch(e){applyShotReview(idx,{score:null,error:e.message});}
}
function safeDownloadName(value,fallback='成片'){
  const cleaned=String(value||fallback).replace(/[\\/:*?"<>|\r\n]+/g,'_').replace(/\s+/g,' ').replace(/[ ._]+$/,'').trim();
  return (cleaned||fallback).slice(0,100)+'.mp4';
}
function markFinalNeedsResynth(){
  const status=$('final-version-status');
  status.textContent='这是上次合成的视频；分镜或提示词已修改，需要重新合成。';
  status.classList.remove('hidden');
  if(window._lastFinalData)window._lastFinalData.needs_resynth=true;
}
function showFinal(d){
  if(!d.needs_resynth)$('continue-bar')?.remove();
  window._lastFinalData=d;
  $('final-box').classList.remove('hidden');
  $('final-title').textContent=`《${d.title}》`;
  $('final-video').src=d.video_url;
  enableVideoAudio($('final-video'));
  $('final-dl').href=d.video_url;
  let filename='';
  try{filename=decodeURIComponent(new URL(d.video_url,location.href).pathname.split('/').pop());}catch(_){}
  $('final-dl').download=filename&&filename!=='final.mp4'?filename:safeDownloadName(d.title||'成片');
  $('final-version-status').classList.add('hidden');
  if(d.needs_resynth)markFinalNeedsResynth();
  const subtitleButton=$('final-subtitle-btn');
  if(subtitleButton){subtitleButton.disabled=false;subtitleButton.textContent='📝 一键加字幕';}
  const subtitleStatus=$('final-subtitle-status');
  if(subtitleStatus)subtitleStatus.textContent='按当前对白重新合成并烧录中文字幕';
  log(d.needs_resynth?'已载入上次成片，修改后需重新合成。':'🎉 成片合成完成！','gold');
  if (!loadingProjectView) $('final-box').scrollIntoView({behavior:'smooth'});
}
function burnFinalSubtitles(){
  if(!currentPid)return;
  const button=$('final-subtitle-btn');
  if(button){button.disabled=true;button.textContent='字幕合成中…';}
  const status=$('final-subtitle-status');
  if(status)status.textContent='正在重新合成并烧录字幕，请稍候…';
  if(resynthES)resynthES.close();
  resynthES=new EventSource(`/api/project/${currentPid}/resynth?subtitle=1&only=1`);
  resynthES.addEventListener('stage',e=>{const d=JSON.parse(e.data);if(d.status==='running')log(`【${d.name}】${d.msg||'合成中...'}`);});
  resynthES.addEventListener('final',e=>{showFinal(JSON.parse(e.data));if(status)status.textContent='字幕已烧录，可直接下载带字幕成片';});
  resynthES.addEventListener('error',e=>{try{const d=JSON.parse(e.data);alert(d.msg||'字幕合成失败');}catch(_){alert('字幕合成失败');}endSubtitleBurn();});
  resynthES.addEventListener('end',endSubtitleBurn);
  resynthES.onerror=endSubtitleBurn;
}
function endSubtitleBurn(){
  if(resynthES){resynthES.close();resynthES=null;}
  const button=$('final-subtitle-btn');
  if(button){button.disabled=false;button.textContent='📝 一键加字幕';}
}

// ---------- 设置 ----------
let llmProfiles=[],activeLLMProfileId='',comfyServers=[],llmModelOptions={};
function renderLLMModelOptions(){
  const list=$('cfg-model');if(!list)return;
  const p=llmProfiles.find(p=>p.id===activeLLMProfileId),current=p?.model||'';
  const models=[...(llmModelOptions[activeLLMProfileId]||[])];
  if(current&&!models.includes(current))models.unshift(current);
  list.replaceChildren();
  if(!models.length)list.appendChild(new Option('请先获取模型列表',''));
  [...new Set(models)].forEach(model=>list.appendChild(new Option(model,model)));
  list.value=current||models[0]||'';
  if(p)p.model=list.value;
}
function selectLLMModel(value){
  const p=llmProfiles.find(p=>p.id===activeLLMProfileId);if(p)p.model=value;
}
function stashLLMProfile(){
  const p=llmProfiles.find(p=>p.id===activeLLMProfileId);if(!p)return;
  p.name=$('cfg-profile-name').value.trim();p.base_url=$('cfg-base-url').value.trim();
  p.api_key=$('cfg-api-key').value.trim();p.model=$('cfg-model').value.trim();
}
function renderLLMProfiles(){
  const sel=$('cfg-profile');sel.replaceChildren();
  llmProfiles.forEach(p=>sel.add(new Option(p.name||'未命名 API',p.id)));
  if(!llmProfiles.length)sel.add(new Option('请新增 API 配置',''));
  sel.value=activeLLMProfileId;
  const p=llmProfiles.find(p=>p.id===activeLLMProfileId);
  $('cfg-delete-profile').disabled=!p;
  $('cfg-profile-name').value=p?.name||'';$('cfg-base-url').value=p?.base_url||'';
  $('cfg-api-key').value=p?.api_key||'';renderLLMModelOptions();
}
function renameLLMProfile(){const o=$('cfg-profile').selectedOptions[0];if(o)o.textContent=$('cfg-profile-name').value.trim()||'未命名 API';}
function switchLLMProfile(id){stashLLMProfile();activeLLMProfileId=id;renderLLMProfiles();}
function addLLMProfile(){
  stashLLMProfile();const p={id:newClientId(),name:`API ${llmProfiles.length+1}`,base_url:'',api_key:'',model:''};
  llmProfiles.push(p);activeLLMProfileId=p.id;renderLLMProfiles();$('cfg-profile-name').focus();
}
function deleteLLMProfile(){
  llmProfiles=llmProfiles.filter(p=>p.id!==activeLLMProfileId);activeLLMProfileId=llmProfiles[0]?.id||'';renderLLMProfiles();
}
async function testCurrentLLM(getModels){
  stashLLMProfile();const p=llmProfiles.find(p=>p.id===activeLLMProfileId);const out=$('cfg-llm-test');
  if(!p){out.textContent='请先新增并填写 API 配置';return;}
  out.className='text-xs text-yellow-300';out.textContent='正在连接...';
  try{
    const r=await fetch(getModels?'/api/llm/models':'/api/llm/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
    const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||d.message||'连接失败');
    const models=(d.models||[]).filter(model=>typeof model==='string');llmModelOptions[p.id]=models;
    if(activeLLMProfileId!==p.id||!llmProfiles.includes(p))return;
    p.model=$('cfg-model').value.trim()||models[0]||'';renderLLMModelOptions();
    out.className='text-xs text-green-400';
    out.textContent=models.length?`连接成功，发现 ${models.length} 个模型：${models.slice(0,8).join('、')}`:'连接成功，但服务未返回可用模型，请检查 API 地址或服务的模型配置。';
  }catch(e){out.className='text-xs text-red-400';out.textContent=e.message+'；请检查 API 地址和密钥后重新获取模型列表。';}
}
function toggleJimengBox(){$('cfg-jimeng-box').classList.toggle('hidden',$('cfg-media-provider').value!=='jimeng');$('cfg-runninghub-box').classList.toggle('hidden',$('cfg-media-provider').value!=='runninghub');}
function renderJimengModelSelect(id,models,current){
  const select=$(id);if(!select)return;
  const values=[...new Set([...(models||[]).filter(Boolean),current].filter(Boolean))];
  select.replaceChildren();
  if(!values.length){select.appendChild(new Option('请先获取官方模型列表',''));return;}
  values.forEach(model=>select.appendChild(new Option(model,model)));
  select.value=current&&values.includes(current)?current:values[0];
}
async function readJsonResponse(response){
  const text=await response.text();
  let data;
  try{data=JSON.parse(text);}
  catch(_){throw new Error(`服务端返回了非 JSON 内容（HTTP ${response.status}），请重启当前服务后再试`);}
  if(!response.ok||data.ok===false)throw new Error(data.error||data.msg||data.message||`请求失败（HTTP ${response.status}）`);
  return data;
}
async function fetchJimengModels(showStatus=true){
  const out=$('cfg-jimeng-test');
  if(showStatus){out.className='text-xs text-yellow-300';out.textContent='正在从即梦服务获取当前账号可用模型…';}
  const body={base_url:$('cfg-jimeng-base').value.trim(),api_key:$('cfg-jimeng-key').value.trim()};
  const [ir,vr]=await Promise.all([
    fetch('/api/jimeng/models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,type:'image'})}),
    fetch('/api/jimeng/models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,type:'video'})})
  ]);
  const image=await readJsonResponse(ir),video=await readJsonResponse(vr);
  renderJimengModelSelect('cfg-jimeng-image-model',image.models||[],$('cfg-jimeng-image-model').value);
  renderJimengModelSelect('cfg-jimeng-video-model',video.models||[],$('cfg-jimeng-video-model').value);
  if(showStatus){
    out.className='text-xs text-green-400';
    out.textContent=`已同步官方模型：图片 ${image.models?.length||0} 个，视频 ${video.models?.length||0} 个`;
  }
  return {image,video};
}
async function testJimeng(){
  const out=$('cfg-jimeng-test');out.className='text-xs text-yellow-300';out.textContent='正在连接…';
  try{
    const r=await fetch('/api/jimeng/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_url:$('cfg-jimeng-base').value.trim(),api_key:$('cfg-jimeng-key').value.trim()})});
    await readJsonResponse(r);
    out.className='text-xs text-green-400';out.textContent='连接成功';
  }catch(e){out.className='text-xs text-red-400';out.textContent=e.message;}
}
async function loadJimengModels(){
  try{await fetchJimengModels(true);}
  catch(e){$('cfg-jimeng-test').className='text-xs text-red-400';$('cfg-jimeng-test').textContent=e.message;}
}
async function openSettings(){
  const c=await(await fetch('/api/config')).json();
  llmProfiles=(c.llm_profiles||[]).map(p=>({...p}));
  if(!llmProfiles.length&&c.llm_mode==='custom')llmProfiles.push({id:newClientId(),name:'我的 LLM',base_url:'',api_key:'',model:''});
  activeLLMProfileId=c.active_llm_profile_id||llmProfiles[0]?.id||'';
  renderLLMProfiles();
  $('cfg-llm-mode').value=c.llm_mode;
  $('cfg-local-url').value=c.local_llm_url||'';$('cfg-local-model').value=c.local_llm_model||'';
  $('cfg-media-provider').value=c.media_provider||'comfyui';
  $('cfg-jimeng-base').value=c.jimeng_base_url||'';
  $('cfg-jimeng-key').value=c.jimeng_api_key||'';
  renderJimengModelSelect('cfg-jimeng-image-model',[],c.jimeng_image_model||'jimeng-image-5.0-lite');
  renderJimengModelSelect('cfg-jimeng-video-model',[],c.jimeng_video_model||'jimeng-video-seedance-2.0-mini');
  $('cfg-steps').value=c.h3_steps??8;$('cfg-steps-val').textContent=c.h3_steps??8;
  $('cfg-exclusive').checked=!!c.exclusive_mode;
  $('cfg-story-bible').checked=c.story_bible_enabled!==false;
  $('cfg-auto-review').checked=!!c.auto_review;
  $('cfg-review-threshold').value=c.review_threshold??72;
  $('cfg-review-rerenders').value=String(c.max_auto_rerenders??1);
  toggleCustom();toggleJimengBox();$('settings-modal').classList.replace('hidden','flex');
  if(c.media_provider==='jimeng'&&c.jimeng_base_url&&c.jimeng_api_key){
    fetchJimengModels(false).catch(()=>{});
  }
}
function toggleCustom(){$('cfg-custom-box').classList.toggle('hidden',$('cfg-llm-mode').value!=='custom');$('cfg-local-box').classList.toggle('hidden',$('cfg-llm-mode').value!=='local');}
$('cfg-llm-mode')?.addEventListener('change',toggleCustom);
$('cfg-media-provider')?.addEventListener('change',toggleJimengBox);
function closeSettings(){$('settings-modal').classList.replace('flex','hidden');}
async function saveSettings(){
  try{
    stashLLMProfile();
    const [asp,mp]=$('resolution').value.split('|');
    const profilesToSave=llmProfiles.filter(p=>p.base_url||p.api_key||p.model);
    const active=profilesToSave.find(p=>p.id===activeLLMProfileId)||profilesToSave[0];
    const body={llm_mode:$('cfg-llm-mode').value,local_llm_url:$('cfg-local-url').value.trim(),local_llm_model:$('cfg-local-model').value.trim(),llm_profiles:profilesToSave,active_llm_profile_id:active?.id||'',
      custom_base_url:active?.base_url||'',custom_api_key:active?.api_key||'EMPTY',custom_model:active?.model||'',
      media_provider:$('cfg-media-provider').value,
      jimeng_base_url:$('cfg-jimeng-base').value.trim(),jimeng_api_key:$('cfg-jimeng-key').value.trim(),
      jimeng_image_model:$('cfg-jimeng-image-model').value.trim(),jimeng_video_model:$('cfg-jimeng-video-model').value.trim(),
      aspect_ratio:asp,
      megapixels:parseFloat(mp),h3_steps:parseInt($('cfg-steps').value),exclusive_mode:$('cfg-exclusive').checked,style:getStyleValue()||'电影写实',
      story_bible_enabled:$('cfg-story-bible').checked,auto_review:$('cfg-auto-review').checked,
      review_threshold:Math.max(40,Math.min(95,parseInt($('cfg-review-threshold').value)||72)),max_auto_rerenders:parseInt($('cfg-review-rerenders').value)||0,
      shot_duration:$('shotDuration').value,shot_count:$('shotCount').value,
      subtitle_enabled:$('subtitleEnabled')?.checked||false,video_skill_id:$('prompt-skill-mode')?.value||'auto',script_skill_id:$('script-skill-mode')?.value||'auto'};
    if(window.PLATFORM?.user?.role==='member'){delete body.comfyui_servers;delete body.comfyui_url;}
    $('h3Steps').value=$('cfg-steps').value;  // 设置里的步数同步到主面板
    const response=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok)throw new Error(result.error||result.msg||'设置保存失败，请检查 API 配置是否填写完整');
    closeSettings();refreshStatus();log('设置已保存','text-green-400');
  }catch(e){alert(`设置保存失败：${e.message}`);}
}

// 页面初始化：恢复上次配置到主面板下拉框
function setResolutionUI(aspect,mp){
  const v=`${aspect}|${mp}`;
  const sel=$('resolution');
  if(![...sel.options].some(o=>o.value===v)){
    const o=document.createElement('option');o.value=v;o.textContent=`自定义 ${mp}MP (${aspect==='9:16 (Portrait)'?'竖屏':'横屏'})`;sel.appendChild(o);
  }
  sel.value=v;
}
async function initPanel(){
  try{
    // Fetch both resources immediately; apply configured selections after skills arrive.
    const [c]=await Promise.all([
      fetch('/api/config').then(response=>response.json()).catch(()=>({})),
      loadSkills(),
    ]);
    if(c.style){
      const presets=[...$('style').options].map(o=>o.value||o.text).filter(v=>v!=='__custom__');
      if(presets.includes(c.style)){$('style').value=c.style;$('styleCustom').value='';}
      else{$('style').value='__custom__';$('styleCustom').value=c.style;}
      toggleCustomStyle();
    }
    if(c.shot_duration!==undefined)$('shotDuration').value=String(c.shot_duration);
    if(c.shot_count!==undefined)$('shotCount').value=String(c.shot_count);
    if(c.prompt_skill_mode!==undefined)$('prompt-skill-mode').value=String(c.video_skill_id||c.prompt_skill_mode);
    if($('script-skill-mode'))$('script-skill-mode').value=String(c.script_skill_id||'auto');
    setResolutionUI(c.aspect_ratio||'16:9 (Widescreen)', c.megapixels??0.4);
    $('h3Steps').value=c.h3_steps??8;
    if(c.manual_mode!==undefined)$('manualMode').checked=!!c.manual_mode;
    if(c.subtitle_enabled!==undefined)$('subtitleEnabled').checked=!!c.subtitle_enabled;
    $('promptBatchMode').checked=true;
    renderSkillSelectors(String(c.video_skill_id||c.prompt_skill_mode||'auto'),String(c.script_skill_id||'auto'));
  }catch(e){}
  applyCreationDefaults();
}

// ---------- 剧项目：一部剧一个项目 ----------
function closeDramaProjects(){$('drama-modal').classList.replace('flex','hidden');}
function toggleDramaCreate(force){
  const box=$('drama-create-box');
  const show=force===undefined?box.classList.contains('hidden'):!!force;
  box.classList.toggle('hidden',!show);
  if(show)setTimeout(()=>$('drama-create-name')?.focus(),0);
}
function dramaProjectState(p){
  if((p.final_count||0)>0)return 'finished';
  if((p.episode_count||0)>0||(p.generated_count||0)>0)return 'producing';
  return 'empty';
}
function renderEpisodeVersions(ep){
  const versions=ep.versions||[];
  if(versions.length<2)return '';
  return `<details class="mt-2 text-xs" onclick="event.stopPropagation()"><summary class="cursor-pointer text-gray-400">制作版本（${versions.length}）</summary><div class="flex flex-col gap-2 mt-2">${versions.map((v,index)=>{
    const action=escapeHtml(`openProject(${JSON.stringify(String(v.project_id))})`);
    return `<button type="button" class="text-left text-yellow-300" onclick="${action}">V${index+1} · ${escapeHtml(v.title||'未命名')}${v.is_current?' · 当前版本':''} · ${v.has_final?'已有成片':'制作中'}</button>`;
  }).join('')}</div></details>`;
}
function renderDramaProjectList(){
  const q=($('drama-search')?.value||'').trim().toLowerCase(),filter=$('drama-filter')?.value||'all';
  const list=DRAMA_PROJECT_LIST.filter(p=>{const hit=!q||String(p.name||'').toLowerCase().includes(q)||String(p.premise||'').toLowerCase().includes(q);const state=dramaProjectState(p);return hit&&(filter==='all'||state===filter);});
  const html=list.length?list.map(p=>{
    const episodes=Object.values(p.episodes||{}).sort((a,b)=>(a.episode||0)-(b.episode||0));
    const children=episodes.length?episodes.map(ep=>{
      const status=ep.final_needs_resynth?'旧成片 · 需重新合成':ep.has_final?'成片':ep.has_script?'制作中':'待制作';
      const cls=ep.final_needs_resynth?'text-yellow-300':ep.has_final?'text-green-300':ep.has_script?'text-yellow-300':'text-gray-500';
      const action=ep.project_id?`onclick="event.stopPropagation();openProject('${escapeHtml(ep.project_id)}')"`:'';
      const encodedSeries=encodeURIComponent(String(p.id||''));
      return `<div class="workspace-list-item ml-3" ${action}>
        <div class="workspace-item-heading">
          <div class="workspace-item-title">└ 第${ep.episode}集 · ${escapeHtml(ep.title||'未命名')}</div>
          <button class="workspace-rename-button" onclick="event.stopPropagation();renameSeriesEpisodeFromList('${encodedSeries}',${Number(ep.episode)||1})" title="重命名单集片名" aria-label="重命名单集片名">✎</button>
        </div>
        <div class="workspace-item-meta ${cls}">${status}${ep.failed_shots?` · ${ep.failed_shots} 个镜头待修`: ''}</div>
        ${renderEpisodeVersions(ep)}
      </div>`;
    }).join(''):'<div class="workspace-muted py-2">暂无单集，进入项目后新建</div>';
    const encodedSeries=encodeURIComponent(String(p.id||''));
    return `<div class="workspace-list-item" onclick="openDramaProject(decodeURIComponent('${encodedSeries}'))">
      <div class="workspace-item-heading">
        <div class="workspace-item-title">🎬 ${escapeHtml(p.name||'未命名剧')}${teamOwnerBadge(p)}</div>
        <button class="workspace-rename-button" onclick="event.stopPropagation();renameSeriesFromList('${encodedSeries}')" title="重命名剧名" aria-label="重命名剧名">✎</button>
      </div>
      <div class="workspace-item-meta">${p.episode_count||0} 集 · 成片 ${p.final_count||0} 集<br>${escapeHtml(p.premise||'待填写核心设定')}</div>
    </div>${children}`;
  }).join(''):'<div class="workspace-muted">还没有剧项目</div>';
  if($('drama-list'))$('drama-list').innerHTML=html;
  renderSideDramaProjectList(list);
}
function renderSideDramaProjectList(list){
  const html=list.length?list.map(p=>{
    const episodes=Object.values(p.episodes||{}).sort((a,b)=>(a.episode||0)-(b.episode||0));
    const children=episodes.length?episodes.map(ep=>{
      const state=ep.final_needs_resynth?'is-producing':ep.has_final?'is-final':ep.has_script?'is-producing':'is-pending';
      const action=ep.project_id?`onclick="openProject('${escapeHtml(ep.project_id)}')"`:'';
      const versions=(ep.versions||[]).filter(v=>v.project_id&&String(v.project_id)!==String(ep.project_id));
      const versionHtml=versions.length?`<div class="side-tree-versions">${versions.map(v=>`<div class="side-tree-item side-tree-version" onclick="event.stopPropagation();openProject('${escapeHtml(v.project_id)}')" title="${escapeHtml(v.title||'制作版本')}"><span class="side-tree-dot"></span><span class="side-tree-title">└ ${escapeHtml(v.title||'制作版本')}</span></div>`).join('')}</div>`:'';
      return `<div class="side-tree-item ${state}" ${action} title="${escapeHtml(ep.title||'未命名')}">
        <span class="side-tree-dot"></span><span class="side-tree-title">第${ep.episode}集 · ${escapeHtml(ep.title||'未命名')}</span>
      </div>${versionHtml}`;
    }).join(''):'<div class="side-tree-empty">暂无单集</div>';
    const encodedSeries=encodeURIComponent(String(p.id||''));
    return `<details>
      <summary class="side-tree-summary" onclick="event.stopPropagation();">
        <span class="side-tree-title" onclick="event.preventDefault();openDramaProject(decodeURIComponent('${encodedSeries}'))">🎞️ ${escapeHtml(p.name||'未命名剧')}${teamOwnerBadge(p)}</span>
        <span class="side-tree-count">${p.episode_count||0}集</span>
      </summary>
      <div class="side-tree-children">${children}</div>
    </details>`;
  }).join(''):'<div class="side-tree-empty">还没有剧项目</div>';
  if($('side-drama-list'))$('side-drama-list').innerHTML=html;
}
function toggleDramaCreatePanel(){loadDramaProjects(true).then(()=>toggleDramaCreate(true));}
async function loadDramaProjects(showModal=true){
  try{DRAMA_PROJECT_LIST=await(await fetch('/api/series')).json();}catch(e){alert('读取剧项目失败: '+e.message);return;}
  if($('drama-search'))$('drama-search').value='';if($('drama-filter'))$('drama-filter').value='all';
  toggleDramaCreate(false);renderDramaProjectList();if(showModal)$('drama-modal').classList.replace('hidden','flex');
}
function closeEpisodeManager(){$('episode-manager-modal').classList.replace('flex','hidden');}
async function openEpisodeManager(){
  $('episode-manager-modal').classList.replace('hidden','flex');
  await refreshEpisodeManager();
}
async function refreshEpisodeManager(){
  try{
    const listReady=window.__workspaceListsReady;
    const queuePromise=RENDER_QUEUE.length?Promise.resolve({ok:true,items:RENDER_QUEUE}):fetch('/api/render-queue').then(response=>response.json());
    if(listReady)await listReady;
    else DRAMA_PROJECT_LIST=await(await fetch('/api/series')).json();
    const queueData=await queuePromise;
    if(queueData.ok)RENDER_QUEUE=queueData.items||[];
    const selectedId=MANAGER_CURRENT?.id||DRAMA_PROJECT_LIST[0]?.id;
    MANAGER_CURRENT=null;
    renderEpisodeManagerSeries();
    if(selectedId)await selectManagerSeries(selectedId);
  }catch(e){$('manager-series-list').innerHTML=`<div class="text-xs text-red-300 p-2">${escapeHtml(e.message||'读取失败')}</div>`;}
}
function renderEpisodeManagerSeries(){
  const query=($('manager-series-search')?.value||'').trim().toLowerCase();
  const list=DRAMA_PROJECT_LIST.filter(item=>!query||String(item.name||'').toLowerCase().includes(query)||String(item.premise||'').toLowerCase().includes(query));
  $('manager-series-count').textContent=String(list.length);
  $('manager-series-list').innerHTML=list.length?list.map(item=>{
    const active=MANAGER_CURRENT?.id===item.id;
    return `<button type="button" onclick="selectManagerSeries('${String(item.id).replace(/'/g,"\\'")}')" class="w-full text-left p-3 rounded-lg border ${active?'border-yellow-400/50 bg-yellow-400/10':'border-white/10 bg-black/10 hover:bg-white/5'}">
      <div class="font-bold text-sm truncate">${escapeHtml(item.name||'未命名剧')}${teamOwnerBadge(item)}</div>
      <div class="text-[11px] text-gray-500 mt-1">${item.episode_count||0}集 · 成片 ${item.final_count||0}集</div>
    </button>`;
  }).join(''):'<div class="workspace-muted p-2">暂无剧项目</div>';
}
async function selectManagerSeries(seriesId){
  try{
    // The list response already contains episode summaries and versions. Use
    // it first so opening the manager does not scan every project file again.
    const cached=DRAMA_PROJECT_LIST.find(item=>String(item.id)===String(seriesId));
    let series=cached;
    if(!series){
      const result=await(await fetch(`/api/series/${encodeURIComponent(seriesId)}`)).json();
      if(!result.ok)throw new Error(result.msg||'读取剧项目失败');
      series=result.series;
    }
    if(!series.episode_status)series={...series,episode_status:series.episodes||{},episodes:series.episodes||{}};
    MANAGER_CURRENT=series;MANAGER_SELECTED=new Set();
    $('manager-select-all').checked=false;
    renderEpisodeManagerSeries();renderEpisodeManagerEpisodes();
  }catch(e){alert(e.message);}
}
function managerEpisodeQueueItem(pid){return RENDER_QUEUE.find(item=>String(item.pid)===String(pid));}
function managerEpisodeStatus(ep){
  const queue=managerEpisodeQueueItem(ep.project_id);
  if(queue?.status==='running')return 'running';
  if(queue&&(queue.status==='queued'||queue.status==='retry'||queue.status==='paused'))return 'queued';
  if(queue?.status==='error')return 'error';
  if(ep.final_needs_resynth)return 'stale';
  if(ep.has_final)return 'finished';
  return ep.has_script?'unfinished':'unfinished';
}
function managerStatusLabel(status){
  return {running:'生成中',queued:'队列中',finished:'已有成片',stale:'旧成片 · 需重新合成',unfinished:'未完成',error:'失败'}[status]||status;
}
function openEpisodeVideoPreview(url,title='剧集预览'){
  if(!url)return;
  const modal=$('episode-video-preview-modal'),video=$('episode-video-preview');
  if(!modal||!video)return;
  $('episode-video-preview-title').textContent=title||'剧集预览';
  video.pause();
  video.src=url;
  video.load();
  modal.classList.replace('hidden','flex');
}
function closeEpisodeVideoPreview(event){
  if(event&&event.target&&event.target.id!=='episode-video-preview-modal')return;
  const modal=$('episode-video-preview-modal'),video=$('episode-video-preview');
  if(video){video.pause();video.removeAttribute('src');video.load();}
  modal?.classList.replace('flex','hidden');
}
function episodePreviewOnclick(url,title){
  return `openEpisodeVideoPreview(${JSON.stringify(String(url||''))},${JSON.stringify(String(title||'剧集预览'))})`;
}
function toggleManagerEpisodePreview(button,url,title){
  const row=button?.closest('.manager-episode-row');
  const preview=row?.querySelector('.manager-episode-inline-preview');
  const video=preview?.querySelector('video');
  if(!preview||!video)return;
  const opening=preview.classList.contains('hidden');
  document.querySelectorAll('.manager-episode-inline-preview').forEach(item=>{
    if(item!==preview){
      item.classList.add('hidden');
      const other=item.querySelector('video');
      if(other){other.pause();other.removeAttribute('src');other.load();}
    }
  });
  if(opening){
    video.src=url;
    video.load();
    preview.classList.remove('hidden');
    button.textContent='■ 收起';
    button.classList.add('text-yellow-200');
  }else{
    video.pause();
    video.removeAttribute('src');
    video.load();
    preview.classList.add('hidden');
    button.textContent='▶ 预览';
    button.classList.remove('text-yellow-200');
  }
}
function toggleManagerPreviewMode(){
  MANAGER_PREVIEW_MODE=MANAGER_PREVIEW_MODE==='compact'?'inline':'compact';
  const button=$('manager-preview-mode-toggle');
  if(button){
    button.textContent=MANAGER_PREVIEW_MODE==='compact'?'▣ 内嵌预览':'▤ 列表模式';
    button.title=MANAGER_PREVIEW_MODE==='compact'?'切换到条目内嵌播放器':'切换回紧凑列表';
  }
  renderEpisodeManagerEpisodes();
}
function renderEpisodeManagerEpisodes(){
  const listEl=$('manager-episode-list');
  if(!MANAGER_CURRENT){listEl.innerHTML='<div class="workspace-muted py-10 text-center">请选择一部剧</div>';return;}
  const query=($('manager-episode-search')?.value||'').trim().toLowerCase();
  const filter=$('manager-episode-filter')?.value||'all';
  const episodes=Object.values(MANAGER_CURRENT.episode_status||{}).sort((a,b)=>(a.episode||0)-(b.episode||0)).filter(ep=>{
    const status=managerEpisodeStatus(ep);
    const hit=!query||String(ep.episode).includes(query)||String(ep.title||'').toLowerCase().includes(query);
    return hit&&(filter==='all'||filter===status);
  });
  $('manager-series-title').textContent=MANAGER_CURRENT.name||'未命名剧';
  $('manager-series-summary').textContent=`${MANAGER_CURRENT.owner_name?'所属：'+MANAGER_CURRENT.owner_name+' · ':''}共 ${Object.keys(MANAGER_CURRENT.episode_status||{}).length} 集 · 已完成 ${Object.values(MANAGER_CURRENT.episode_status||{}).filter(ep=>ep.has_final).length} 集`;
  listEl.innerHTML=episodes.length?episodes.map(ep=>{
    const status=managerEpisodeStatus(ep),queue=managerEpisodeQueueItem(ep.project_id),checked=MANAGER_SELECTED.has(ep.project_id);
    const tone={running:'text-yellow-300',queued:'text-cyan-300',finished:'text-green-300',stale:'text-yellow-300',error:'text-red-300',unfinished:'text-gray-400'}[status]||'text-gray-400';
    const canQueue=!!ep.project_id;
    const previewHandler=ep.final?escapeHtml(episodePreviewOnclick(ep.final,`第${ep.episode}集 · ${ep.title||'未命名'}`)):'';
    const previewAction=ep.final?(MANAGER_PREVIEW_MODE==='compact'
      ?`<button onclick="${previewHandler};event.stopPropagation();" class="text-xs text-green-300 hover:text-green-100">▶ 预览</button>`
      :''):'';
    const inlinePreview=ep.final&&MANAGER_PREVIEW_MODE==='inline'
      ?`<div class="manager-episode-inline-preview mt-3 rounded-lg overflow-hidden border border-white/10 bg-black"><video src="${escapeHtml(ep.final)}" controls playsinline preload="metadata" class="w-full aspect-video max-h-[420px] object-contain"></video></div>`
      :'';
    return `<div class="manager-episode-row rounded-xl border border-white/10 bg-black/15 p-3">
      <div class="grid grid-cols-[auto_56px_minmax(0,1fr)_120px_auto] gap-3 items-center">
      <input type="checkbox" class="manager-episode-check accent-yellow-500" data-pid="${escapeHtml(ep.project_id||'')}" ${checked?'checked':''} ${canQueue?'':'disabled'} onchange="toggleManagerEpisode('${String(ep.project_id||'').replace(/'/g,"\\'")}',this.checked)">
      <div class="tag text-center">第${ep.episode}集</div>
      <div class="min-w-0"><div class="font-bold text-sm truncate">${escapeHtml(ep.title||'未命名')}</div><div class="text-[11px] text-gray-500 truncate">${escapeHtml((MANAGER_CURRENT.episodes||{})[String(ep.episode)]?.synopsis||'')}</div></div>
      <div class="text-xs ${tone}">${managerStatusLabel(status)}${queue?.progress?` · ${queue.progress}%`:''}</div>
      <div class="flex items-center gap-2 justify-end">${ep.project_id?`<button onclick="openProject('${String(ep.project_id).replace(/'/g,"\\'")}');closeEpisodeManager()" class="text-xs text-yellow-300 hover:text-yellow-100">打开</button>`:''}${previewAction}${ep.final?`<a href="${escapeHtml(ep.final)}" target="_blank" class="text-xs text-gray-400 hover:text-gray-200">成片</a>`:''}</div>
      </div>
      ${renderEpisodeVersions(ep)}
      ${inlinePreview}
    </div>`;
  }).join(''):'<div class="workspace-muted py-10 text-center">没有符合条件的集数</div>';
  $('manager-selected-count').textContent=`已选 ${MANAGER_SELECTED.size} 集`;
}
function toggleManagerEpisode(pid,checked){
  if(!pid)return;
  if(checked)MANAGER_SELECTED.add(pid);else MANAGER_SELECTED.delete(pid);
  $('manager-selected-count').textContent=`已选 ${MANAGER_SELECTED.size} 集`;
}
function toggleManagerSelectAll(checked){
  document.querySelectorAll('.manager-episode-check:not(:disabled)').forEach(box=>{
    box.checked=checked;
    const pid=box.dataset.pid;
    if(checked)MANAGER_SELECTED.add(pid);else MANAGER_SELECTED.delete(pid);
  });
  $('manager-selected-count').textContent=`已选 ${MANAGER_SELECTED.size} 集`;
}
async function mergeSelectedManagerEpisodes(){
  const ids=[...MANAGER_SELECTED],seriesId=MANAGER_CURRENT?.id;
  if(!seriesId||!ids.length){alert('请先勾选要合并下载的剧集');return;}
  const button=$('manager-merge-download');
  button.disabled=true;button.textContent='准备合并…';
  try{
    const response=await fetch(`/api/series/${encodeURIComponent(seriesId)}/merge-download`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_ids:ids})});
    const result=await response.json();
    if(response.status===404&&typeof result.error==='string'&&result.error.startsWith('接口不存在:'))throw new Error('当前服务尚未加载合并功能，需要重载服务后才能使用。');
    if(!response.ok||!result.ok)throw new Error(result.msg||result.error||'无法创建合并任务');
    for(;;){
      const poll=await fetch(`/api/episode-exports/${result.job_id}`);
      const job=await poll.json();
      if(!poll.ok||!job.ok||job.status==='error')throw new Error(job.msg||'合并失败');
      button.textContent=`${job.msg||'合并中'} ${job.progress}%`;
      if(job.status==='done'){
        const link=document.createElement('a');
        link.href=`/api/episode-exports/${result.job_id}/download`;
        link.download='';document.body.appendChild(link);link.click();link.remove();
        break;
      }
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  }catch(error){alert(error.message||'合并下载失败');}
  finally{button.disabled=false;button.textContent='⬇️ 合并下载';}
}
async function queueSelectedManagerEpisodes(){
  const ids=Object.values(MANAGER_CURRENT?.episode_status||{}).filter(ep=>MANAGER_SELECTED.has(ep.project_id)&&!ep.has_final).map(ep=>ep.project_id);
  if(!ids.length){alert('请先选择尚未完成的集数进行排队');return;}
  await addProjectsToRenderQueue(ids);
  await refreshEpisodeManager();
}
async function createDramaProject(){
  const name=$('drama-create-name').value.trim(),premise=$('drama-create-premise').value.trim();
  if(!name){alert('先填写剧名');return;}
  const btn=$('drama-create-btn');btn.disabled=true;btn.textContent='创建中…';
  try{
    const r=await(await fetch('/api/series/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,premise})})).json();
    if(!r.ok){if(r.series){closeDramaProjects();await openDramaProject(r.series.id);}else alert(r.msg||'创建失败');return;}
    $('drama-create-name').value='';$('drama-create-premise').value='';closeDramaProjects();await openDramaProject(r.series.id);
  }catch(e){alert('创建失败: '+e.message);}finally{btn.disabled=false;btn.textContent='创建并进入项目';}
}
async function openDramaProject(seriesId){
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(seriesId)}`)).json();
    if(!r.ok){alert(r.msg||'剧项目不存在');return;}
    SERIES_CURRENT=r.series;
    renderManualSeriesProject(SERIES_CURRENT);
    closeDramaProjects();$('series-modal').classList.replace('hidden','flex');
  }catch(e){alert('打开剧项目失败: '+e.message);}
}
async function deleteDramaProject(seriesId,name){
  const ok=confirm(`确定删除剧项目《${name||'未命名剧'}》？\n\n这会同时删除该剧已关联的单集项目与输出视频，无法恢复。`);
  if(!ok)return;
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(seriesId)}/delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_children:true})})).json();
    if(!r.ok){alert(r.msg||'删除失败');return;}
    DRAMA_PROJECT_LIST=DRAMA_PROJECT_LIST.filter(x=>x.id!==seriesId);renderDramaProjectList();log(`剧项目《${name}》已删除`,'text-gray-400');
  }catch(e){alert('删除失败: '+e.message);}
}
async function openEpisodeProject(pid){
  if(!pid)return;closeSeriesFactory();await openProject(pid);
}

// ---------- 历史项目 ----------
let REMAKE_TARGET={scope:'project',id:'',name:''};
function openCurrentProjectRemake(mode){
  if(!currentPid)return;
  if(es){alert('当前制作仍在运行，请先点击“终止制作”，再返回重做。');return;}
  openRemakeModal('project',currentPid,SCRIPT_DATA?.title||$('proj-title').textContent||'当前项目');
  $('remake-mode').value=mode;
}
function openRemakeModal(scope,id,name=''){
  if(!id){alert('没有可重做的项目');return;}
  REMAKE_TARGET={scope,id:String(id),name:String(name||'')};
  $('remake-target-label').textContent=`${scope==='series'?'整部剧':'短片/单集'}：${REMAKE_TARGET.name||REMAKE_TARGET.id}；原项目会保留，新版本会继承当前配置。`;
  $('remake-mode').value='full';
  $('remake-status').textContent='';
  $('remake-confirm-btn').disabled=false;
  $('remake-modal').classList.replace('hidden','flex');
}
function closeRemakeModal(){$('remake-modal').classList.replace('flex','hidden');}
async function confirmRemake(){
  const button=$('remake-confirm-btn'),mode=$('remake-mode').value;
  if(!REMAKE_TARGET.id)return;
  button.disabled=true;button.textContent='创建中…';$('remake-status').textContent='正在复制项目结构…';
  const endpoint=REMAKE_TARGET.scope==='series'
    ?`/api/series/${encodeURIComponent(REMAKE_TARGET.id)}/remake`
    :`/api/project/${encodeURIComponent(decodeURIComponent(REMAKE_TARGET.id))}/remake`;
  try{
    const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok)throw new Error(result.msg||'创建重做版本失败');
    closeRemakeModal();
    if(REMAKE_TARGET.scope==='series'){
      const created=result.series;
      log(`已创建剧集重做版本《${created?.name||'未命名剧'}》`,'text-green-400');
      await loadDramaProjects(false);
      await openDramaProject(created.id);
    }else{
      const created=result.project;
      log(`已创建短片重做版本《${created?.title||'未命名短片'}》`,'text-green-400');
      await loadProjects(false);
      await openProject(created.id);
      if(mode==='full'||mode==='script'){
        $('continue-bar')?.remove();
        const bar=document.createElement('div');
        bar.id='continue-bar';bar.className='glass rounded-2xl p-5 mt-4';
        bar.innerHTML='<div class="text-sm text-yellow-200">已返回剧本生成步骤</div><p class="text-xs text-gray-400 mt-2">可先修改上方故事和导演方案，确认导演方案后点击下方按钮。新剧本生成后会先停下供你查阅。</p><button type="button" id="remake-script-start" class="btn-gold px-5 py-2 rounded-lg text-sm mt-3">重新生成剧本</button>';
        $('pipeline-box').before(bar);
        $('remake-script-start').onclick=()=>{
          if(directorConfirmedSignature!==directorSignature()){alert('请先确认上方导演方案');return;}
          regenerateScriptFromDirector();
        };
        $('idea').scrollIntoView({behavior:'smooth',block:'center'});
      }
    }
  }catch(error){
    $('remake-status').textContent=error.message;
    alert(error.message);
  }finally{
    button.disabled=false;button.textContent='创建重做版本';
  }
}
function renderProjectList(){
  const q=($('proj-search')?.value||'').trim().toLowerCase(), filter=$('proj-filter')?.value||'all';
  const list=PROJECT_LIST.filter(p=>{if(p.series)return false;const hit=!q||String(p.title||p.id||'').toLowerCase().includes(q);const st=filter==='all'||(filter==='final'&&p.final)||(filter==='unfinished'&&!p.final);return hit&&st;});
  const html=list.length?list.map(p=>{
    const encodedProject=encodeURIComponent(String(p.id||''));
    return `<div class="workspace-list-item" onclick="openProject(decodeURIComponent('${encodedProject}'))">
      <div class="workspace-item-heading">
        <div class="workspace-item-title">${escapeHtml(p.title||'未命名')}${teamOwnerBadge(p)}</div>
        <button class="workspace-rename-button" onclick="event.stopPropagation();renameProjectFromList('${encodedProject}')" title="重命名单集片名" aria-label="重命名单集片名">✎</button>
      </div>
      <div class="workspace-item-meta">${new Date(p.created*1000).toLocaleString()} · ${p.final?'已有成片':'未完成'}<button class="ml-2 text-yellow-300 hover:text-yellow-100" onclick="event.stopPropagation();openRemakeModal('project','${encodedProject}',${escapeHtml(JSON.stringify(p.title||'未命名短片'))})" title="复制为新版本重做">🔄</button></div>
    </div>`;
  }).join(''):'<div class="workspace-muted">没有符合条件的项目</div>';
  if($('proj-list'))$('proj-list').innerHTML=html;
  if($('side-project-list'))$('side-project-list').innerHTML=list.length?list.map(p=>{
    const state=p.final?'is-final':'is-pending';
    const encoded=encodeURIComponent(String(p.id||''));
    return `<div class="side-tree-item ${state}" onclick="openProject(decodeURIComponent('${encoded}'))" title="${escapeHtml(p.title||p.id||'')}">
      <span class="side-tree-dot"></span><span class="side-tree-title">${escapeHtml(p.title||'未命名')}${teamOwnerBadge(p)}</span>
      <button class="ml-auto text-[11px] text-yellow-300" onclick="event.stopPropagation();openRemakeModal('project','${encoded}',${escapeHtml(JSON.stringify(p.title||'未命名短片'))})" title="复制为新版本重做" aria-label="复制为新版本重做">🔄</button>
    </div>`;
  }).join(''):'<div class="side-tree-empty">暂无短片</div>';
}
async function loadProjects(showModal=true){
  PROJECT_LIST=await(await fetch('/api/projects')).json();
  if($('proj-search'))$('proj-search').value='';if($('proj-filter'))$('proj-filter').value='all';renderProjectList();
  if(showModal)$('proj-modal').classList.replace('hidden','flex');
}
async function deleteProject(pid){
  if(!confirm('确定删除这个历史项目？\n该项目已生成的视频文件将一并删除，不可恢复。'))return;
  const r=await(await fetch('/api/project/'+pid+'/delete',{method:'POST'})).json();
  if(r.ok){log('项目已删除','text-gray-400');loadProjects();}
  else alert('删除失败: '+(r.msg||'未知错误'));
}
async function renameProjectFromList(encodedPid){
  const pid=decodeURIComponent(encodedPid||'');
  const item=PROJECT_LIST.find(x=>String(x.id)===pid);
  const title=prompt('请输入新的单集片名：',item?.title||'');
  if(title===null)return;
  const next=title.trim();
  if(!next){alert('单集片名不能为空');return;}
  try{
    const r=await(await fetch(`/api/project/${encodeURIComponent(pid)}/rename`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})})).json();
    if(!r.ok)throw new Error(r.msg||'重命名失败');
    if(item)item.title=next;
    renderProjectList();
    if(currentPid===pid)$('proj-title').textContent=next;
    log(`单集片名已改为《${next}》`,'text-green-400');
  }catch(e){alert('重命名失败：'+e.message);}
}
async function renameSeriesFromList(encodedSeriesId){
  const seriesId=decodeURIComponent(encodedSeriesId||'');
  const item=DRAMA_PROJECT_LIST.find(x=>String(x.id)===seriesId);
  const name=prompt('请输入新的剧名：',item?.name||'');
  if(name===null)return;
  const next=name.trim();
  if(!next){alert('剧名不能为空');return;}
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(seriesId)}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:next,premise:item?.premise||''})})).json();
    if(!r.ok)throw new Error(r.msg||'重命名失败');
    if(item)item.name=next;
    renderDramaProjectList();
    if(SERIES_CURRENT?.id===seriesId){SERIES_CURRENT=r.series;renderManualSeriesProject(SERIES_CURRENT);}
    log(`剧名已改为《${next}》`,'text-green-400');
  }catch(e){alert('重命名失败：'+e.message);}
}
async function renameSeriesEpisodeFromList(encodedSeriesId,episode){
  const seriesId=decodeURIComponent(encodedSeriesId||'');
  const series=DRAMA_PROJECT_LIST.find(x=>String(x.id)===seriesId);
  const item=series?.episodes?.[String(episode)]||{};
  const title=prompt(`请输入第${episode}集的新片名：`,item.title||`第${episode}集`);
  if(title===null)return;
  const next=title.trim();
  if(!next){alert('单集片名不能为空');return;}
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(seriesId)}/episode/${episode}/rename`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})})).json();
    if(!r.ok)throw new Error(r.msg||'重命名失败');
    await loadDramaProjects(false);
    if(SERIES_CURRENT?.id===seriesId){SERIES_CURRENT=r.series;renderManualSeriesProject(SERIES_CURRENT);}
    log(`第${episode}集片名已改为《${next}》`,'text-green-400');
  }catch(e){alert('重命名失败：'+e.message);}
}
async function renameCurrentProject(){
  if(!currentPid)return;
  const current=($('proj-title')?.textContent||'').trim();
  const title=prompt('请输入新的单集片名：',current);
  if(title===null)return;
  const next=title.trim();
  if(!next){alert('单集片名不能为空');return;}
  try{
    const r=await(await fetch(`/api/project/${encodeURIComponent(currentPid)}/rename`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})})).json();
    if(!r.ok){alert(r.msg||'重命名失败');return;}
    $('proj-title').textContent=next;
    if($('final-title'))$('final-title').textContent=`《${next}》`;
    if(window._lastFinalData)window._lastFinalData.title=next;
    log(`单集片名已改为《${next}》`,'text-green-400');
    if(SERIES_CURRENT)refreshCurrentSeries();
  }catch(e){alert('重命名失败: '+e.message);}
}
// 接着历史项目未完成的进度继续生成（已完成的分镜/资产自动跳过）
function continueProject(pid){
  setCurrentProjectId(pid);
  saveLastView();
  if(window._projIdea){setStoryText(stripDirectorBrief(window._projIdea));hydrateDirectorFromIdea(window._projIdea);directorMatched=true;directorConfirmedSignature=directorSignature();updateIdeaCount();setDirectorStatus('已载入已确认的导演方案','ok');}  // 展示原始故事；续跑时内部仍使用项目完整创意
  const bar=$('continue-bar');if(bar)bar.remove();
  const res=$('resynth-bar');if(res)res.remove();
  runPipeline(pid);  // 传 pid 续跑；后端自动跳过已完成的分镜/资产
}
function setCurrentProjectId(pid){
  if(pid!==currentPid){storyChatState={story:$('idea').value,history:[],undo:null};renderStoryChat();}
  projectOpenVersion++;
  currentPid=pid;
  window.dispatchEvent(new Event('current-project-change'));
}
let projectOpenVersion=0;
let projectOpenController=null;
let loadingProjectView = false;
async function openProject(pid,options={}){
  const openVersion=++projectOpenVersion;
  const preservedScrollY = options.restoreScrollY ?? window.scrollY;
  projectOpenController?.abort();
  const controller=new AbortController();
  projectOpenController=controller;
  let r;
  try {
    const response=await fetch('/api/project/'+encodeURIComponent(pid)+'?active_only=1',{signal:controller.signal});
    r=await response.json();
  } catch(error) {
    if(error.name==='AbortError')return false;
    log('作品加载失败：'+error.message,'text-red-400');return false;
  } finally {
    if(projectOpenController===controller)projectOpenController=null;
  }
  if(openVersion!==projectOpenVersion)return false;
  if(!r.ok){if(String(readLastView()?.pid||'')===String(pid))clearLastView();return false;}
  loadingProjectView = true;
  try {
  const p=r.project;ASSET_EDIT_DATA=Object.fromEntries((p.assets||[]).map(a=>[a.key,a]));setGenerationReference(p.generation_reference||null);window.bridgeSupported=!!p.bridge_supported;$('proj-modal').classList.replace('flex','hidden');
  window.studioAssetsConfirmed=!!p.asset_confirm?.__all__?.continue;
  setCurrentProjectId(pid);saveLastView();if($('side-process-project'))$('side-process-project').textContent=p.title||pid;
  if(p.idea){setStoryText(stripDirectorBrief(p.idea));directorMatched=hydrateDirectorFromProject(p);directorConfirmedSignature=directorMatched?directorSignature():'';updateIdeaCount();setDirectorStatus(directorMatched?'已载入已确认的导演方案':'输入梗概后先让 AI 匹配',directorMatched?'ok':'muted');}
  renderStages();$('pipeline-box').classList.remove('hidden');
  ['continue-bar','resynth-bar','assets-confirm-bar','shots-confirm-bar','prompt-batch-bar','render-groups','script-review-bar'].forEach(id=>$(id)?.remove());
  $('final-box').classList.add('hidden');
  if(p.script){renderScript(p.script);setStage(1,'stage-done');}
  else{
    SCRIPT_DATA=null;SHOT_DATA={};scriptChatHistory=[];
    $('script-box').classList.add('hidden');$('shots-box').classList.add('hidden');
    ['char-list','scene-list','prop-list','shot-grid'].forEach(id=>$(id).innerHTML='');
    $('script-summary')?.remove();$('proj-title').textContent=p.title||'';
  }
  $('proj-title').dataset.projectId=pid;
  $('proj-title').dataset.episode=p.series?.episode||'';
  $('proj-title').textContent=p.title||p.script?.title||'未命名作品';
  scriptChatHistory=structuredClone(p.script_edit_archive?.chat_history||[]);renderScriptChat();
  if(p.preview_project_id){
    try{
      const preview=await (await fetch('/api/project/'+encodeURIComponent(p.preview_project_id)+'?active_only=1')).json();
      const pp=preview.project||{};
      const ready=(pp.shots||[]).filter(s=>s.video_url&&!s.error);
      if(ready.length){
        // 正式项目卡片已先建立，覆盖相同镜头的正式视频为小样预览，避免后续初始化把小样清掉。
        ready.forEach(s=>{const data={...s,preview:true};SHOT_DATA[s.index]=data;addShotCard(data);});
        log(`已加载小样分支：${ready.length} 个镜头，可先审查小样`,'gold');
      }
    }catch(_){/* 小样不存在时保持正式项目正常打开 */}
  }
  if(p.script&&p.script_review_required&&!p.script_confirmed)showScriptReviewBar({msg:'已载入待查阅剧本，请确认后继续制作。'});
  $('reference-sync-bar')?.remove();if(Object.keys(p.reference_sync||{}).length)showReferenceSyncBar();
  const expectedAssets=p.script?((p.script.characters||[]).length+(p.script.scenes||[]).length+(p.script.props||[]).length):0;
  if(expectedAssets>0&&(p.assets||[]).length>=expectedAssets)setStage(2,'stage-done');
  if(expectedAssets>0&&(p.assets||[]).filter(a=>a.url).length>=expectedAssets&&!p.asset_confirm?.__all__?.continue&&!p.final)showAssetsConfirmBar({assets:p.assets});
  if(p.script){showRenderGroups(p.render_groups||[]);if(Object.values(p.prompt_failures||{}).some(f=>f.status==='needs_edit'&&f.prompt))showPromptBatchBar({shots:[]});}
  const expectedShots=p.script?(p.script.shots||[]).length:0;
  // Normalize legacy local paths before counting rendered shots. Older
  // projects may have a valid generated file but no persisted video_url yet.
  (p.shots||[]).forEach(sh=>{
    if(!sh.video_url){
      const raw=sh.local_path||sh.path||'';
      const m=raw.replaceAll('\\\\','/').match(/(?:^|\/)outputs\/([^/]+)\/(shot_[^/]+\.(?:mp4|webm))$/i);
      if(m) sh.video_url=`/file/outputs/${encodeURIComponent(m[1])}/${encodeURIComponent(m[2])}`;
    }
  });
  // 用户只需要所有镜头都有视频即可进入下一步；审片、连续性同步等
  // 状态不再阻塞按钮，具体文件完整性由后端合成前校验。
  const okShots=(p.shots||[]).filter(sh=>sh.video_url&&!sh.error).length;
  if(expectedShots>0&&okShots>=expectedShots)setStage(3,'stage-done');
  if(expectedShots>0&&okShots>=expectedShots&&!p.final){
    (p.shots||[]).forEach(sh=>{SHOT_DATA[sh.index]=sh;});
    window.studioAssetsConfirmed=true;
    setStageView(2);
  }
  if(p.final)setStage(4,'stage-done');
  (p.assets||[]).forEach(a=>{const kind=a.kind==='character'?'character':(a.kind==='prop'?'prop':'scene');addAssetCard({type:kind,name:a.key.replace(/^(char|scene|prop)_/,''),url:a.url,prompt:a.prompt,cached:true});});
  (p.shots||[]).forEach(sh=>{
    // Older project records store only a relative local path. Normalize it
    // when reopening so generated videos remain visible after a refresh.
    if(!sh.video_url){
      const raw=sh.local_path||sh.path||'';
      const m=raw.replaceAll('\\\\','/').match(/(?:^|\/)outputs\/([^/]+)\/(shot_[^/]+\.(?:mp4|webm))$/i);
      if(m) sh.video_url=`/file/outputs/${encodeURIComponent(m[1])}/${encodeURIComponent(m[2])}`;
    }
    SHOT_DATA[sh.index]=sh;
    if(sh.error)showShotError(sh.index,sh.error);else addShotCard(sh);
  });
  if(expectedShots>0&&okShots>=expectedShots&&!p.final){
    window.studioAssetsConfirmed=true;
    setStageView(2);
  }
  Object.entries(p.reviews||{}).forEach(([idx,r])=>applyShotReview(parseInt(idx),r));
  const manualProject=!!(p.render_config&&p.render_config.manual_mode);
  const batchPromptProject=!!(p.render_config&&(p.render_config.batch_prompt_mode||p.render_config.manual_mode));
  if(manualProject){
    (p.shots||[]).forEach(sh=>{
      const cf=(p.shot_confirm||{})[String(sh.index)]||{};
      if(!sh.video_url&&!sh.error&&sh.prompt&&!cf.confirmed){
        if(batchPromptProject)showShotBatchEditor(sh.index,sh.prompt,sh.duration||8,sh.camera||SHOT_DATA[sh.index]?.camera||'');
        else showShotConfirm(sh.index,sh.prompt,sh.duration||8,sh.camera||SHOT_DATA[sh.index]?.camera||'');
      }
    });
  }
  if(batchPromptProject&&expectedShots>0)showPromptBatchBar({shots:p.shots||[]});
  if(p.final||p.previous_final)showFinal({video_url:p.final||p.previous_final,title:p.title,needs_resynth:!p.final});
  window._projIdea=p.idea||'';
  setStoryText(stripDirectorBrief(p.idea||''));updateIdeaCount();
  if(p.custom_assets&&!p.assets_confirmed){log('该项目处于自定义参考图待确认状态，可继续上传后点「继续生成」','gold');showAssetUploadUI();}
  // 载入存在失败镜的项目时，提示可重制失败镜后重新合成
  const failedShots=(p.shots||[]).filter(sh=>sh.error);
  if(failedShots.length){showResynthUI({msg:`该项目有 ${failedShots.length} 个分镜未成功。请在分镜卡片中重新渲染失败镜，完成后使用底部按钮合成成片。`});}
  log(`已载入项目《${p.title||pid}》`,'gold');
  return true;
  } finally {
    loadingProjectView = false;
    requestAnimationFrame(()=>requestAnimationFrame(()=>window.scrollTo({top:Math.max(0,Number(preservedScrollY)||0),behavior:'instant'})));
  }
}


// ---------- 剧项目详情：不做整季AI规划，只管理Story Bible与逐集创作 ----------
let SERIES_CURRENT=null;
function closeSeriesFactory(){$('series-modal').classList.replace('flex','hidden');}
function openSeriesFactory(){
  if(SERIES_CURRENT){renderManualSeriesProject(SERIES_CURRENT);$('series-modal').classList.replace('hidden','flex');}
  else loadDramaProjects();
}
function seriesEpisodeNumbers(s){return Object.keys((s&&s.episode_status)||{}).map(x=>parseInt(x)).filter(Number.isFinite).sort((a,b)=>a-b);}
function renderManualSeriesProject(s){
  if(!s)return;
  SERIES_CURRENT=s;
  $('series-factory-name').value=s.name||'';
  $('series-factory-premise').value=s.premise||'';
  const nums=seriesEpisodeNumbers(s), next=(nums.length?Math.max(...nums)+1:1);
  $('series-new-episode').value=next;
  const charN=Object.keys(s.characters||{}).length, sceneN=Object.keys(s.scenes||{}).length, propN=Object.keys(s.props||{}).length, assetN=Object.keys(s.assets||{}).length;
  $('series-bible-summary').textContent=`Story Bible：角色 ${charN} · 场景 ${sceneN} · 道具 ${propN} · 已复用资产 ${assetN}`;
  $('series-episode-count').textContent=`${nums.length}集`;
  const statuses=s.episode_status||{}, episodes=s.episodes||{};
  $('series-episode-list').innerHTML=nums.length?nums.map(no=>{
    const st=statuses[String(no)]||{}, meta=episodes[String(no)]||{};
    const badge=st.has_final?'<span class="tag">已有成片</span>':st.has_script?'<span class="tag" style="background:rgba(143,211,244,.12);color:#8fd3f4">制作中</span>':'<span class="text-gray-600 text-xs">待创作</span>';
    const title=st.title||meta.title||`第${no}集`;
    const synopsis=(meta.synopsis||'').trim();
    return `<div class="bg-black/30 border border-white/10 rounded-xl p-3">
      <div class="flex items-center gap-2"><span class="tag">第${no}集</span><div class="font-bold text-sm truncate">${escapeHtml(title)}</div><button onclick="renameSeriesEpisode(${no});event.stopPropagation();" class="text-xs px-2 py-1 rounded glass hover:bg-yellow-400/20 transition" title="重命名单集片名" aria-label="重命名第${no}集">✏️</button>${badge}<div class="flex-1"></div>
        ${st.project_id?`<button onclick="addEpisodeToRenderQueue('${String(st.project_id).replace(/'/g,'')}');event.stopPropagation();" class="text-xs px-2 py-1 rounded glass hover:bg-yellow-400/20" title="加入视频生成队列">🚀 排队</button>${st.final?`<button onclick="${escapeHtml(episodePreviewOnclick(st.final,`第${no}集 · ${title}`))};event.stopPropagation();" class="text-xs px-2 py-1 rounded glass hover:bg-green-400/20 text-green-300" title="预览成片">▶ 预览</button>`:''}<button onclick="openEpisodeProject('${String(st.project_id).replace(/'/g,'')}')" class="text-xs px-2 py-1 rounded glass hover:bg-white/10">打开本集</button><button onclick="openRemakeModal('project','${String(st.project_id).replace(/'/g,'')}',${escapeHtml(JSON.stringify(title))});event.stopPropagation();" class="text-xs px-2 py-1 rounded glass hover:bg-yellow-400/20" title="复制为本集重做版本">🔄 重做</button>`:`<button onclick="continueManualSeriesEpisode(${no})" class="text-xs px-2 py-1 rounded glass hover:bg-yellow-400/20">开始创作</button>`}
      </div>
      <div class="mt-2 text-xs text-gray-500 line-clamp-2">${escapeHtml(synopsis||'本集剧情由你自己填写，系统不会自动规划。')}</div>
      ${st.failed_shots?`<div class="mt-1 text-xs text-red-300">⚠ ${st.failed_shots} 个失败镜头待处理</div>`:''}
    </div>`;
  }).join(''):'<div class="text-gray-500 text-center py-10 md:col-span-2">这部剧还没有集数。上方输入集数后点击「＋ 新建这一集」。</div>';
}
async function refreshCurrentSeries(){
  if(!SERIES_CURRENT)return;
  try{const r=await(await fetch(`/api/series/${encodeURIComponent(SERIES_CURRENT.id)}`)).json();if(r.ok)renderManualSeriesProject(r.series);}catch(e){alert('刷新失败: '+e.message);}
}
async function saveSeriesSettings(){
  if(!SERIES_CURRENT)return;
  const name=$('series-factory-name').value.trim(),premise=$('series-factory-premise').value.trim(),btn=$('series-save-btn');
  if(!name){alert('剧名不能为空');return;}
  btn.disabled=true;btn.textContent='保存中…';
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(SERIES_CURRENT.id)}/update`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,premise})})).json();
    if(!r.ok){alert(r.msg||'保存失败');return;}
    SERIES_CURRENT=r.series;renderManualSeriesProject(SERIES_CURRENT);log(`剧名已改为《${SERIES_CURRENT.name}》，核心设定已保存`,'text-green-400');loadDramaProjects(false);
  }catch(e){alert('保存失败: '+e.message);}finally{btn.disabled=false;btn.textContent='💾 保存剧名和设定';}
}
async function renameSeriesEpisode(no){
  if(!SERIES_CURRENT)return;
  const status=(SERIES_CURRENT.episode_status||{})[String(no)]||{};
  const meta=(SERIES_CURRENT.episodes||{})[String(no)]||{};
  const current=status.title||meta.title||`第${no}集`;
  const title=prompt(`请输入第${no}集的新片名：`,current);
  if(title===null)return;
  const next=title.trim();
  if(!next){alert('单集片名不能为空');return;}
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(SERIES_CURRENT.id)}/episode/${no}/rename`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})})).json();
    if(!r.ok){alert(r.msg||'重命名失败');return;}
    SERIES_CURRENT=r.series;renderManualSeriesProject(SERIES_CURRENT);loadDramaProjects(false);
    log(`第${no}集片名已改为《${next}》`,'text-green-400');
  }catch(e){alert('重命名失败: '+e.message);}
}
async function newSeriesEpisode(){
  if(!SERIES_CURRENT)return;
  const no=Math.max(1,parseInt($('series-new-episode').value)||1);
  const existing=(SERIES_CURRENT.episode_status||{})[String(no)];
  if(existing&&existing.project_id){if(confirm(`第${no}集已经存在，是否直接打开？`))openEpisodeProject(existing.project_id);return;}
  try{
    const r=await(await fetch(`/api/series/${encodeURIComponent(SERIES_CURRENT.id)}/episode/register`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({episode:no})})).json();
    if(!r.ok){alert(r.msg||'新建失败');return;}
    SERIES_CURRENT=r.series;
    const created=(SERIES_CURRENT.episode_status||{})[String(no)]||{};
    if(created.project_id){ await openProject(created.project_id); }
    else continueManualSeriesEpisode(no);
    return created.project_id||null;
  }catch(e){alert('新建失败: '+e.message);}
}
function continueManualSeriesEpisode(no){
  if(!SERIES_CURRENT)return;
  const prev=((SERIES_CURRENT.episodes||{})[String(no-1)]||{});
  $('series-mode').checked=true;
  $('series-name').value=SERIES_CURRENT.name||'';
  $('episode-no').value=no;
  $('prev-summary').value=prev.synopsis||prev.title||'';
  toggleSeriesMode();applyDirectorPreset('serial');
  $('idea').value='';updateIdeaCount();queueDraftSave();closeSeriesFactory();
  window.scrollTo({top:0,behavior:'smooth'});setTimeout(()=>$('idea')?.focus(),250);
  flashDraftStatus(`已进入《${SERIES_CURRENT.name}》第${no}集，请自己填写本集剧情`);
}

// ---------- 单镜头生成器 ----------
let singleMode='r2v', singleSlots=[], singleTaskId=null, singleResult=null, singleReplace=null, uploadTargetSlot=0;
let singleOrganizeController=null;
let singlePollTimer=null;
function singleTaskStorageKey(context){return DRAFT_KEY+':single-task:'+ (context?context.pid+':'+context.index:'standalone');}
function saveSingleTask(){try{localStorage.setItem(singleTaskStorageKey(singleReplace),JSON.stringify({taskId:singleTaskId,mode:singleMode,slots:singleSlots,prompt:$('single-prompt').value,idea:$('single-idea').value,duration:$('single-duration').value}));}catch(e){}}

const SLOT_COUNT={r2v:9,i2v:2,t2v:0};

function openSingle(prefill){
  singleOrganizeController?.abort();
  clearTimeout(singlePollTimer);
  prefill=prefill||{};
  singleReplace=prefill.replace||null;
  $('single-replace-tag').classList.toggle('hidden',!singleReplace);
  if(singleReplace)$('single-replace-tag').textContent=`重制镜头 ${singleReplace.index}`;
  const refs=(prefill.refs||[]).map(p=>({path:p,url:'/file/'+String(p).replace(/\\/g,'/')+'?t='+Date.now()}));
  const initialMode=prefill.mode||'r2v';
  singleSlots=Array.from({length:initialMode==='r2v'?Math.min(9,Math.max(1,refs.length)):SLOT_COUNT[initialMode]},()=>null);
  setSingleMode(initialMode);
  refs.forEach((r,i)=>{if(i<singleSlots.length)singleSlots[i]=r;});
  renderSingleRefs();
  $('single-idea').value=prefill.idea||'';
  $('single-prompt').value=prefill.prompt||'';
  if(prefill.duration)$('single-duration').value=String(prefill.duration);
  $('single-result').classList.add('hidden');$('single-status').textContent='';$('single-apply').classList.add('hidden');
  singleResult=null;singleTaskId=null;
  $('single-modal').classList.replace('hidden','flex');
  singleGenDone();
  try{
    const saved=JSON.parse(localStorage.getItem(singleTaskStorageKey(singleReplace))||'null');
    if(saved?.taskId){
      setSingleMode(saved.mode);singleSlots=saved.slots;renderSingleRefs();
      $('single-prompt').value=saved.prompt||'';$('single-idea').value=saved.idea||'';$('single-duration').value=saved.duration||'8';
      singleTaskId=saved.taskId;$('btn-single-gen').disabled=true;$('single-status').textContent='正在恢复上次生成结果…';pollSingle();
    }
  }catch(e){}
}

function closeSingle(){singleOrganizeController?.abort();$('single-modal').classList.replace('flex','hidden');}
function setSingleMode(m){
  singleMode=m;
  document.querySelectorAll('.single-mode-btn').forEach(b=>{
    const on=b.dataset.mode===m;
    b.className='single-mode-btn flex-1 py-2 rounded-xl text-sm transition '+(on?'btn-gold':'glass hover:bg-white/10');
  });
  $('single-refs-box').classList.toggle('hidden',m==='t2v');
  $('single-ref-hint').textContent={r2v:'（1~9张，第1张为主体，可点击或拖入替换）',i2v:'（首帧必填，尾帧可选，可点击或拖入替换）',t2v:''}[m];
  const n=m==='r2v'?Math.min(9,Math.max(1,singleSlots.length||1)):SLOT_COUNT[m];
  singleSlots=Array.from({length:n},(_,i)=>singleSlots[i]||null);
  renderSingleRefs();
}
function addSingleReferenceSlot(){
  if(singleMode!=='r2v')return;
  if(singleSlots.length>=9){$('single-status').textContent='最多添加9张参考图';return;}
  singleSlots.push(null);renderSingleRefs();pickSlotImage(singleSlots.length-1);
}
function slotLabel(i){
  if(singleMode==='i2v')return i===0?'首帧':'尾帧';
  return 'Picture '+(i+1);
}
function renderSingleRefs(){
  $('single-refs').innerHTML=singleSlots.map((r,i)=>{
    if(!r)return `
    <div onclick="pickSlotImage(${i})" data-single-slot="${i}" class="single-reference-slot w-20 h-20 rounded-lg border border-dashed border-white/20 flex flex-col items-center justify-center hover:border-yellow-400/60 hover:bg-white/5 transition" title="点击上传${slotLabel(i)}">
      <div class="text-gray-500 text-lg leading-none">+</div>
      <div class="text-gray-600 mt-1" style="font-size:10px;">${slotLabel(i)}</div>
    </div>`;
    return `
    <div class="single-reference-slot relative group" data-single-slot="${i}" title="点击图片查看大图；点击图片上的更换按钮替换，也可拖入图片替换">
      <img src="${r.url}" onclick="event.stopPropagation();openImageLightbox('${String(r.url).replace(/'/g,"\\'")}','${slotLabel(i)}')" class="w-20 h-20 object-cover rounded-lg border border-white/10" alt="${slotLabel(i)}参考图">
      <button type="button" class="single-reference-change" onclick="event.stopPropagation();pickSlotImage(${i})">更换</button>
      <div class="absolute bottom-0 left-0 right-0 text-center rounded-b-lg" style="font-size:10px;background:rgba(0,0,0,.6);">${slotLabel(i)}</div>
      <button onclick="event.stopPropagation();singleSlots[${i}]=null;renderSingleRefs()" class="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-red-500 text-white text-xs hidden group-hover:flex items-center justify-center" title="移除参考图">×</button>
    </div>`;
  }).join('');
  const add=$('single-add-ref');
  if(add){add.classList.toggle('hidden',singleMode!=='r2v'||singleSlots.length>=9);add.classList.toggle('flex',singleMode==='r2v'&&singleSlots.length<9);}
  document.querySelectorAll('[data-single-slot]').forEach(slot=>{
    const index=Number(slot.dataset.singleSlot);
    ['dragenter','dragover'].forEach(type=>slot.addEventListener(type,event=>{event.preventDefault();event.stopPropagation();slot.classList.add('is-dragover');}));
    ['dragleave','drop'].forEach(type=>slot.addEventListener(type,event=>{event.preventDefault();event.stopPropagation();slot.classList.remove('is-dragover');}));
    slot.addEventListener('drop',event=>{const file=[...(event.dataTransfer?.files||[])].find(item=>item.type.startsWith('image/'));if(file)uploadSingleRefFile(file,index);});
  });
}
function pickSlotImage(i){uploadTargetSlot=i;$('single-file').click();}
async function uploadSingleRefFile(file,index){
  if(!file)return;
  $('single-status').textContent='参考图上传中…';
  try{
    const fd=new FormData();fd.append('file',file);
    const result=await(await fetch('/api/single_shot/upload',{method:'POST',body:fd})).json();
    if(result.error)throw new Error(result.error);
    singleSlots[index]=result;renderSingleRefs();$('single-status').textContent=`已更换${slotLabel(index)}参考图`;
  }catch(error){$('single-status').textContent='';alert('更换参考图失败：'+error.message);}
}
async function uploadSingleRef(input){
  const f=input.files[0];input.value='';if(!f)return;
  await uploadSingleRefFile(f,uploadTargetSlot);
}
function filledSlots(){return singleSlots.filter(Boolean);}
async function singleOrganize(){
  const idea=$('single-idea').value.trim();
  if(!idea){alert('先输入创作要求');return;}
  if(singleMode==='i2v'&&!singleSlots[0]){alert('i2v模式请先上传首帧图');return;}
  if(singleMode==='r2v'&&!filledSlots().length){alert('r2v模式请先上传至少1张参考图');return;}
  if(singleOrganizeController)return;
  const controller=new AbortController();singleOrganizeController=controller;
  const started=Date.now();let timedOut=false;
  $('btn-organize').disabled=true;$('btn-organize').textContent='整理中...';
  const showElapsed=()=>{$('single-status').textContent=`AI正在读取参考图并整理提示词，已等待 ${Math.floor((Date.now()-started)/1000)} 秒（最多等待180秒）…`;};
  showElapsed();
  const ticker=setInterval(showElapsed,1000);
  const timeout=setTimeout(()=>{timedOut=true;controller.abort();},180000);
  try{
    const response=await fetch('/api/single_shot/prompt',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({mode:singleMode,idea,duration:parseInt($('single-duration').value),ref_count:Math.max(1,filledSlots().length),ref_paths:filledSlots().map(x=>x.path)})});
    if(!response.headers.get('content-type')?.includes('application/json'))throw new Error(response.redirected?'登录已过期，请重新登录':'服务未返回有效结果（HTTP '+response.status+'）');
    const r=await response.json();
    if(!response.ok||r.error)throw new Error(r.error||'请求失败（HTTP '+response.status+'）');
    if(!r.prompt?.trim())throw new Error('模型返回了空提示词，请重试');
    if(controller.signal.aborted)return;
    $('single-prompt').value=r.prompt;
    $('single-status').textContent='提示词已整理完成，请检查后生成视频。';
  }catch(e){
    $('single-status').textContent=timedOut
      ?'AI整理等待超过180秒，已停止本次等待。创作要求和原提示词已保留。后台请求可能仍在处理，请稍后重试；也可以直接编辑H3提示词。'
      :e.name==='AbortError'?'已停止等待，输入内容已保留。':'AI整理失败：'+e.message;
  }finally{
    clearInterval(ticker);clearTimeout(timeout);
    singleOrganizeController=null;
    $('btn-organize').disabled=false;$('btn-organize').textContent='✨ AI整理';
  }
}
async function singleGenerate(){
  const prompt=$('single-prompt').value.trim();
  if(!prompt){alert('提示词为空，先AI整理或手动编写');return;}
  let refPaths=[];
  if(singleMode==='r2v'){
    refPaths=filledSlots().map(x=>x.path);
    if(!refPaths.length){alert('r2v模式需要至少1张参考图');return;}
  }else if(singleMode==='i2v'){
    if(!singleSlots[0]){alert('i2v模式需要上传首帧图');return;}
    refPaths=[singleSlots[0].path];
    if(singleSlots[1])refPaths.push(singleSlots[1].path);  // 尾帧可选
  }
  $('btn-single-gen').disabled=true;$('btn-single-gen').textContent='🎬 渲染中...';
  $('single-result').classList.add('hidden');$('single-apply').classList.add('hidden');
  try{
    const r=await(await fetch('/api/single_shot/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:singleMode,prompt,project_context:singleReplace,ref_paths:refPaths,duration:parseInt($('single-duration').value)})})).json();
    if(r.error){alert(r.error);singleGenDone();return;}
    singleTaskId=r.task_id;saveSingleTask();pollSingle();
  }catch(e){alert('提交失败: '+e);singleGenDone();}
}
function singleGenDone(){$('btn-single-gen').disabled=false;$('btn-single-gen').textContent='🚀 生成视频';}
async function pollSingle(){
  if(!singleTaskId)return;
  const taskId=singleTaskId;
  try{
    const t=await(await fetch('/api/single_shot/status/'+taskId,{cache:'no-store'})).json();
    if(taskId!==singleTaskId)return;
    if(t.status==='running'){$('single-status').innerHTML=taskProgressHtml(t,'MiniMax H3渲染中');singlePollTimer=setTimeout(pollSingle,1000);return;}
    $('single-status').textContent=t.msg||'';
    if(t.status==='done'){
      singleResult=t;
      $('single-video').src=t.video_url;enableVideoAudio($('single-video'));$('single-dl').href=t.video_url;
      $('single-result').classList.remove('hidden');
      if(singleReplace&&!t.applied)$('single-apply').classList.remove('hidden');
      if(singleReplace&&t.applied&&currentPid===singleReplace.pid){addShotCard({index:singleReplace.index,video_url:t.video_url,audio_review:t.audio_review});if(SHOT_DATA[singleReplace.index])SHOT_DATA[singleReplace.index].video_url=t.video_url;}
      log('单镜头视频生成完成','text-green-400');
    }else{
      log('单镜头生成失败: '+(t.msg||''),'text-red-400');
    }
  }catch(e){if(taskId===singleTaskId)singlePollTimer=setTimeout(pollSingle,5000);return;}
  singleGenDone();
}
async function applySingleReplace(){
  if(!singleReplace||!singleResult)return;
  const r=await(await fetch(`/api/project/${singleReplace.pid}/shot/${singleReplace.index}/replace`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({src_path:singleResult.local_path,prompt:$('single-prompt').value.trim()})})).json();
  if(r.error){alert(r.error);return;}
  addShotCard(r.shot);
  try{localStorage.removeItem(singleTaskStorageKey(singleReplace));}catch(e){}
  if(SHOT_DATA[singleReplace.index])Object.assign(SHOT_DATA[singleReplace.index],{video_url:r.shot.video_url,prompt:r.shot.prompt,refs:filledSlots().map(x=>x.path),duration:parseInt($('single-duration').value)});
  log(`镜头${singleReplace.index}已重制替换（正片需重新一键合成）`,'text-green-400');
  closeSingle();
}
async function remakeShot(idx){
  if(!currentPid){alert('没有活动项目');return;}
  const button=document.querySelector(`#shot-${idx} button[onclick*="remakeShot"]`);
  // 直接调用项目分镜渲染流：后端会重新规划镜头，并按项目流程补齐提示词、参考图和其它依赖。
  generateBridgeShot(idx,button||{disabled:false,textContent:''});
}

// 主界面分辨率/步数变更时实时同步到后端配置，确保单镜头生成器等所有入口立即生效
async function syncMainConfig(){
  try{
    const [asp,mp]=$('resolution').value.split('|');
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({aspect_ratio:asp,megapixels:parseFloat(mp),h3_steps:parseInt($('h3Steps').value)||8,prompt_skill_mode:$('prompt-skill-mode')?.value||'auto',video_skill_id:$('prompt-skill-mode')?.value||'auto',script_skill_id:$('script-skill-mode')?.value||'auto',subtitle_enabled:$('subtitleEnabled')?.checked||false})});
  }catch(e){}
}
$('resolution').addEventListener('change',syncMainConfig);
$('h3Steps').addEventListener('change',syncMainConfig);

window.addEventListener('pagehide',saveLastView);
window.addEventListener('beforeunload',saveLastView);
let lastViewScrollTimer=null;
window.addEventListener('scroll',()=>{
  if(!currentPid||lastViewScrollTimer)return;
  lastViewScrollTimer=setTimeout(()=>{
    lastViewScrollTimer=null;
    saveLastView();
  },500);
},{passive:true});
async function initializeWorkspace(){
  // Lists render independently; restoring a project only depends on config and draft setup.
  window.__workspaceListsReady=Promise.allSettled([
    loadDramaProjects(false),
  ]);
  await Promise.allSettled([
    window.__workspaceListsReady,
    initPanel().finally(async()=>{
      initV2UX();
      await restoreLastView();
    }),
  ]);
  // The project endpoint reads large historical JSON files. Defer it until
  // the first paint; Works management loads it on demand if needed.
  if (window.requestIdleCallback) {
    window.requestIdleCallback(() => { if (!window.__projectsReady) window.__projectsReady=loadProjects(false).then(()=>window.__studioRefreshNav?.()); }, {timeout: 3000});
  } else {
    setTimeout(() => { if (!window.__projectsReady) window.__projectsReady=loadProjects(false).then(()=>window.__studioRefreshNav?.()); }, 1500);
  }
}
renderStages();initializeWorkspace();
// 首屏先完成工作区渲染，运行状态和队列延后加载，避免网络探测阻塞交互。
setTimeout(refreshStatus,1200);setTimeout(refreshRenderQueue,1200);
// 队列快照会逐个读取项目文件，避免高频轮询拖慢主工作区。
setInterval(refreshStatus,30000);setInterval(refreshRenderQueue,10000);
