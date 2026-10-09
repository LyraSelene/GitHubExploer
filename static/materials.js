'use strict';
(()=>{
 let query='',selected=null,loading=false;
 const filter=()=>({tag:$('#materials-tag').value,project:$('#materials-project').value});
 const size=n=>n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':(n/1048576).toFixed(1)+' MB';
 function highlighted(text){
  text=String(text||'');const terms=query.trim().split(/\s+/).filter(Boolean);
  if(!terms.length)return esc(text);
  const pattern=new RegExp(terms.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).sort((a,b)=>b.length-a.length).join('|'),'gi');
  let out='',last=0;for(const match of text.matchAll(pattern)){out+=esc(text.slice(last,match.index))+'<mark>'+esc(match[0])+'</mark>';last=match.index+match[0].length;}return out+esc(text.slice(last));
 }
 function options(id,values,label){const el=$(id),old=el.value;el.replaceChildren();el.add(new Option(label,''));values.forEach(v=>el.add(new Option(v,v)));if(values.includes(old))el.value=old;}
 function button(label,handler){const el=document.createElement('button');el.className='secondary compact';el.textContent=label;el.onclick=()=>guard(handler);return el;}
 async function show(id,chunk_id=null,pageNumber=null){
  const data=await api('materials_get',{id,chunk_id,page:pageNumber});selected=id;
  const d=data.document,container=$('#materials-preview');container.replaceChildren();
  const title=document.createElement('h2');title.textContent=d.title;container.append(title);
  const backlinks=document.createElement('div');backlinks.className='note-backlinks';container.append(backlinks);
  if(window.NotesUI)guard(()=>window.NotesUI.backlinks(backlinks,'material',d.id));
  const info=document.createElement('dl');
  [['文件',d.name],['来源',d.path],['类型',d.kind],['大小',size(d.size)],['SHA-256',d.content_hash||d.sha256||'未读取到文件'],['导入时间',d.imported_at],['标签',d.tags.join('、')||'无'],['所属项目',d.project||'未分类']].forEach(([key,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key;dd.textContent=value;info.append(dt,dd);});container.append(info);
  const actions=document.createElement('div');actions.className='materials-actions';
  if(d.github?.commit_sha){const loc=data.hit;const label=document.createElement('p');label.className='hint';label.textContent=d.github.repository+' · '+d.github.file_path+' · '+d.github.commit_sha+(loc?.start_line?' · L'+loc.start_line+'–L'+loc.end_line:'');container.append(label);actions.append(button('固定 GitHub 来源 ↗',()=>openUrl(loc?.source_url||d.github.url)),button('仓库版本与继续导入',()=>{document.querySelector('#github-import-panel').open=true;return window.GitHubImportUI.showVersion(d.github.version_id);}));}

  if(d.status==='ready'&&window.ReviewUI)actions.append(button('生成复习卡片',()=>window.ReviewUI.compose({type:'material',id:d.id,page:data.page,chunk_id:data.hit?.id})));
  const tags=document.createElement('input');tags.value=d.tags.join(', ');tags.placeholder='标签（逗号分隔）';tags.setAttribute('aria-label','编辑标签');
  const project=document.createElement('input');project.value=d.project;project.maxLength=120;project.placeholder='所属项目';project.setAttribute('aria-label','编辑所属项目');
  actions.append(tags,project,button('保存标签 / 项目',async()=>{await api('materials_update',{id,tags:tags.value,project:project.value});await refresh();await show(id,chunk_id,pageNumber);toast('资料信息已保存');}));
  if(d.status==='failed'&&!d.github?.commit_sha)actions.append(button('重试导入',()=>retry(id)));
  actions.append(button('删除资料',async()=>{if(!confirm('删除“'+d.name+'”及其全部分块？原始文件不会删除。'))return;await api('materials_delete',{id});selected=null;container.innerHTML='<p class="hint">资料及分块已删除。原始文件保留。</p>';await refresh();}));container.append(actions);
  if(d.error){const p=document.createElement('p');p.className='material-error';p.textContent=d.error;container.append(p);return;}
  if(d.kind==='pdf'){
   const row=document.createElement('label');row.textContent='PDF 页码 ';const select=document.createElement('select');select.setAttribute('aria-label','PDF 页码');data.pages.forEach(p=>select.add(new Option('第 '+p+' 页',p)));select.value=data.page;select.onchange=()=>guard(()=>show(id,null,Number(select.value)));row.append(select);container.append(row);
  }
  if(data.hit){const title=document.createElement('h3');title.textContent='命中片段'+(data.page?' · 第 '+data.page+' 页':'');const hit=document.createElement('pre');hit.className='material-hit';hit.innerHTML=highlighted(data.hit.content);container.append(title,hit);}
  const heading=document.createElement('h3');heading.textContent='已保存原文'+(data.page?' · 第 '+data.page+' 页':'');const original=document.createElement('pre');original.className='material-original';
  if(data.hit){const a=data.hit.start_offset,b=data.hit.end_offset;original.innerHTML=highlighted(data.text.slice(0,a))+'<span id="material-hit-location">'+highlighted(data.text.slice(a,b))+'</span>'+highlighted(data.text.slice(b));}
  else original.innerHTML=highlighted(data.text);
  container.append(heading,original);if(data.hit){const target=original.querySelector('#material-hit-location');original.scrollTop=Math.max(0,target.offsetTop-original.offsetTop-60);}
  const note=document.createElement('p');note.className='hint';note.textContent='原文是导入时保存的文本快照。PDF 为提取文字，页码按文件实际页序；不包含图片或版式。';container.append(note);
 }
 function render(items,searched){const root=$('#materials-results');root.replaceChildren();if(!items.length){root.innerHTML='<p class="hint">'+(searched?'没有匹配资料，请调整关键词或筛选条件。':'还没有资料，点击上方导入。')+'</p>';return;}
  items.forEach(item=>{const d=searched?item.document:item;const el=document.createElement('button');el.className='material-item';el.innerHTML='<strong>'+esc(d.title)+'</strong><small>'+esc(d.name)+' · '+esc(d.kind)+(searched&&item.page?' · 第 '+item.page+' 页':'')+' · '+size(d.size)+'</small><small>'+esc(d.tags.join(' / '))+(d.project?' · '+esc(d.project):'')+'</small><small>'+esc(d.path)+(searched&&item.start_line?' · L'+item.start_line+'–L'+item.end_line:'')+'</small>'+(d.status==='failed'?'<p class="material-error">导入失败：'+esc(d.error)+'</p>':searched?'<p>'+highlighted(item.snippet)+'</p>':'');el.onclick=()=>guard(()=>show(d.id,searched?item.chunk_id:null));root.append(el);});
 }
 async function refresh(){
  const data=await api('materials_list',filter());options('#materials-tag',data.tags,'全部标签');options('#materials-project',data.projects,'全部项目');
  query=$('#materials-query').value.trim();
  if(query){const result=await api('materials_search',{query,title_only:$('#materials-title-only').checked,...filter()});render(result.results,true);$('#materials-status').textContent='找到 '+result.results.length+' 个结果（最多 50 个） · 关键词需同时匹配同一分块；点击定位原文。';}
  else{render(data.documents,false);$('#materials-status').textContent='已保存 '+(data.counts.ready||0)+' 份资料 · '+(data.counts.failed||0)+' 份失败 · 当前列表 '+data.documents.length+' 份（最多 500）。';}
 }
 function importResult(result){const root=$('#materials-import-results');root.replaceChildren();$('#materials-import-details').hidden=false;$('#materials-import-details').open=true;const summary=document.createElement('p');summary.textContent='成功 '+result.imported+' · 重复 '+result.duplicate+' · 失败 '+result.failed+' · 跳过 '+result.skipped+(result.limited?' · 达到 500 文件限制，余下请分批导入。':'');root.append(summary);
  result.items.forEach(item=>{const row=document.createElement('div');row.className='materials-import-row';const text=document.createElement('span');text.textContent=item.name+' · '+({ready:'已保存',duplicate:'内容重复，使用已有记录',failed:'失败'}[item.status])+(item.error?'：'+item.error:'');row.append(text);if(item.status==='failed'&&item.id)row.append(button('重试',()=>retry(item.id)));root.append(row);});
 }
 async function retry(id){const result=await api('materials_retry',{id});importResult(result);await refresh();if(selected===id){try{await show(id);}catch(error){selected=null;$('#materials-preview').textContent='重试内容与已有资料重复，已合并。';}}}
 async function importFiles(folder){if(loading)return;if(!window.pywebview){toast('请在 Windows 桌面应用中选择文件或文件夹。');return;}loading=true;$('#materials-import').disabled=$('#materials-folder').disabled=true;$('#materials-status').textContent='正在选择并导入资料…';try{const result=await window.pywebview.api.import_materials(folder,$('#materials-import-tags').value,$('#materials-import-project').value);if(result?.error)throw Error(result.error);if(result)importResult(result);await refresh();}finally{loading=false;$('#materials-import').disabled=$('#materials-folder').disabled=false;}}
 $('#materials-import').onclick=()=>guard(()=>importFiles(false));$('#materials-folder').onclick=()=>guard(()=>importFiles(true));$('#materials-refresh').onclick=$('#materials-search').onclick=()=>guard(refresh);$('#materials-query').onkeydown=e=>{if(e.key==='Enter')guard(refresh);};['materials-tag','materials-project','materials-title-only'].forEach(id=>$('#'+id).onchange=()=>guard(refresh));
 $('[data-page="materials"]').addEventListener('click',()=>guard(refresh));
 window.Materials={refresh,show:async(id,chunkId,pageNumber=null)=>{page('materials');await refresh();await show(id,chunkId,pageNumber);}};
 // Separate, session-only permission shared by research, learning and follow-up requests.
 for(const [parent,id] of [['.research-options','materials-enabled'],['#discover-panel .card-footer','materials-learning-enabled'],['.follow-row','materials-follow-enabled']]){
  const label=document.createElement('label');label.className='check materials-permission';const input=document.createElement('input');input.type='checkbox';input.id=id;input.checked=false;const span=document.createElement('span');span.textContent='允许研究 Agent 检索资料库';label.append(input,span);const hint=document.createElement('small');hint.textContent='命中片段会发送到所选模型';label.append(hint);$(parent).append(label);
 }
 document.documentElement.dataset.materialsReady='true';
})();
