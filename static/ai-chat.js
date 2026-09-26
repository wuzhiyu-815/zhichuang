/* Shared view for story, image and video editing. Business handlers stay in workspace-main.js. */
window.AIChat = (() => {
  const variants = {
    story: {prefix:'story-chat', hint:'描述你想调整的人物、剧情或结尾', send:'sendStoryChat', model:true,
      status:'修改后自动回填正文并保存草稿', action:{id:'story-chat-undo', label:'撤销上次修改', handler:'undoStoryChat', disabled:true}},
    image: {prefix:'image-edit-chat', hint:'例如：光线更柔和，保留人物服装', send:'sendImageEditChat', model:true},
    video: {prefix:'edit-chat', hint:'描述你想调整的动作、节奏或画面', send:'sendEditChat', model:true,
      action:{id:'edit-redraw', label:'🔄 用此提示词重新渲染', handler:'editRedraw'}},
  };
  // Change this one template to update all three editors.
  const template = document.createElement('template');
  template.innerHTML = `<div class="ai-chat-heading"><strong>💬 AI 对话</strong><span data-chat-hint></span></div>
    <div class="ai-chat-messages" data-chat-part="messages" role="log" aria-live="polite"></div>
    <div class="ai-chat-composer">
      <textarea class="ai-chat-input" data-chat-part="input" rows="1" aria-label="AI 修改要求" placeholder="告诉 AI 你想怎么改…（Enter 发送，Shift+Enter 换行）"></textarea>
      <div class="ai-chat-controls" data-chat-part="controls">
        <div class="ai-chat-actions" data-chat-actions></div>
        <select class="ai-chat-model" data-chat-part="model" aria-label="本次对话模型"><option value="">使用当前 LLM</option></select>
        <button class="ai-chat-send" data-chat-part="send" type="button">发送</button>
      </div>
      <span class="ai-chat-status" data-chat-part="status" role="status"></span>
    </div>`;
  function resize(input){
    if(!input)return;
    input.style.height='42px';
    input.style.height=Math.min(Math.max(input.scrollHeight,42),180)+'px';
    input.style.overflowY=input.scrollHeight>180?'auto':'hidden';
  }
  function append(box,role,content){
    const row=document.createElement('div');
    row.className='ai-chat-message '+(role==='user'?'ai-chat-user':'ai-chat-assistant');
    row.dataset.role=role;row.dataset.content=String(content??'');
    row.textContent=(role==='user'?'你：':'AI：')+row.dataset.content;
    box.append(row);box.scrollTop=box.scrollHeight;return row;
  }
  function render(box,history){
    if(!box)return;box.replaceChildren();
    for(const item of history||[])append(box,item.role,item.content);
  }
  function mount(root){
    const config=variants[root.dataset.aiChat];
    if(!config||root.dataset.chatMounted)return;
    root.dataset.chatMounted='true';root.classList.add('ai-chat');
    root.append(template.content.cloneNode(true));
    root.querySelector('[data-chat-hint]').textContent=config.hint;
    root.querySelectorAll('[data-chat-part]').forEach(el=>el.id=config.prefix+'-'+el.dataset.chatPart);
    const input=root.querySelector('textarea'),send=root.querySelector('[data-chat-part="send"]');
    if(config.prefix==='story-chat')input.maxLength=4000;
    const status=root.querySelector('[data-chat-part="status"]');
    status.textContent=config.status||'';
    if(!config.model)root.querySelector('select').remove();
    if(config.action){
      const button=document.createElement('button');button.type='button';button.id=config.action.id;
      button.textContent=config.action.label;button.disabled=!!config.action.disabled;
      button.addEventListener('click',()=>window[config.action.handler]());
      root.querySelector('[data-chat-actions]').append(button);
    }
    let busy=false;
    const submit=async()=>{
      if(busy||send.disabled||input.disabled)return;
      busy=true;send.disabled=true;
      try{await window[config.send]();}finally{busy=false;send.disabled=false;resize(input);}
    };
    send.addEventListener('click',submit);
    input.addEventListener('input',()=>resize(input));
    input.addEventListener('keydown',event=>{
      if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();event.stopPropagation();submit();}
    });
  }
  document.querySelectorAll('[data-ai-chat]').forEach(mount);
  return {append,render,resize,mount};
})();
