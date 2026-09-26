/* Production workspace shell: reuse existing controls, endpoints and permissions. */
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id),
    grid = document.querySelector(".workspace-grid"),
    main = grid.querySelector("main"),
    left = grid.querySelector(".left"),
    right = grid.querySelector(".right");
  right.id = "studio-runtime-panel";
  right.setAttribute("aria-label", "运行面板");
  right.tabIndex = 0;
  if (window.matchMedia("(max-width: 950px)").matches)
    grid.classList.add("studio-monitor-hidden");
  const isAdmin = window.PLATFORM?.user?.role === "admin";
  const isMember =
    !!window.PLATFORM?.user && window.PLATFORM.user.role !== "admin";
  const state = { series: "", page: "studio", stage: 0, works: "series" };
  const button = (label, action) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.onclick = action;
    return b;
  };
  const originalHeader = document.querySelector("body>header");
  originalHeader.classList.add("studio-legacy-header");
  const workspace = document.createElement("div");
  workspace.className = "studio-workspace";
  grid.insertBefore(workspace, main);
  workspace.append(main);
  const top = document.createElement("header");
  top.className = "studio-top";
  workspace.prepend(top);
  const crumbWrap = document.createElement("div");
  crumbWrap.className = "studio-heading";
  const crumbs = document.createElement("div");
  crumbs.className = "studio-crumb";
  const currentTitle = document.createElement("h1");
  currentTitle.className = "studio-current-title";
  currentTitle.textContent = "新作品";
  crumbWrap.append(crumbs, currentTitle);
  top.append(crumbWrap);
  const topActions = document.createElement("div");
  topActions.className = "studio-top-actions";
  top.append(topActions);
  const status =
    originalHeader.querySelector("#dot-llm")?.parentElement?.parentElement;
  if (status) topActions.append(status);
  const monitorToggle = button("运行面板", () => {
    grid.classList.toggle("studio-monitor-hidden");
    monitorToggle.setAttribute("aria-expanded", String(!grid.classList.contains("studio-monitor-hidden")));
  });
  monitorToggle.setAttribute("aria-controls", right.id);
  monitorToggle.setAttribute("aria-expanded", String(!grid.classList.contains("studio-monitor-hidden")));
  topActions.append(
    button("任务", () => selectPage("tasks")),
    monitorToggle,
  );
  if (!isAdmin) {
    const toolsNav = document.createElement("nav");
    toolsNav.className = "studio-header-tools";
    toolsNav.setAttribute("aria-label", "素材与制作");
    toolsNav.append(
      button("小说与改编", () => selectPage("library")),
      button("番茄下载", () => openTomatoDownloader()),
      button("单镜生成器", () => selectPage("single")),
      button("节点管理", () => selectPage("nodes")),
      (() => { const b = button("⚙️", () => selectPage("settings")); b.title = "系统设置"; b.setAttribute("aria-label", "系统设置"); b.classList.add("icon-only-nav"); return b; })(),
      (() => { const b = button("👤", () => selectPage("account")); b.title = "我的账号"; b.setAttribute("aria-label", "我的账号"); b.classList.add("icon-only-nav"); return b; })(),
      button("功能全览", () => selectPage("map")),
    );
    if (!isMember) toolsNav.append(button("Skills", () => selectPage("skills")));
    top.append(toolsNav);
  }
  const user = byId("team-current-user");
  if (user) topActions.append(user);
  const stages = document.createElement("nav");
  stages.className = "studio-stage-tabs";
  stages.setAttribute("aria-label", "制作阶段");
  // Keep the current work and its resume action beside the production steps.
  const productionBar = document.createElement("div");
  productionBar.className = "studio-production-bar";
  const workContext = document.createElement("div");
  workContext.className = "studio-work-context";
  const projectActions = document.createElement("div");
  projectActions.id = "studio-project-actions";
  workContext.append(crumbWrap, projectActions);
  productionBar.append(stages, workContext);
  top.append(productionBar);
  const sections = [
    main.querySelector("section"),
    byId("script-box"),
    byId("shots-box"),
    byId("final-box"),
  ];
  sections[0].id = "studio-story";
  const stageNames = [
    "故事与剧本",
    "角色与素材",
    "分镜制作",
    "成片导出",
  ];
  stageNames.forEach((n, i) =>
    stages.append(button(i + 1 + " " + n, () => setStageView(i))),
  );
  const empty = document.createElement("div");
  empty.className = "studio-empty";
  main.append(empty);
  const storySources = document.createElement('div');
  storySources.className = 'studio-story-sources';
  storySources.append(button('从小说导入', () => { inspiration.hidden = true; selectPage('library'); }));
  const importRow = byId('script-import-row');
  const importInput = byId('script-import-file');
  const importButton = importRow?.querySelector('button');
  const importStatus = byId('script-import-status');
  const importClear = byId('script-import-clear');
  if (importButton) {
    importButton.className = 'glass';
    importButton.textContent = '导入完整剧本';
    storySources.append(importButton);
    if (importStatus) {
      importButton.title = importStatus.textContent.trim();
      importStatus.hidden = true;
    }
    if (importClear) storySources.append(importClear);
    importRow?.remove();
  }
  byId('idea').before(storySources);
  const inspiration = document.createElement('section');
  inspiration.id = 'image-inspiration';
  inspiration.hidden = false;
  inspiration.innerHTML = `<div class="image-dropzone"><input id="inspiration-file" aria-label="选择图片" type="file" accept="image/jpeg,image/png,image/webp" hidden><img id="inspiration-preview" alt="图片预览" hidden><button id="inspiration-import" type="button">＋ 导入图片</button><button id="inspiration-remove" type="button" hidden>移除</button></div><div class="image-box-actions"><label><input id="inspiration-atmosphere" type="checkbox"> 用作氛围参考</label><button id="inspiration-analyze" type="button">分析图片</button></div><details><summary>补充创作方向</summary><textarea id="inspiration-direction" aria-label="图片创作方向" rows="2" placeholder="希望从图片中构思怎样的故事？（可选）"></textarea></details><p id="inspiration-status" role="status"></p><textarea id="inspiration-result" aria-label="图片灵感剧本草稿" rows="8" hidden></textarea><button id="inspiration-apply" type="button" hidden>采用这份草稿</button>`;
  const intake = document.createElement('div');
  intake.className = 'story-intake-layout';
  storySources.after(intake);
  const writing = document.createElement('div');
  writing.className = 'story-writing-pane';
  const writingLabel = document.createElement('label');
  writingLabel.htmlFor = 'idea';
  writingLabel.textContent = '故事正文';
  writing.append(writingLabel, byId('idea'));
  intake.append(writing, inspiration);
  const imageFrame = document.createElement('div');
  imageFrame.className = 'story-image-frame';
  inspiration.prepend(imageFrame);
  imageFrame.append(inspiration.querySelector('.image-dropzone'), inspiration.querySelector('.image-box-actions'), inspiration.querySelector('details'));

  // Three peer cards, each with an independent collapsible body.
  const storyRoot = sections[0];
  const directorCard = storyRoot.querySelector('.story-director');
  const inputCard = document.createElement('section');
  inputCard.className = 'story-step-card story-input-card';
  const inputTitle = storyRoot.querySelector('h2');
  const inputBody = document.createElement('div');
  inputBody.id = 'story-input-body';
  for (const child of Array.from(storyRoot.children)) {
    if (child === directorCard) break;
    if (child !== inputTitle) inputBody.append(child);
  }
  function stepHeader(title, body, id) {
    const header = document.createElement('div');
    header.className = 'story-step-heading';
    const toggle = button('收起', () => {
      body.hidden = !body.hidden;
      toggle.textContent = body.hidden ? '展开' : '收起';
      toggle.setAttribute('aria-expanded', String(!body.hidden));
    });
    toggle.id = id;
    toggle.setAttribute('aria-controls', body.id);
    toggle.setAttribute('aria-expanded', 'true');
    header.append(title, toggle);
    return header;
  }
  inputCard.append(stepHeader(inputTitle, inputBody, 'story-input-toggle'), inputBody);
  storyRoot.prepend(inputCard);
  directorCard.classList.add('story-step-card');
  directorCard.firstElementChild.classList.add('story-step-heading');
  const directorTitle = directorCard.firstElementChild.firstElementChild;
  directorTitle.classList.add('story-step-title');
  const directorToggle = byId('director-toggle');
  directorToggle.setAttribute('aria-controls', 'director-body');
  const syncDirectorExpanded = () => directorToggle.setAttribute('aria-expanded', String(!byId('director-body').classList.contains('hidden')));
  new MutationObserver(syncDirectorExpanded).observe(byId('director-body'), {attributes:true, attributeFilter:['class']});
  syncDirectorExpanded();
  const outputCard = storyRoot.querySelector('.story-output');
  outputCard.classList.add('story-step-card');
  const outputTitle = outputCard.querySelector('h3');
  const outputBody = document.createElement('div');
  outputBody.id = 'story-output-body';
  Array.from(outputCard.children).filter(child => child !== outputTitle).forEach(child => outputBody.append(child));
  outputCard.append(stepHeader(outputTitle, outputBody, 'story-output-toggle'), outputBody);

  if (isMember) byId('novel-ai-status').closest('.border-t').hidden = true;
  let inspirationUrl = null, inspirationVersion = 0, inspirationReference = null;
  byId('inspiration-file').onchange = () => {
    const selected=byId('inspiration-file').files[0];
    if(selected && (selected.size>10*1024*1024 || !['image/jpeg','image/png','image/webp'].includes(selected.type))){byId('inspiration-status').textContent='请选择 10 MB 以内的 JPG、PNG 或 WebP 图片';byId('inspiration-file').value='';return;}
    inspirationVersion++;inspirationReference=null;
    if (inspirationUrl) URL.revokeObjectURL(inspirationUrl);
    const file = byId('inspiration-file').files[0];
    byId('inspiration-preview').hidden = !file;
    if (file) { inspirationUrl = URL.createObjectURL(file); byId('inspiration-preview').src = inspirationUrl; }
    byId('inspiration-result').hidden = true;
    byId('inspiration-apply').hidden = true;
    byId('inspiration-status').textContent = '';
    byId('inspiration-import').textContent = file ? '更换图片' : '＋ 导入图片';
    byId('inspiration-remove').hidden = !file;
    if (file && byId('inspiration-atmosphere').checked) uploadInspirationAsReference(file);
  };
  async function uploadInspirationAsReference(file) {
    const status=byId('inspiration-status');
    if(file.size>10*1024*1024){status.textContent='图片不能超过 10 MB';return;}
    const version=inspirationVersion, pid=currentPid;
    try { const data=new FormData();data.append('image',file); const response=await fetch('/api/generation-reference',{method:'POST',body:data}); const result=await response.json(); if(!response.ok||!result.ok)throw new Error(result.msg||'参考图上传失败'); if(version!==inspirationVersion||pid!==currentPid||!byId('inspiration-atmosphere').checked)return; inspirationReference=result.reference; await persistGenerationReference(result.reference); status.textContent='图片已选，将同时作为参考图使用'; }
    catch(error){ status.textContent=error.message; }
  }
  byId('inspiration-analyze').onclick = async () => {
    let file = byId('inspiration-file').files[0];
    if(!file && inspirationReference?.url){try{const response=await fetch(inspirationReference.url);if(!response.ok)throw new Error();file=new File([await response.blob()],'reference.png',{type:'image/png'});}catch(_){byId('inspiration-status').textContent='图片读取失败，请重新导入';return;}}
    const status = byId('inspiration-status');
    if (!file) { status.textContent = '请先选择一张图片'; return; }
    if (file.size > 10*1024*1024) { status.textContent = '图片不能超过 10 MB'; return; }
    const version = inspirationVersion, draft = byId('inspiration-direction').value;
    const data = new FormData();data.append('image',file);data.append('idea',draft);
    byId('inspiration-analyze').disabled = true;status.textContent = 'AI 正在分析图片并构思剧本…';
    try {
      const response = await fetch('/api/story/image-inspiration',{method:'POST',body:data});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.msg || '图片分析失败');
      if (version !== inspirationVersion) return;
      inspirationReference=result.reference||null;
      byId('inspiration-result').value = result.story;
      byId('inspiration-result').hidden = false;byId('inspiration-apply').hidden = false;
      status.textContent = '草稿已生成，可编辑后采用。';
    } catch (error) { if(version === inspirationVersion)status.textContent = error.message; }
    finally { byId('inspiration-analyze').disabled = false; }
  };
  byId('inspiration-apply').onclick = async () => {
    const draft = byId('inspiration-result').value.trim();if (!draft) return;
    if (byId('idea').value.trim() && !confirm('用图片灵感草稿替换当前故事内容？')) return;
    byId('idea').value = typeof normalizeStoryText==='function' ? normalizeStoryText(draft) : draft;updateIdeaCount();queueDraftSave();invalidateDirectorMatch(true);
    byId('idea').focus();
  };
  const originalNovelImport = sendCurrentNovelChapterToStory;
  sendCurrentNovelChapterToStory = function() {
    if (!NOVEL_CURRENT || !NOVEL_CHAPTER_INDEX) return originalNovelImport();
    if(byId('idea').value.trim()&&!confirm('用小说章节替换当前故事内容？'))return;
    inspiration.hidden = true;
    originalNovelImport();selectPage('studio',false);setStageView(0);
  };
  async function persistGenerationReference(reference) {
    if(generationReferenceBusy)throw new Error('参考图正在保存，请稍后重试');
    if(es)throw new Error('请等待当前生成完成后更换参考图');
    generationReferenceBusy=true;
    try {
      if(currentPid){
        const response=await fetch(`/api/project/${encodeURIComponent(currentPid)}/generation-reference`,{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reference_id:reference?.id||''})});
        const result=await response.json();
        if(!response.ok||!result.ok)throw new Error(result.msg||'保存参考图失败');
      }
      setGenerationReference(reference);queueDraftSave();
    } finally {generationReferenceBusy=false;}
  }
  function generationReferencePanel(suffix) {
    const box=document.createElement('section');
    box.className='generation-reference-panel';
    box.innerHTML=`<h3>参考图片 <small>可选</small></h3><p>上传图片，指导角色、场景与道具生成。</p><details><summary>参考图使用说明</summary><p>不上传则按文字生成。采用图片灵感草稿后会自动使用原图；更换仅影响后续生成，已有资产可单张重新生成。</p></details><input id="generation-reference-file-${suffix}" aria-label="上传生图参考图" type="file" accept="image/jpeg,image/png,image/webp"><img alt="当前生图参考图" hidden style="max-width:260px;max-height:160px;object-fit:contain;margin:8px 0"><button type="button" hidden>移除参考图，使用文生图</button><p role="status"></p>`;
    const file=box.querySelector('input'),preview=box.querySelector('img'),remove=box.querySelector('button'),status=box.querySelector('[role=status]');
    function render(){
      preview.hidden=!generationReference?.url;
      if(generationReference?.url)preview.src=generationReference.url;else preview.removeAttribute('src');
      remove.hidden=!generationReference;
      status.textContent=generationReference?.missing?'原参考图已缺失，请重新上传':generationReference?'已选参考图，将使用参考图生图':'未选参考图，将使用文生图';
    }
    window.addEventListener('generation-reference-change',render);render();
    file.onchange=async()=>{
      const image=file.files[0];if(!image)return;
      if(es||generationReferenceBusy){status.textContent='请等待当前生成或上传完成后再更换';file.value='';return;}
      if(image.size>10*1024*1024){status.textContent='图片不能超过 10 MB';file.value='';return;}
      file.disabled=true;generationReferenceBusy=true;status.textContent='正在上传参考图…';
      const startingPid=currentPid;
      try{
        const data=new FormData();data.append('image',image);
        const response=await fetch('/api/generation-reference',{method:'POST',body:data});
        const result=await response.json();
        if(!response.ok||!result.ok)throw new Error(result.msg||'上传失败');
        if(currentPid!==startingPid)throw new Error('项目已切换，请在当前项目重新选择参考图');
        generationReferenceBusy=false;
        await persistGenerationReference(result.reference);
      }catch(error){status.textContent=error.message;}
      finally{file.disabled=false;file.value='';generationReferenceBusy=false;}
    };
    remove.onclick=async()=>{try{await persistGenerationReference(null);}catch(error){status.textContent=error.message;}};
    return box;
  }
  function enableImageDrop(target,input){
    if(!target||!input||target.dataset.dropReady)return;
    target.dataset.dropReady='1';
    ['dragenter','dragover'].forEach(type=>target.addEventListener(type,e=>{e.preventDefault();target.classList.add('is-dragover');}));
    ['dragleave','drop'].forEach(type=>target.addEventListener(type,e=>{e.preventDefault();target.classList.remove('is-dragover');}));
    target.addEventListener('drop',e=>{const file=[...(e.dataTransfer?.files||[])].find(f=>f.type.startsWith('image/'));if(!file)return;try{const dt=new DataTransfer();dt.items.add(file);input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));}catch(_){}});
  }
  enableImageDrop(byId('inspiration-file').closest('.image-dropzone'),byId('inspiration-file'));
  byId('inspiration-import').onclick=()=>byId('inspiration-file').click();
  byId('inspiration-atmosphere').onchange=async()=>{
    try{
      if(!byId('inspiration-atmosphere').checked)await persistGenerationReference(null);
      else if(inspirationReference)await persistGenerationReference(inspirationReference);
      else if(byId('inspiration-file').files[0])await uploadInspirationAsReference(byId('inspiration-file').files[0]);
      else {byId('inspiration-atmosphere').checked=false;byId('inspiration-status').textContent='请先导入图片';}
    }catch(error){byId('inspiration-atmosphere').checked=!!generationReference;byId('inspiration-status').textContent=error.message;}
  };
  byId('inspiration-remove').onclick=async()=>{
    try{await persistGenerationReference(null);}catch(error){byId('inspiration-status').textContent=error.message;return;}
    byId('inspiration-file').value='';byId('inspiration-file').onchange();
    byId('inspiration-atmosphere').checked=false;
  };
  window.addEventListener('generation-reference-change',()=>{
    byId('inspiration-atmosphere').checked=!!generationReference;
    if(generationReference?.url){
      inspirationReference=generationReference;inspiration.hidden=false;
      byId('inspiration-preview').src=generationReference.url;byId('inspiration-preview').hidden=false;
      byId('inspiration-remove').hidden=false;byId('inspiration-import').textContent='更换图片';
    }
  });
  // Keep asset controls visible even when the story form is hidden.
  const assetControls = document.createElement("section");
  assetControls.id = "studio-asset-controls";
  assetControls.className = "studio-asset-actions";
  // Keep the original setting in the story form for existing project state.
  byId("customAssets").closest("label").hidden = true;
  const assetAction = button("生成资产", () => {
    const target = assetTarget();
    if (target) {
      target.click();
    } else if (currentPid && SCRIPT_DATA && !es) {
      // A loaded project with an uploaded inspiration image should continue
      // generating missing AI assets. The custom-assets gate is only for the
      // explicit upload-and-confirm workflow, which has its own confirmation
      // button; otherwise it traps the user on this button forever.
      const custom = byId("customAssets");
      if (custom && custom.checked) custom.checked = false;
      continueProject(currentPid);
    }
    refreshAssetControls();
  });
  assetAction.id = "studio-generate-assets";
  assetAction.className = "btn-gold px-5 py-2";
  assetControls.append(assetAction);
  main.prepend(assetControls);
  function assetTarget() {
    return (
      byId("script-confirm-btn") ||
      byId("assets-continue-btn") ||
      byId("btn-assets-continue")
    );
  }
  function refreshAssetControls() {
    const target = assetTarget();
    // Stage confirmation belongs only to the footer; retain generation/retry actions.
    assetAction.hidden = target?.id === "btn-assets-continue";
    const label = es ? "生成中…" : "生成资产";
    if (assetAction.textContent !== label) assetAction.textContent = label;
    assetAction.disabled = target ? target.disabled : !currentPid || !SCRIPT_DATA || !!es;
    assetAction.title = !SCRIPT_DATA ? "请先在故事与剧本中生成剧本" : "生成角色、场景与道具素材";
  }
  new MutationObserver(refreshAssetControls).observe(main, {
    childList: true,
    subtree: true,
  });
  new MutationObserver(refreshAssetControls).observe(projectActions, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["disabled"],
  });
  // One explicit transition for each production stage.
  const stepFooter = document.createElement("section");
  stepFooter.className = "studio-step-footer";
  const stepHint = document.createElement("p");
  const stepNext = button("确认并进入下一步", async () => {
    const i = state.stage;
    const target =
      i === 0
        ? byId("script-confirm-btn")
        : i === 1
          ? byId("btn-assets-continue")
          : byId("btn-shots-continue");
    if (i === 2) {
      if (!allShotVideosPresent()) return;
      // Always use the dedicated resynthesis stream here. This also works for
      // projects that already have a final video and therefore have no inner
      // shot-confirm button or waiting SSE task left to resume.
      if (typeof startDirectResynth === "function") startDirectResynth();
      refreshStepFooter();
      return;
    }
    if (!target || target.disabled) return;
    if (i === 0) await confirmScriptAndContinue();
    else if (i === 1) await confirmAssetsBatch();
    else await confirmShotsBatch();
    // Shot confirmation starts synthesis asynchronously. Keep the shot review
    // section visible while the final video is being produced; switching to the
    // empty final stage here makes the workspace look frozen.
    if (!document.contains(target) && i !== 2) setStageView(i + 1);
    refreshStepFooter();
  });
  stepNext.id = "studio-step-next";
  stepNext.className = "btn-gold px-5 py-3";
  stepFooter.append(stepHint, stepNext);
  main.append(stepFooter);
  function allShotVideosPresent() {
    const shots = SCRIPT_DATA?.shots || [];
    return shots.length > 0 && shots.every(s => !!SHOT_DATA[s.index]?.video_url);
  }
  function refreshStepFooter() {
    refreshStageAvailability();
    const i = state.stage;
    const ready = allShotVideosPresent();
    const target =
      i === 0
        ? byId("script-confirm-btn")
        : i === 1
          ? byId("btn-assets-continue")
          : byId("btn-shots-continue");
    stepFooter.hidden = i === 3;
    stepNext.disabled = i === 2 ? !ready : !target || target.disabled;
    const names = [
      "确认剧本，进入角色与素材",
      "确认素材，进入分镜制作",
      "确认分镜与审片，进入成片导出",
    ];
    const text = names[i] || "制作完成";
    if (stepNext.textContent !== text) stepNext.textContent = text;
    const hint = stepNext.disabled
      ? [
          "请先生成并查阅剧本。",
          "请等待参考图生成完成，检查角色、场景和道具。",
          "请完成全部镜头并逐镜检查；尚未进入待审片状态时，请先继续制作。",
        ][i]
      : "检查完成后点击确认，再进入下一步。";
    if (stepHint.textContent !== hint) stepHint.textContent = hint || "";
  }
  new MutationObserver(refreshStepFooter).observe(main, {
    childList: true,
    subtree: true,
  });
  // Studio creation always uses manual stage gates; queue automation is separate.
  byId("manualMode").checked = true;
  byId("manualMode").disabled = true;
  const originalRunPipeline = runPipeline;
  runPipeline = function (...args) {
    byId("manualMode").checked = true;
    return originalRunPipeline(...args);
  };
  const originalShotsReady = showShotsConfirmBar;
  showShotsConfirmBar = function (data) {
    originalShotsReady(data);
    refreshStepFooter();
  };
  const dock = document.createElement("div");
  dock.className = "studio-dock";
  workspace.append(dock);
  const pages = {
    "project-settings": "series-modal",
    projects: "drama-modal",
    history: "proj-modal",
    episodes: "episode-manager-modal",
    library: "novel-viewer-modal",
    single: "single-modal",
    skills: "skills-modal",
    settings: "settings-modal",
    nodes: "nodes-modal",
  };
  const pageNodes = {};
  for (const [name, id] of Object.entries(pages)) {
    const node = byId(id);
    pageNodes[name] = node;
    node.classList.add("studio-page");
    dock.append(node);
    new MutationObserver((records) => {
      const wasHidden = (records[0].oldValue || '').split(' ').includes('hidden');
      if (wasHidden === node.classList.contains('hidden')) return;
      if (!node.classList.contains("hidden") && state.page !== name)
        selectPage(name, false);
      else if (node.classList.contains("hidden") && state.page === name)
        selectPage("studio", false);
    }).observe(node, { attributes: true, attributeFilter: ["class"], attributeOldValue: true });
  }
  // Keep the actual queue, progress, cancellation and log controls alive.
  const queue = byId("render-queue-list").closest(".workspace-panel");
  right.prepend(queue);
  queue.classList.add("studio-queue");
  const monitorHead = document.createElement("div");
  monitorHead.className = "studio-monitor-title";
  const mh = document.createElement("h2");
  mh.textContent = "运行面板";
  monitorHead.append(
    mh,
    button("收起", () => {
      grid.classList.add("studio-monitor-hidden");
      monitorToggle.setAttribute("aria-expanded", "false");
      monitorToggle.focus({ preventScroll: true });
    }),
  );
  right.prepend(monitorHead);
  const progress = document.createElement("section");
  progress.className = "studio-monitor-section";
  right.insertBefore(progress, queue);
  const errors = document.createElement("section");
  errors.className = "studio-monitor-section";
  right.insertBefore(errors, queue);
  const logsTitle = document.createElement("h3");
  logsTitle.textContent = "制作阶段与运行日志";
  byId("pipeline-box").prepend(logsTitle);
  const worksBar = document.createElement("div");
  worksBar.className = "studio-works-tabs";
  worksBar.append(
    button("连续剧", () => selectPage("projects")),
    button("独立短片", () => selectPage("history")),
    button("新建独立短片", () => newProject()),
    button("新建连续剧", async () => {
      selectPage("projects", false);
      await loadDramaProjects(true);
      toggleDramaCreate(true);
    }),
  );
  dock.prepend(worksBar);
  left.replaceChildren();
  const brand = document.createElement("div");
  brand.className = "studio-brand";
  brand.textContent = "智创";
  left.append(brand);
  const nav = document.createElement("nav");
  nav.className = "studio-navigation";
  nav.setAttribute("aria-label", "项目与工具");
  left.append(nav);
  function currentSeries() {
    return DRAMA_PROJECT_LIST.find((s) => s.id === state.series);
  }
  function navGroup(label) {
    const h = document.createElement("div");
    h.className = "studio-nav-label";
    h.textContent = label;
    nav.append(h);
  }
  function navButton(label, page, fn) {
    const b = button(label, fn || (() => selectPage(page)));
    b.className = "studio-nav-button";
    b.dataset.page = page;
    if (state.page === page) b.setAttribute("aria-current", "page");
    nav.append(b);
    return b;
  }
  let navRenderPending = false;
  function renderNav() {
    if (navRenderPending) return;
    navRenderPending = true;
    queueMicrotask(() => { navRenderPending = false; renderNavNow(); });
  }
  window.__studioRefreshNav = renderNav;
  function renderNavNow() {
    const activeSeries = DRAMA_PROJECT_LIST.find(series => Object.values(series.episodes || {}).some(episode =>
      String(episode.project_id || '') === String(currentPid || '-') || (episode.versions || []).some(version => String(version.project_id) === String(currentPid))));
    if (currentPid) state.series = activeSeries?.id || 'short';
    nav.replaceChildren();
    if (!isAdmin) navButton("新建作品", "new-work", () => newProject());
    navButton("作品管理", "works");
    if (isAdmin) {
      navGroup("作品与任务管理");
      navButton("全部连续剧", "projects");
      navButton("全部短片", "history");
      navButton("剧集管理", "episodes");
      navButton("任务管理", "tasks");
      navGroup("系统管理");
      navButton("小说管理", "library");
      navButton("Skills 管理", "skills");
      navButton("节点管理", "nodes");
      navButton("系统设置", "settings");
      navButton("团队管理", "team", () => location.assign('/team'));
      navButton("我的账号", "account");
      updateCrumbs();
      return;
    }
    const workTools = document.createElement("div");
    workTools.className = "studio-work-tools";
    const workSearch = document.createElement("input");
    workSearch.type = "search";
    workSearch.placeholder = "搜索作品";
    workSearch.setAttribute("aria-label", "搜索作品");
    workSearch.className = "studio-work-search";
    const workFilter = document.createElement("select");
    workFilter.setAttribute("aria-label", "筛选作品状态");
    [["all", "全部状态"], ["active", "制作中"], ["error", "需要处理"], ["done", "已完成"]].forEach(([value, label]) => workFilter.append(new Option(label, value)));
    workFilter.className = "studio-work-filter";
    workTools.append(workSearch, workFilter);
    nav.append(workTools);
    const allWorks = document.createElement("div");
    allWorks.className = "studio-all-works";
    allWorks.setAttribute("aria-label", "全部作品列表");
    const workItems = [];
    for (const work of DRAMA_PROJECT_LIST) {
      const episodes = Object.values(work.episodes || {});
      const failed = episodes.reduce((n, e) => n + Number(e.failed_shots || 0), 0);
      const done = Number(work.final_count || episodes.filter(e => e.has_final).length);
      const total = Number(work.episode_count || episodes.length);
      workItems.push({ type: "series", work, failed, done, total });
    }
    for (const work of PROJECT_LIST.filter(work => !work.series)) {
      workItems.push({ type: "short", work, failed: Number(work.failed_shots || 0), done: work.final ? 1 : 0, total: 1 });
    }
    function renameIcon(label, rename) {
      const icon = document.createElement('button');
      icon.type = 'button';
      icon.className = 'studio-work-rename';
      icon.title = '重命名';
      icon.setAttribute('aria-label', `重命名：${label}`);
      icon.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6Z M13 6l5 5"/></svg>';
      icon.onkeydown = event => event.stopPropagation();
      icon.onclick = async event => {
        event.preventDefault();event.stopPropagation();icon.disabled=true;
        try {
          await rename();
          await Promise.all([loadDramaProjects(false), loadProjects(false)]);
          renderNav();
        } catch(error) { alert('刷新作品失败：'+error.message); }
        finally { icon.disabled=false; }
      };
      return icon;
    }
    const renderWorks = () => {
      const expanded = new Set(Array.from(allWorks.querySelectorAll('details[open]')).map(el => el.dataset.workKey));
      allWorks.replaceChildren();
      const query = workSearch.value.trim().toLowerCase();
      const filter = workFilter.value;
      const filtered = workItems.filter(item => {
        const work = item.work;
        const episodeText = Object.values(work.episodes || {}).map(e => `${e.title || ""} ${e.idea || ""}`).join(" ");
        const title = `${work.name || ""} ${work.title || ""} ${work.id || ""} ${episodeText}`.toLowerCase();
        const status = item.failed ? "error" : item.done >= item.total && item.total > 0 ? "done" : item.total ? "active" : "empty";
        return (!query || title.includes(query)) && (filter === "all" || status === filter);
      }).sort((a, b) => {
        const rank = item => item.failed ? 0 : item.done >= item.total && item.total > 0 ? 2 : 1;
        return rank(a) - rank(b) || Number(b.work.updated || b.work.created || 0) - Number(a.work.updated || a.work.created || 0);
      });
      const groups = [
        ["连续剧", filtered.filter(item => item.type === "series")],
        ["独立短片", filtered.filter(item => item.type === "short")],
      ];
      for (const [groupName, groupItems] of groups) {
        if (!groupItems.length) continue;
        const heading = document.createElement("div");
        heading.className = "studio-work-group-title";
        const group = document.createElement('section');
        group.className = 'studio-work-group';
        const headingLabel = document.createElement('span');
        headingLabel.textContent = `${groupName} · ${groupItems.length}`;
        heading.append(headingLabel);
        const addGroup = document.createElement('button');
        addGroup.type = 'button';
        addGroup.className = 'studio-group-add';
        addGroup.textContent = '＋';
        addGroup.title = groupName === '连续剧' ? '新建连续剧' : '新建独立短片';
        addGroup.setAttribute('aria-label', addGroup.title);
        addGroup.onclick = async event => {
          event.preventDefault(); event.stopPropagation();
          if (groupName === '连续剧') {
            selectPage('projects', false);
            await loadDramaProjects(true);
            toggleDramaCreate(true);
          } else {
            newProject();
          }
        };
        heading.append(addGroup);
        group.append(heading);
        allWorks.append(group);
        for (const item of groupItems) {
        const work = item.work;
        const row = item.type === "series" ? document.createElement("details") : document.createElement("div");
        if (item.type === "series") row.className = "studio-work-series";
        else row.className = "studio-work-short";
        const line = item.type === "series" ? document.createElement("summary") : row;
        line.className = "studio-work-line";
        if (item.type === "short") {
          line.onclick = () => openProject(work.id);
          line.tabIndex = 0;
          line.setAttribute('role', 'button');
          line.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); line.click(); } };
        } else {
          row.dataset.workKey = `series:${work.id}`;
          row.open = expanded.has(row.dataset.workKey) || state.series === work.id || !!query;
        }
        const title = document.createElement("span");
        const shortTitle = work.title && !["独立短片", "未命名短片", "项目"].includes(String(work.title).trim())
          ? work.title
          : (work.idea || `未命名短片 · ${String(work.id || "").slice(0, 8)}`);
        title.textContent = item.type === "series" ? (work.name || "未命名连续剧") : shortTitle;
        const meta = document.createElement("small");
        const status = item.failed ? "需要处理" : item.done >= item.total && item.total > 0 ? "已完成" : item.total ? "制作中" : "待制作";
        const stateClass = item.failed ? "error" : status === "已完成" ? "done" : status === "制作中" ? "active" : "empty";
        title.dataset.state = stateClass;
        const actions = document.createElement('span');
        actions.className = 'studio-work-line-actions';
        actions.append(renameIcon(title.textContent, () => item.type === 'series'
          ? renameSeriesFromList(encodeURIComponent(work.id))
          : renameProjectFromList(encodeURIComponent(work.id))));
        line.append(title, actions);
        if (item.type === 'series') {
          line.addEventListener('click', event => {
            if (event.target.closest('button')) return;
            event.preventDefault();
            row.open = !row.open;
          });
          const addEpisode = document.createElement('button');
          addEpisode.type = 'button';
          addEpisode.className = 'studio-work-add-episode';
          addEpisode.title = '新建续集';
          addEpisode.setAttribute('aria-label', `新建续集：${title.textContent}`);
          addEpisode.textContent = '＋';
          addEpisode.onclick = async event => {
            event.preventDefault(); event.stopPropagation();
            state.series = work.id;
            await openDramaProject(work.id);
            await newSeriesEpisode();
            await loadDramaProjects(false);
            renderNav();
          };
          actions.prepend(addEpisode);
        }
        if (item.type === "short" && String(currentPid) === String(work.id)) line.setAttribute("aria-current", "page");
        if (item.type === "series") row.append(line);
        line.title = title.textContent;
        group.append(row);
        if (item.type === "series") {
          const episodes = Object.values(work.episodes || {}).sort((a, b) => Number(a.episode || 0) - Number(b.episode || 0));
          const episodeList = document.createElement("div");
          episodeList.className = "studio-work-episodes";
          if (!episodes.length) {
            episodeList.textContent = "暂无分集";
          } else {
            for (const episode of episodes) {
              const episodeButton = button("", () => {
                state.series = work.id;
                if (episode.project_id) openProject(episode.project_id);
                else {
                  openDramaProject(work.id).then(() => {
                    const input = byId('series-new-episode');
                    if (input) { input.value = String(episode.episode || ''); input.focus(); }
                  });
                }
              });
              episodeButton.className = "studio-work-episode";
              const episodeTitle = document.createElement("span");
              episodeTitle.textContent = `第${episode.episode || "?"}集 · ${episode.title || "未命名"}`;
              const episodeMeta = document.createElement("small");
              const episodeState = episode.failed_shots ? "error" : episode.has_final ? "done" : episode.has_script ? "active" : "empty";
              episodeTitle.dataset.state = episodeState;
              episodeButton.append(episodeTitle);
              episodeButton.title = episodeTitle.textContent;
              if (currentPid === episode.project_id) episodeButton.setAttribute('aria-current', 'page');
              const episodeNode = document.createElement('div');
              episodeNode.className = 'studio-work-episode-node';
              const episodeLine = document.createElement('div');
              episodeLine.className = 'studio-work-editable';
              episodeLine.append(episodeButton, renameIcon(episodeTitle.textContent, () => renameSeriesEpisodeFromList(encodeURIComponent(work.id), episode.episode)));
              episodeNode.append(episodeLine);
              episodeList.append(episodeNode);
              const versions = (episode.versions || []).filter(v => v.project_id && String(v.project_id) !== String(episode.project_id));
              const versionList = document.createElement('details');
              versionList.className = 'studio-work-versions';
              versionList.dataset.workKey = `episode:${work.id}:${episode.episode}`;
              versionList.open = expanded.has(versionList.dataset.workKey) || versions.some(v => v.project_id === currentPid);
              const versionHeading = document.createElement('summary');
              versionHeading.textContent = `历史版本 · ${versions.length}`;
              versionList.append(versionHeading);
              if (versions.length) episodeNode.append(versionList);
              for (const version of versions) {
                const versionButton = button(`${version.title || '制作版本'}`, () => {
                  state.series = work.id;
                  openProject(version.project_id);
                });
                versionButton.className = "studio-work-episode studio-work-version";
                versionButton.title = version.title || '制作版本';
                if (currentPid === version.project_id) versionButton.setAttribute('aria-current', 'page');
                const versionLine = document.createElement('div');
                versionLine.className = 'studio-work-editable';
                versionLine.append(versionButton, renameIcon(versionButton.title, () => renameProjectFromList(encodeURIComponent(version.project_id))));
                versionList.append(versionLine);
              }
            }
          }
          row.append(episodeList);
        }
        }
      }
      if (!allWorks.children.length) {
        const emptyWorks = document.createElement("p");
        emptyWorks.textContent = query || filter !== "all" ? "没有符合条件的作品" : "暂无作品，点击下方新建独立短片开始";
        allWorks.append(emptyWorks);
      }
    };
    workSearch.oninput = renderWorks;
    workFilter.onchange = renderWorks;
    renderWorks();
    /* legacy rendering below is intentionally replaced by the unified list */
    /*
    for (const work of DRAMA_PROJECT_LIST) {
      const row = button("", () => {
        state.series = work.id;
        selectPage("episodes");
      });
      const title = document.createElement("span");
      title.textContent = work.name || "未命名连续剧";
      const meta = document.createElement("small");
      meta.textContent = `连续剧 · ${work.episode_count || Object.keys(work.episodes || {}).length} 集`;
      row.append(title, meta);
      if (state.series === work.id) row.setAttribute("aria-current", "page");
      allWorks.append(row);
    }
    for (const work of PROJECT_LIST.filter(work => !work.series)) {
      const row = button("", () => openProject(work.id));
      const title = document.createElement("span");
      title.textContent = work.title || "未命名短片";
      const meta = document.createElement("small");
      meta.textContent = `${work.series ? "剧集版本" : "独立短片"} · ${work.final ? "已有成片" : "制作中"}`;
      row.append(title, meta);
      if (currentPid === work.id) row.setAttribute("aria-current", "page");
      allWorks.append(row);
    }
    */
    if (!allWorks.children.length) {
      const emptyWorks = document.createElement("p");
      emptyWorks.textContent = "暂无作品，点击下方新建独立短片开始";
      allWorks.append(emptyWorks);
    }
    nav.append(allWorks);
    updateCrumbs();
  }
  function updateCrumbs() {
    const title = (byId("proj-title")?.textContent || "").trim();
    const projectLabel = byId("proj-title");
    const episode = (currentPid && projectLabel?.dataset.projectId === String(currentPid)
      ? projectLabel.dataset.episode : "") || PROJECT_LIST.find(p => p.id === currentPid)?.series?.episode;
    const fullTitle = title || (currentPid ? "当前作品" : "新作品");
    currentTitle.textContent = isAdmin ? "管理工作台" : episode ? `${fullTitle} · 第${episode}集` : fullTitle;
    currentTitle.title = currentTitle.textContent;
    crumbs.textContent =
      (currentSeries()?.name || "短剧制作") +
      " / " +
      (state.page === "studio"
        ? byId("proj-title").textContent || "新作品"
        : {
            "project-settings": "项目设置",
            projects: "我的作品",
            history: "作品记录",
            episodes: "剧集管理",
            tasks: "制作任务",
            nodes: "节点管理",
            settings: "系统设置",
            library: "小说与改编",
            single: "单镜生成器",
            skills: "Skills",
            map: "功能全览",
            account: "我的账号",
          }[state.page] || "");
    crumbs.hidden = state.page === "studio";
  }
  new MutationObserver(updateCrumbs).observe(byId("proj-title"), {
    childList: true,
    characterData: true,
    subtree: true,
  });
  const custom = document.createElement("section");
  custom.className = "studio-custom-page";
  dock.append(custom);
  const loaders = {
    projects: async () => {
      await Promise.all([
        loadDramaProjects(false),
        loadProjects(false),
      ]);
      renderNav();
      byId("drama-modal")?.classList.add("hidden");
      byId("proj-modal")?.classList.add("hidden");
    },
    history: () => loadProjects(true),
    episodes: async () => {
      await openEpisodeManager();
      if (state.series && state.series !== "short")
        await selectManagerSeries(state.series);
    },
    library: openNovelViewer,
    single: openSingle,
    skills: openSkillsManager,
    settings: openSettings,
    nodes: openNodeManager,
  };
  async function renderWorksManager() {
    custom.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = '作品管理';
    const toolbar = document.createElement('div');
    toolbar.className = 'works-manager-toolbar';
    const search = document.createElement('input');
    search.type = 'search'; search.placeholder = '搜索作品或剧集'; search.setAttribute('aria-label', '搜索管理作品');
    const type = document.createElement('select');
    type.setAttribute('aria-label', '作品类型');
    type.append(new Option('全部类型','all'),new Option('连续剧','series'),new Option('独立短片','short'));
    const filter = document.createElement('select');
    filter.setAttribute('aria-label', '作品状态');
    filter.append(new Option('全部状态','all'),new Option('制作中','active'),new Option('已完成','done'),new Option('需要处理','error'));
    const archiveView = document.createElement('select');
    archiveView.setAttribute('aria-label','归档状态');
    archiveView.append(new Option('使用中的作品','active'),new Option('已归档','archived'));
    const status = document.createElement('p');status.setAttribute('role','status');
    const selected = new Set();
    const selectedEpisodes = new Map();
    const batch = document.createElement('div'); batch.className='works-manager-batch';
    const selectedLabel=document.createElement('span'); selectedLabel.textContent='已选 0 项';
    const batchArchive=button('批量归档',async()=>{const ids=[...selected];if(!ids.length)return;for(const item of items.filter(x=>ids.includes(x.work.id))){await fetch(`/api/${item.kind==='series'?'series':'project'}/${encodeURIComponent(item.work.id)}/archive`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archived:true})});}selected.clear();await reload();});
    const batchDelete=button('批量删除',async()=>{const chosen=items.filter(x=>selected.has(x.work.id));if(!chosen.length||!confirm(`确定删除选中的 ${chosen.length} 项？此操作不可恢复。`))return;for(const item of chosen){await fetch(`/api/${item.kind==='series'?'series':'project'}/${encodeURIComponent(item.work.id)}/delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(item.kind==='series'?{delete_children:true}:{})});}selected.clear();await reload();});
    batch.append(selectedLabel,batchArchive,batchDelete);
    const list = document.createElement('div');list.className = 'works-manager-list';
    let items = [], busy = false;
    const refresh = button('刷新', reload);
    toolbar.append(search,type,filter,archiveView,refresh);
    custom.append(heading,toolbar,batch,status,list);
    function updateSelected(){selectedLabel.textContent=`已选 ${selected.size} 项`;batchArchive.disabled=batchDelete.disabled=!selected.size;}
    updateSelected();
    const stateOf = item => {
      const episodes = Object.values(item.work.episodes || {});
      if(item.work.failed_shots || episodes.some(e=>e.failed_shots))return 'error';
      if(item.kind==='short')return item.work.final ? 'done' : 'active';
      return episodes.length && episodes.every(e=>e.has_final) ? 'done' : 'active';
    };
    async function reload(force = false) {
      if(busy)return;
      busy=true;refresh.disabled=true;status.textContent='正在加载作品…';
      try{
        const suffix=archiveView.value==='archived'?'?archived=1':'';
        archiveView.disabled=true;
        let data;
        // The initial page load already fetches both lightweight lists. Reuse
        // those results when opening Works, instead of reading every project a
        // second time and making the page feel stuck.
        if(!force && archiveView.value==='active' && window.__workspaceListsReady){
          await window.__workspaceListsReady;
          if(window.__projectsReady) await window.__projectsReady;
          else {
            window.__projectsReady=loadProjects(false);
            await window.__projectsReady;
          }
          data=[DRAMA_PROJECT_LIST, PROJECT_LIST];
        }else{
          const responses=await Promise.all([fetch('/api/series'+suffix),fetch('/api/projects'+suffix)]);
          data=await Promise.all(responses.map(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.msg||'加载失败');return d;}));
        }
        if(!data.every(Array.isArray))throw new Error('作品列表格式错误');
        if(archiveView.value!=='archived'){DRAMA_PROJECT_LIST=data[0];PROJECT_LIST=data[1];}
        items=[...data[0].map(work=>({kind:'series',work})),...data[1].filter(w=>!w.series).map(work=>({kind:'short',work}))];
        renderNav();render();
      }catch(error){status.textContent=error.message;}finally{busy=false;refresh.disabled=false;archiveView.disabled=false;}
    }
    function render(){
      list.replaceChildren();
      const query=search.value.trim().toLowerCase();
      const visible=items.filter(item=>(type.value==='all'||type.value===item.kind)&&(filter.value==='all'||stateOf(item)===filter.value)&&[item.work.name,item.work.title,...Object.values(item.work.episodes||{}).map(e=>e.title)].join(' ').toLowerCase().includes(query));
      status.textContent=`共 ${items.length} 部作品，显示 ${visible.length} 部`;
      if(!visible.length){list.textContent='暂无符合条件的作品';return;}
      for(const item of visible){
        const {work,kind}=item;
        const card=document.createElement('article');card.className='works-manager-card';
        const check=document.createElement('input');check.type='checkbox';check.className='works-manager-select';check.checked=selected.has(work.id);check.setAttribute('aria-label',`选择${work.name||work.title||'作品'}`);check.onchange=()=>{check.checked?selected.add(work.id):selected.delete(work.id);updateSelected();};
        const info=document.createElement('div');info.className='works-manager-info';
        const title=document.createElement('h3');title.textContent=work.name||work.title||'未命名作品';
        const meta=document.createElement('p');meta.textContent=`${kind==='series'?'连续剧':'独立短片'} · ${{active:'制作中',done:'已完成',error:'需要处理'}[stateOf(item)]}`;
        info.append(title,meta);
        const actions=document.createElement('div');actions.className='works-manager-actions';
        actions.append(button('打开',()=>kind==='series'?openDramaProject(work.id):openProject(work.id)),button('重命名',async()=>{
          if(kind==='series')await renameSeriesFromList(encodeURIComponent(work.id));else await renameProjectFromList(encodeURIComponent(work.id));
          renderNav();render();
        }),button('删除',async()=>{
          if(!confirm(`删除《${title.textContent}》？${kind==='series'?'该剧关联的单集及输出视频也将删除。':'该作品及输出视频将删除。'}此操作不可恢复。`))return;
          actions.querySelectorAll('button').forEach(b=>b.disabled=true);
          try{
            const response=await fetch(`/api/${kind==='series'?'series':'project'}/${encodeURIComponent(work.id)}/delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(kind==='series'?{delete_children:true}:{})});
            const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.msg||'删除失败');
            await reload();
          }catch(error){status.textContent=error.message;}finally{actions.querySelectorAll('button').forEach(b=>b.disabled=false);}
        }));
        const archived = archiveView.value === 'archived';
        const archiveButton = button(archived ? '恢复' : '归档', async () => {
          archiveButton.disabled=true;
          archiveButton.textContent=archived?'恢复中…':'归档中…';
          status.textContent=archived?'正在恢复作品…':'正在归档作品…';
          try {
            const response=await fetch(`/api/${kind==='series'?'series':'project'}/${encodeURIComponent(work.id)}/archive`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archived:!archived})});
            const result=await response.json().catch(()=>({}));if(!response.ok||!result.ok)throw new Error(result.msg||`归档操作失败（${response.status}）`);
            await Promise.all([loadDramaProjects(false),loadProjects(false)]);
            renderNav();await reload();
          }catch(error){status.textContent=error.message;alert(error.message);}finally{archiveButton.disabled=false;archiveButton.textContent=archived?'恢复':'归档';}
        });
        actions.prepend(archiveButton);
        if(archived){
          // Restore before opening or editing; archived data stays outside active lists.
          Array.from(actions.children).filter(b=>['打开','重命名'].includes(b.textContent)).forEach(b=>b.remove());
          meta.textContent += ' · 已归档';
        }
        card.append(check,info,actions);
        if(kind==='series'){
          const episodes=Object.values(work.episodes||{}).sort((a,b)=>Number(a.episode||0)-Number(b.episode||0));
          const chosen=selectedEpisodes.get(work.id)||new Set();
          selectedEpisodes.set(work.id, chosen);
          const details=document.createElement('details');
          const summary=document.createElement('summary');
          summary.textContent=`剧集与批量操作 · ${episodes.length}`;
          details.append(summary);
          if(episodes.length && archiveView.value!=='archived'){
            const episodeBatch=document.createElement('div');
            episodeBatch.className='works-manager-episode-batch';
            const count=document.createElement('span');
            count.className='works-manager-episode-count';
            const updateCount=()=>{count.textContent=`已选 ${chosen.size} 集`;};
            updateCount();
            const selectFinished=button('全选成片',()=>{
              episodes.filter(ep=>ep.project_id&&ep.has_final).forEach(ep=>chosen.add(ep.project_id));
              render();
            });
            const queue=button('排队选中',async()=>{
              const ids=[...chosen];
              if(!ids.length){alert('请先选择要排队的集数');return;}
              await addProjectsToRenderQueue(ids);
              await refreshRenderQueue();
              render();
            });
            const merge=button('合并下载',async()=>{
              const ids=[...chosen];
              if(!ids.length){alert('请先选择要合并下载的集数');return;}
              await mergeSelectedEpisodes(work.id,ids,merge);
            });
            episodeBatch.append(count,selectFinished,queue,merge);
            details.append(episodeBatch);
            for(const episode of episodes){
              const row=document.createElement('div');row.className='works-manager-episode';
              const check=document.createElement('input');check.type='checkbox';check.className='works-manager-episode-select';check.checked=chosen.has(episode.project_id);check.disabled=!episode.project_id;
              check.setAttribute('aria-label',`选择第${episode.episode}集`);
              check.onchange=()=>{check.checked?chosen.add(episode.project_id):chosen.delete(episode.project_id);updateCount();};
              const label=document.createElement('span');label.textContent=`第 ${episode.episode} 集 · ${episode.title||'未命名'}`;
              const state=document.createElement('small');
              const episodeState=typeof managerEpisodeStatus==='function'?managerEpisodeStatus(episode):(episode.has_final?'finished':'unfinished');
              state.textContent={running:'生成中',queued:'队列中',finished:'已有成片',stale:'需重新合成',error:'失败',unfinished:'未完成'}[episodeState]||episodeState;
              state.className='works-manager-episode-state '+(episodeState==='finished'?'is-done':episodeState==='error'?'is-error':'');
              const info=document.createElement('div');info.className='works-manager-episode-info';info.append(label,state);
              row.append(check,info);
              const episodePreview = episode.final || episode.previous_final;
              if (episodePreview) {
                const preview = document.createElement('video');
                preview.className = 'works-manager-episode-preview';
                preview.src = episodePreview;
                preview.controls = true;
                preview.muted = true;
                preview.playsInline = true;
                preview.preload = 'metadata';
                preview.setAttribute('aria-label', `第 ${episode.episode} 集视频预览`);
                row.append(preview);
                const download = document.createElement('a');
                download.className = 'works-manager-episode-download';
                download.href = episodePreview;
                download.download = '';
                download.textContent = '下载';
                download.setAttribute('aria-label', `下载第 ${episode.episode} 集`);
                row.append(download);
              }
              if(episode.project_id)row.append(button('打开',()=>openProject(episode.project_id)));
              details.append(row);
            }
          }
          card.append(details);
        }
        list.append(card);
      }
    }
    search.oninput=render;type.onchange=render;filter.onchange=render;archiveView.onchange=reload;
    await reload();
  }
  async function mergeSelectedEpisodes(seriesId, ids, buttonEl) {
    const original = buttonEl?.textContent || '合并下载';
    if (buttonEl) { buttonEl.disabled = true; buttonEl.textContent = '准备合并…'; }
    try {
      const response = await fetch(`/api/series/${encodeURIComponent(seriesId)}/merge-download`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_ids: ids}),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.msg || result.error || '无法创建合并任务');
      for (;;) {
        const poll = await fetch(`/api/episode-exports/${result.job_id}`);
        const job = await poll.json();
        if (!poll.ok || !job.ok || job.status === 'error') throw new Error(job.msg || '合并失败');
        if (buttonEl) buttonEl.textContent = `${job.msg || '合并中'} ${job.progress}%`;
        if (job.status === 'done') {
          const link = document.createElement('a');
          link.href = `/api/episode-exports/${result.job_id}/download`;
          link.download = ''; document.body.appendChild(link); link.click(); link.remove();
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch (error) { alert(error.message || '合并下载失败'); }
    finally { if (buttonEl) { buttonEl.disabled = false; buttonEl.textContent = original; } }
  }
  function selectPage(name, load = true) {
    if (name === "tomato-download") {
      openTomatoDownloader();
      return;
    }
    if (isAdmin && ['studio', 'single'].includes(name)) { name = 'projects'; load = true; }
    if (isMember && ["skills"].includes(name)) return;
    state.page = name;
    for (const [key, node] of Object.entries(pageNodes)) {
      if (key !== name) {
        node.classList.add("hidden");
        node.classList.remove("flex");
      }
    }
    main.hidden = name !== "studio";
    stages.hidden = name !== "studio";
    projectActions.hidden = name !== "studio";
    dock.hidden = name === "studio";
    worksBar.hidden = !["projects", "history"].includes(name);
    custom.hidden = !["map", "account", "tasks", "inspect", "works"].includes(name);
    custom.replaceChildren();
    if (name === "tasks") {
      custom.append(button("刷新任务", refreshRenderQueue));
      custom.append(queue);
      queue.classList.add("studio-tasks-page");
    } else {
      queue.classList.remove("studio-tasks-page");
      right.insertBefore(queue, byId("pipeline-box"));
    }
    if (name === "works") renderWorksManager();
    if (name === "account") {
      const h = document.createElement("h2");
      h.textContent = "我的账号";
      custom.append(
        h,
        button("修改密码", () => location.assign("/account/password")),
        button("退出登录", () => window.teamLogout?.()),
      );
    }
    if (name === 'account' && !isAdmin) {
      const usageBox = document.createElement('p');
      usageBox.textContent = '正在读取用量…';
      custom.append(usageBox);
      fetch('/api/auth/usage').then(r=>r.json()).then(data=>{
        if (!data.ok) throw new Error(data.msg || '读取失败');
        const {usage,limits}=data;
        usageBox.textContent = `整集运行 ${usage.active} / ${limits.parallel || '不限'}；今日启动 ${usage.daily} / ${limits.daily || '不限'}；作品存储 ${(usage.bytes/1024**3).toFixed(2)} GB / ${limits.storage_gb || '不限'} GB。每日启动按 UTC 日期重置，单镜任务不计入。`;
      }).catch(error=>{usageBox.textContent=error.message;});
    }
    if (name === "map") {
      const h = document.createElement("h2");
      h.textContent = "功能全览";
      custom.append(h);
      Object.entries({
        projects: "作品管理",
        ...(isMember ? {} : { episodes: "剧集管理" }),
        library: "小说与改编",
        single: "单镜生成器",
        skills: "Skills",
        nodes: "ComfyUI 节点管理",
        settings: "服务与模型设置",
        tasks: "任务与日志",
      })
        .filter(([k]) => !isMember || !["skills"].includes(k))
        .forEach(([k, v]) => custom.append(button(v, () => selectPage(k))));
    }
    if (load && loaders[name])
      Promise.resolve(loaders[name]()).catch((e) =>
        log(e.message, "text-red-400"),
      );
    renderNav();
    if (name === "studio") setStageView(state.stage);
  }
  function refreshStageAvailability() {
    const hasFinal = !byId("final-box").classList.contains("hidden");
    const assetsConfirmed = !!window.studioAssetsConfirmed || hasFinal;
    // The shot review/confirm stage must open before final synthesis. A project
    // with every scripted shot rendered is ready for review even when final is
    // still absent.
    const scriptedShots = SCRIPT_DATA?.shots || [];
    const renderedShots = Object.values(SHOT_DATA || {}).filter((shot) =>
      shot && shot.video_url && !shot.error,
    ).length;
    const shotsReady = scriptedShots.length > 0 && renderedShots >= scriptedShots.length;
    const available = [
      true,
      !!SCRIPT_DATA,
      assetsConfirmed && !!SCRIPT_DATA?.shots?.length,
      hasFinal || shotsReady,
    ];
    [...stages.children].forEach((tab, index) => {
      tab.disabled = !available[index];
      tab.title = available[index] ? stageNames[index] : "尚无生成内容，完成前面的步骤后开放";
    });
  }
  // The project loader also selects a stage when restoring rendered shots.
  window.setStageView = setStageView;
  function setStageView(i) {
    // Creating shot cards with the script is not evidence that assets are ready.
    if (i >= 2 && byId("final-box").classList.contains("hidden") && !window.studioAssetsConfirmed) {
      i = byId("script-review-bar") ? 0 : 1;
    }
    state.stage = i;
    refreshStepFooter();
    assetControls.hidden = i !== 1;
    refreshAssetControls();
    main.dataset.stage = String(i);
    sections.forEach((s, n) => {
      s.classList.toggle(
          "studio-stage-off",
          n !== i && !(n === 1 && i === 0),
        );
    });
    [...stages.children].forEach((b, n) =>
      b.setAttribute("aria-current", n === i ? "step" : "false"),
    );
    const shown = sections[i];
    empty.hidden = !shown.classList.contains("hidden");
    empty.textContent = [
      "",
      "确认剧本后，这里会显示角色、场景和道具素材。",
      "生成剧本后，这里会显示分镜与生成状态。",
      "完成视频生成后，可逐镜审片、修改和选择版本。",
      "完成镜头制作并合成后，这里会显示成片和下载入口。",
    ][i];
  }
  // Present the existing batch actions in the approved workspace hierarchy.
  const manager = byId("episode-manager-modal");
  manager.querySelector("h3").textContent = "剧集管理";
  const managerSection = byId("manager-episode-list").parentElement;
  const managerHero = document.createElement("div");
  managerHero.className = "studio-manager-hero";
  const managerTitle = byId("manager-series-title").parentElement;
  managerHero.append(
    managerTitle,
    button("新建一集", async () => {
      if (MANAGER_CURRENT) {
        await openDramaProject(MANAGER_CURRENT.id);
        byId("series-new-episode").focus();
      }
    }),
  );
  managerSection.prepend(managerHero);
  const batchActions = document.createElement("div");
  batchActions.className = "studio-batch-actions";
  for (const selector of [
    '[onclick="queueSelectedManagerEpisodes()"]',
    '[onclick="openJianyingExport()"]',
    "#manager-merge-download",
  ]) {
    const control = manager.querySelector(selector);
    batchActions.append(control);
  }
  managerSection.append(batchActions);
  const clearSelection = button("清空选择", () => {
    MANAGER_SELECTED.clear();
    byId("manager-select-all").checked = false;
    renderEpisodeManagerEpisodes();
  });
  byId("manager-selected-count").after(clearSelection);

  // Independent settings tabs retain all original IDs and save handlers.
  const settings = byId("settings-modal").firstElementChild,
    content = settings.querySelector(".space-y-4");
  const settingsTabs = document.createElement("nav");
  settingsTabs.className = "studio-settings-tabs";
  settings.insertBefore(settingsTabs, content);
  const children = [...content.children],
    panels = {};
  for (const label of [
    "大语言模型",
    "ComfyUI",
    "即梦 API",
    "RunningHub",
    "自动化规则",
  ]) {
    const p = document.createElement("section");
    p.dataset.settingsPage = label;
    panels[label] = p;
    content.append(p);
    settingsTabs.append(button(label, () => settingsPage(label)));
  }
  const mediaContainer = byId("cfg-media-provider").parentElement;
  const providerLabel = mediaContainer.querySelector("label");
  providerLabel.textContent = "当前图片 / 视频生成服务";
  const selectProvider = byId("cfg-media-provider");
  selectProvider.querySelector("option[value=runninghub]")?.remove();
  const serviceBar = document.createElement("div");
  serviceBar.className = "studio-service-choice";
  serviceBar.append(providerLabel, selectProvider);
  settings.insertBefore(serviceBar, settingsTabs);
  panels["即梦 API"].append(byId("cfg-jimeng-box"));
  panels.RunningHub.append(byId("cfg-runninghub-box"));

  for (const child of children) {
    if (child === mediaContainer) {
      child.remove();
      continue;
    }
    if (child.tagName === "BUTTON") {
      content.append(child);
      continue;
    }
    if (
      child.contains(byId("cfg-steps")) ||
      child.contains(byId("cfg-exclusive"))
    )
      panels.ComfyUI.append(child);
    else if (child.contains(byId("cfg-story-bible")))
      panels["自动化规则"].append(child);
    else if (child.parentElement === content)
      panels["大语言模型"].append(child);
  }
  function settingsPage(label) {
    for (const [k, p] of Object.entries(panels)) p.hidden = k !== label;
    [...settingsTabs.children].forEach((b) =>
      b.setAttribute(
        "aria-current",
        b.textContent === label ? "page" : "false",
      ),
    );
    byId("cfg-jimeng-box").classList.remove("hidden");
    byId("cfg-runninghub-box").classList.remove("hidden");
  }
  toggleJimengBox = () => {
    byId("cfg-jimeng-box").classList.remove("hidden");
    byId("cfg-runninghub-box").classList.remove("hidden");
  };
  selectProvider.addEventListener("change", toggleJimengBox);
  settingsPage("大语言模型");
  function renderMonitor() {
    progress.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "当前任务";
    progress.append(heading);
    const active = RENDER_QUEUE.find((t) => t.status === "running");
    if (active) {
      const title = document.createElement("p");
      title.textContent = active.title || active.pid;
      const phase = document.createElement("p");
      phase.textContent =
        (active.phase || "生成中") +
        " · " +
        Math.max(0, Math.min(100, Number(active.progress) || 0)) +
        "%";
      const meter = document.createElement("progress");
      meter.max = 100;
      meter.value = Number(active.progress) || 0;
      meter.setAttribute("aria-label", "当前任务进度");
      progress.append(title, phase, meter);
    } else {
      const p = document.createElement("p");
      p.textContent = es
        ? "当前制作正在运行，请查看下方阶段与日志"
        : "当前没有运行中的队列任务";
      progress.append(p);
    }
    errors.replaceChildren();
    const h = document.createElement("h3");
    const failed = RENDER_QUEUE.filter((t) => t.status === "error");
    h.textContent = "报错与提醒 · " + failed.length + " 项";
    errors.append(h);
    failed.forEach((t) => {
      const box = document.createElement("div");
      box.className = "studio-error";
      const title = document.createElement("strong");
      title.textContent = t.title || t.pid;
      const msg = document.createElement("p");
      msg.textContent = t.error || t.message || "生成失败，请查看日志";
      box.append(title, msg);
      box.append(button("查看任务", () => selectPage("tasks")));
      if (!["single_shot", "rerender", "batch_render"].includes(t.queue_type))
        box.append(
          button("重试", (event) => retryRenderQueueItem(t.id, event)),
        );
      errors.append(box);
    });
    updateCrumbs();
    if (state.page === "studio") setStageView(state.stage);
  }
  const oldRenderProjects = renderProjectList;
  renderProjectList = function(...args) {
    const result = oldRenderProjects(...args);
    renderNav();
    return result;
  };
  const oldRender = renderSideDramaProjectList;
  renderSideDramaProjectList = function (list) {
    oldRender(list);
    if (!state.series && DRAMA_PROJECT_LIST.length)
      state.series = DRAMA_PROJECT_LIST[0].id;
    renderNav();
  };
  const oldOpenDrama = openDramaProject;
  openDramaProject = async function (id) {
    await oldOpenDrama(id);
    if (SERIES_CURRENT?.id === id) {
      state.series = id;
      renderNav();
    }
  };
  window.addEventListener('current-project-change', renderNav);
  const oldOpen = openProject;
  openProject = async function (...args) {
    if (isAdmin) {
      if (args[1]?.restoreScrollY !== undefined) return false;
      selectPage('inspect', false);
      const response = await fetch('/api/project/' + encodeURIComponent(args[0]));
      const result = await response.json();
      if (state.page !== 'inspect') return false;
      const title = document.createElement('h2');
      title.textContent = result.project?.title || '作品详情';
      custom.append(title);
      if (!response.ok || !result.ok) { custom.append(document.createTextNode(result.msg || '读取失败')); return false; }
      const project = result.project;
      const script = document.createElement('pre');
      script.style.whiteSpace = 'pre-wrap';
      script.textContent = project.script ? buildFullScriptText(project.script) : '暂无剧本';
      custom.append(script);
      const shots = (project.shots || []).filter(shot => shot.video_url);
      if (shots.length) {
        const heading = document.createElement('h3');
        heading.textContent = `已生成分镜视频（${shots.length}）`;
        custom.append(heading);
        for (const shot of shots) {
          const label = document.createElement('p');
          label.textContent = `镜头 ${shot.index}`;
          const video = document.createElement('video');
          video.src = shot.video_url;
          video.controls = true;
          video.preload = 'metadata';
          video.style.maxWidth = '100%';
          custom.append(label, video);
        }
      }
      for (const asset of project.assets || []) { if (asset.url) { const img = document.createElement('img'); img.src = asset.url; img.alt = asset.key; img.style.maxWidth = '100%'; custom.append(img); } }
      const finalUrl = project.final || project.previous_final;
      if (finalUrl) {
        const section = document.createElement('section');
        section.id = 'inspect-final';
        const heading = document.createElement('h3');
        heading.textContent = project.final ? '已合成视频' : '上次合成的视频（修改后需重新合成）';
        const video = document.createElement('video');
        video.src = finalUrl;
        video.controls = true;
        video.preload = 'metadata';
        video.style.maxWidth = '100%';
        const download = document.createElement('a');
        download.href = finalUrl;
        download.textContent = '下载视频';
        let filename = '';
        try { filename = decodeURIComponent(new URL(finalUrl, location.href).pathname.split('/').pop()); } catch (_) {}
        download.download = filename && filename !== 'final.mp4' ? filename : safeDownloadName(project.title);
        section.append(heading, video, download);
        title.after(section);
      }
      return true;
    }
    const result = await oldOpen(...args);
    if (result) {
      const series = DRAMA_PROJECT_LIST.find((s) =>
        Object.values(s.episodes || {}).some(
          (e) => e.project_id === currentPid || (e.versions || []).some(v => v.project_id === currentPid),
        ),
      );
      state.series = series?.id || "short";
      selectPage("studio", false);
      setStageView(
        byId("final-box").classList.contains("hidden")
          ? byId("script-review-bar")
            ? 0
            : SCRIPT_DATA
              ? 2
              : 0
          : 3,
      );
    }
    return result;
  };
  const oldContinue = continueManualSeriesEpisode;
  continueManualSeriesEpisode = function (...args) {
    oldContinue(...args);
    selectPage("studio", false);
    setStageView(0);
  };
  const oldNew = newProject;
  newProject = async function (...args) {
    const result = await oldNew(...args);
    if (result === true) {
      state.series = "short";
      selectPage("studio", false);
      setStageView(0);
    }
    return result;
  };
  new MutationObserver(renderMonitor).observe(byId("render-queue-list"), {
    childList: true,
  });
  new MutationObserver((records) => {
    if (state.page !== "studio") return;
    const changes = records.filter(
      (r) =>
        r.target.classList.contains("hidden") !==
        (r.oldValue || "").split(" ").includes("hidden"),
    );
    if (!changes.length) return;
    const revealed = changes
      .filter((r) => !r.target.classList.contains("hidden"))
      .map((r) => r.target.id);
    if (
      byId("script-review-bar") &&
      revealed.some((id) => ["script-box", "shots-box"].includes(id))
    )
      setStageView(0);
    else if (revealed.includes("final-box")) setStageView(3);
    else if (revealed.includes("shots-box")) setStageView(window.studioAssetsConfirmed ? 2 : 1);
    else if (revealed.includes("script-box")) setStageView(1);
    else setStageView(state.stage);
  }).observe(main, {
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
    attributeOldValue: true,
  });
  // Existing IDs used by asynchronous list updates must remain available.
  for (const id of ["side-drama-list", "side-project-list"]) {
    if (!byId(id)) {
      const hidden = document.createElement("div");
      hidden.id = id;
      hidden.hidden = true;
      document.body.append(hidden);
    }
  }
  if (isAdmin) {
    document.body.classList.add('studio-admin');
    currentTitle.textContent = '管理工作台';
    const creativeHandlers = /^(toggleDramaCreate|createDramaProject|toggleDramaCreatePanel|newProject|newSeriesEpisode|continueManualSeriesEpisode|openRemakeModal|openCurrentProjectRemake|autoMatchDirector|generateNovel|queueNovel|extractNovel|generateTrailer|generateExcerpt|sendCurrentNovelChapterToStory|useNovelHighlight)/;
    const hideCreativeControls = () => {
      for (const node of dock.querySelectorAll('[onclick]')) {
        const handler = node.getAttribute('onclick').replace(/^event\.stopPropagation\(\);/, '').trim();
        if (creativeHandlers.test(handler)) node.hidden = true;
      }
      for (const node of worksBar.querySelectorAll('button')) if (node.textContent.startsWith('新建')) node.hidden = true;
      managerHero.querySelector('button').hidden = true;
    };
    new MutationObserver(hideCreativeControls).observe(dock, {childList:true,subtree:true});
    hideCreativeControls();
  }
  main.querySelector("footer")?.remove();
  document.body.classList.add("studio-production");
  renderNav();
  const requestedView = new URLSearchParams(location.search).get('view');
  const embedded = isAdmin && new URLSearchParams(location.search).get('embedded') === '1';
  if (embedded) document.body.classList.add('studio-admin-embedded');
  selectPage(isAdmin && ['projects','history','episodes','tasks','settings','nodes','skills','library'].includes(requestedView) ? requestedView : 'studio', isAdmin);
  renderMonitor();
})();
