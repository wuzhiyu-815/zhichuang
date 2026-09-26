let JIANYING_EXPORT_SELECTION=null, JIANYING_EXPORT_BUSY=false;
function openJianyingExport(){
  if(!MANAGER_CURRENT?.id||!MANAGER_SELECTED.size){alert('请先勾选要导出的剧集');return;}
  if(!JIANYING_EXPORT_BUSY){
    JIANYING_EXPORT_SELECTION={series_id:MANAGER_CURRENT.id,project_ids:[...MANAGER_SELECTED]};
    $('jianying-export-summary').textContent=`《${MANAGER_CURRENT.name||'未命名剧'}》 · 已选 ${MANAGER_SELECTED.size} 集，按集数顺序排列`;
    $('jianying-export-status').textContent='原始素材直接打包，无需转码。';
    $('jianying-export-link').classList.add('hidden');
  }
  $('jianying-export-modal').classList.replace('hidden','flex');
}
function closeJianyingExport(){$('jianying-export-modal').classList.replace('flex','hidden');}
function updateJianyingExportMode(){
  const disabled=$('jianying-export-mode').value!=='shots';
  $('jianying-export-subtitles').disabled=disabled;
  if(disabled)$('jianying-export-subtitles').checked=false;
}
async function startJianyingExport(){
  if(JIANYING_EXPORT_BUSY||!JIANYING_EXPORT_SELECTION)return;
  const button=$('jianying-export-start'),status=$('jianying-export-status');
  JIANYING_EXPORT_BUSY=true;
  button.disabled=true;$('jianying-export-mode').disabled=true;$('jianying-export-subtitles').disabled=true;
  $('jianying-export-link').classList.add('hidden');
  status.textContent='正在创建草稿…';
  try{
    const selection=JIANYING_EXPORT_SELECTION;
    const response=await fetch(`/api/series/${encodeURIComponent(selection.series_id)}/jianying-export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_ids:selection.project_ids,mode:$('jianying-export-mode').value,subtitles:$('jianying-export-subtitles').checked})});
    const result=await response.json();
    if(response.status===404&&result.error?.startsWith('接口不存在:'))throw new Error('当前服务尚未加载剪映草稿功能，需要重载服务。');
    if(!response.ok||!result.ok)throw new Error(result.msg||result.error||'无法创建草稿');
    for(;;){
      const poll=await fetch(`/api/jianying-exports/${result.job_id}`),job=await poll.json();
      if(!poll.ok||!job.ok||job.status==='error')throw new Error(job.msg||'草稿打包失败');
      status.textContent=`${job.msg||'正在打包'} · ${job.progress}%`;
      if(job.status==='done'){
        const link=$('jianying-export-link');
        link.href=`/api/jianying-exports/${result.job_id}/download`;
        link.classList.remove('hidden');link.click();
        status.textContent='草稿包已就绪。下载后完整解压，退出剪映，双击 import.cmd 选择草稿位置。';
        break;
      }
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  }catch(error){status.textContent=error.message||'草稿导出失败，请重试';}
  finally{JIANYING_EXPORT_BUSY=false;button.disabled=false;$('jianying-export-mode').disabled=false;updateJianyingExportMode();}
}
