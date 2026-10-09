'use strict';
(()=>{
 let current=null,dirty=false,saving=null,timer=null,trash=false,links=[],editSequence=0;
 const fields=['note-title','note-content','note-tags','note-folder','note-pinned'];
 const status=text=>$('#notes-save-status').textContent=text;
 function draft(){return {id:current.id,title:$('#note-title').value,content:$('#note-content').value,tags:$('#note-tags').value,folder:$('#note-folder').value,pinned:$('#note-pinned').checked,links:links.map(l=>({...l})),revision:current.revision};}
 function cache(){if(current&&!current.deleted){try{localStorage.setItem('notes-draft-'+current.id,JSON.stringify(draft()));}catch(error){status('草稿备份失败，请立即保存');}}}
 function changed(){if(!current||current.deleted)return;dirty=true;editSequence++;cache();status('待保存…');clearTimeout(timer);timer=setTimeout(()=>guard(flush),1000);$('#notes-preview-body').innerHTML=markdown($('#note-content').value);bindLinks($('#notes-preview-body'));}
 async function flush(){
  clearTimeout(timer);
  if(saving){await saving; if(dirty)return flush(); return;}
  if(!dirty||!current||current.deleted)return;
  const payload=draft(),sequence=editSequence;status('保存中…');
  saving=(async()=>{try{const saved=await api('notes_save',payload);current=saved;dirty=editSequence!==sequence;
   if(!dirty){localStorage.removeItem('notes-draft-'+saved.id);status('已保存 · '+saved.updated_at.slice(11,19));}
   else{cache();status('待保存…');}await refreshList();
  }catch(error){dirty=true;status('保存失败 · 点击保存重试');throw error;}})();
  try{await saving;}finally{saving=null;}if(dirty)return flush();
 }
 function setEditor(note){current=note;dirty=false;editSequence=0;links=note.links.map(l=>({type:l.target_type,id:l.target_id,label:l.target_label}));
  $('#note-title').value=note.title;$('#note-content').value=note.content;$('#note-tags').value=note.tags.join(', ');$('#note-folder').value=note.folder;$('#note-pinned').checked=note.pinned;
  fields.forEach(id=>$('#'+id).disabled=note.deleted);$('#notes-link-add').disabled=note.deleted;$('#notes-save').disabled=note.deleted;$('#notes-delete').hidden=note.deleted;$('#notes-restore').hidden=!note.deleted;$('#notes-export').disabled=note.deleted;status(note.deleted?'已删除 · 可恢复':'已保存 · '+note.updated_at.slice(11,19));
  $('#notes-preview-body').innerHTML=markdown(note.content);bindLinks($('#notes-preview-body'));renderLinks();
 }
 async function open(id){await flush();const note=await api('notes_get',{id,include_deleted:true});setEditor(note);
  let backup=null;try{backup=JSON.parse(localStorage.getItem('notes-draft-'+id));}catch(error){}
  if(backup&&!note.deleted){$('#note-title').value=backup.title;$('#note-content').value=backup.content;$('#note-tags').value=Array.isArray(backup.tags)?backup.tags.join(', '):backup.tags;$('#note-folder').value=backup.folder;$('#note-pinned').checked=backup.pinned;links=backup.links||[];current.revision=backup.revision;renderLinks();dirty=true;status('发现未保存草稿 · 点击保存');}
  await refreshList();
  await loadTargets();
 }
 function selectOptions(id,values,label){const el=$(id),old=el.value;el.replaceChildren(new Option(label,''));values.forEach(v=>el.add(new Option(v,v)));if(values.includes(old))el.value=old;}
 async function refreshList(){const result=await api('notes_list',{query:$('#notes-search').value,folder:$('#notes-folder-filter').value,tag:$('#notes-tag-filter').value,include_deleted:trash});selectOptions('#notes-folder-filter',result.folders,'全部文件夹');selectOptions('#notes-tag-filter',result.tags,'全部标签');const root=$('#notes-list');root.replaceChildren();
  const items=result.notes.filter(n=>n.deleted===trash);if(!items.length){root.innerHTML='<p class="hint">'+(trash?'没有已删除笔记。':'暂无笔记或没有匹配结果。')+'</p>';return;}
  items.forEach(note=>{const b=document.createElement('button');b.className='note-card'+(current?.id===note.id?' selected':'');const q=$('#notes-search').value.trim().split(/\s+/)[0],pos=q?note.content.toLowerCase().indexOf(q.toLowerCase()):0;const snippet=note.content.slice(Math.max(0,pos-35),Math.max(0,pos-35)+150);b.innerHTML='<strong>'+(note.pinned?'📌 ':'')+esc(note.title)+'</strong><small>'+esc(note.folder||'未分类')+' · '+esc(note.updated_at.slice(0,19))+'</small><small>'+esc(note.tags.join(' / '))+'</small><p>'+esc(snippet)+'</p>';b.onclick=()=>guard(()=>open(note.id));root.append(b);});
 }
 async function create(initial={}){await flush();trash=false;$('#notes-trash').textContent='已删除';const note=await api('notes_create',{folder:$('#notes-folder-filter').value,...initial});setEditor(note);page('notes');await refreshList();await loadTargets();$('#note-content').focus();}
 function renderLinks(){const root=$('#note-links-list');root.replaceChildren();if(!links.length)root.innerHTML='<p class="hint">尚未关联，选择已有资料 / 报告 / 学习任务，或填写 GitHub 仓库 URL。</p>';
  links.forEach((link,index)=>{const row=document.createElement('div');row.className='note-link-row';const b=document.createElement('button');b.textContent=({report:'研究报告',material:'资料',github:'GitHub',learning_task:'学习任务'}[link.type])+': '+(link.label||link.id);b.onclick=()=>guard(async()=>{await flush();if(link.type==='material')await window.Materials.show(Number(link.id));else if(link.type==='report')await loadReport(Number(link.id));else if(link.type==='github')await openUrl(link.id);else{const [projectId]=link.id.split(':');await refresh();page('github');learnTab('progress');if(!state.data.learning.some(p=>p.id===Number(projectId)))throw Error('学习项目不存在');showProject(Number(projectId));}});const remove=document.createElement('button');remove.textContent='移除';remove.disabled=current?.deleted;remove.onclick=()=>{links.splice(index,1);renderLinks();changed();};row.append(b,remove);root.append(row);});
 }
 async function loadTargets(){const data=await api('notes_targets');const type=$('#note-link-type').value,select=$('#note-link-target');select.replaceChildren(new Option('选择已有目标，或在下面填写',''));const items=type==='report'?data.reports:type==='material'?data.materials:type==='learning_task'?data.learning.flatMap(p=>p.tasks.map((t,i)=>({id:p.id+':'+i,title:p.name+' · '+(i+1)+'. '+t.title}))):[];items.forEach(i=>select.add(new Option(i.title,String(i.id))));select.hidden=type==='github';}
 async function exportFolder(){await flush();const folder=current?.folder??$('#notes-folder-filter').value;
  if(window.pywebview){const result=await window.pywebview.api.export_notes_folder(folder);if(result.error)throw Error(result.error);if(result.saved)toast('已导出 '+result.count+' 篇笔记到 '+result.path);}
  else{const result=await api('notes_export_folder',{folder});if(!result.files.length)throw Error('文件夹没有笔记');await exportText((folder||'未分类')+'-全部笔记',result.files.map(f=>'<!-- '+f.name+' -->\n'+f.text).join('\n\n'));}}
 async function versions(){await flush();if(!current)return;const result=await api('notes_versions',{id:current.id});const root=$('#notes-versions-list');root.replaceChildren();result.versions.forEach(v=>{const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='版本 '+v.version_no+' · '+v.created_at.slice(0,19)+' · '+v.title;const pre=document.createElement('pre');pre.textContent=v.content;const b=document.createElement('button');b.textContent='恢复此版本';b.disabled=current.deleted;b.onclick=()=>guard(async()=>{const note=await api('notes_restore_version',{id:current.id,version:v.version_no});setEditor(note);await refreshList();closeModal('notes-versions-modal');toast('版本已恢复，并保存为新版本');});details.append(summary,pre,b);root.append(details);});openModal('notes-versions-modal');}
 window.NotesUI={hasPending:()=>dirty||!!saving,flush,show:async(id)=>{closeModal('report-modal');page('notes');await open(id);},create,
  sourceRef:()=>{if(!current||current.deleted)throw Error('请先打开一篇未删除的笔记');return {type:'note',id:current.id};},
  backlinks:async(container,type,id)=>{const data=await api('notes_reverse',{type,id});container.replaceChildren();const h=document.createElement('h3');h.textContent='引用此'+(type==='material'?'资料':'报告')+'的笔记';container.append(h);if(!data.notes.length){const p=document.createElement('p');p.className='hint';p.textContent='暂无引用笔记。';container.append(p);}data.notes.forEach(n=>{const b=document.createElement('button');b.textContent=n.title+' · '+(n.folder||'未分类');b.onclick=()=>guard(()=>window.NotesUI.show(n.id));container.append(b);});const b=document.createElement('button');b.className='secondary compact';b.textContent='＋ 创建关联笔记';b.onclick=()=>guard(async()=>{closeModal('report-modal');await create({links:[{type,id:String(id)}]});});container.append(b);}};
 const tagSelect=document.createElement('select');tagSelect.id='notes-tag-filter';tagSelect.className='notes-tag-filter';tagSelect.setAttribute('aria-label','标签筛选');tagSelect.add(new Option('全部标签',''));$('#notes-toolbar-placeholder')?.append(tagSelect);$('#notes-trash').before(tagSelect);
 const target=document.createElement('select');target.id='note-link-target';target.setAttribute('aria-label','选择关联目标');$('#note-link-id').before(target);target.onchange=()=>{if(target.value){$('#note-link-id').value=target.value;$('#note-link-label').value=target.selectedOptions[0].textContent;}};
 const preview=document.createElement('details');preview.innerHTML='<summary>Markdown 预览</summary><div id="notes-preview-body" class="markdown notes-markdown"></div>';$('#note-content').after(preview);
 const modal=document.createElement('div');modal.id='notes-versions-modal';modal.className='overlay';modal.innerHTML='<section class="modal wide glass"><button class="close" aria-label="关闭版本历史">×</button><h2>笔记版本历史</h2><p class="hint">保留当前版本和最近 10 个历史版本；恢复会创建新版本，包含标题、正文、标签、文件夹、置顶和关联关系。</p><div id="notes-versions-list" class="notes-versions-list"></div></section>';modal.querySelector('.close').onclick=()=>closeModal(modal.id);document.body.append(modal);
 fields.forEach(id=>$('#'+id).oninput=changed);$('#notes-new').onclick=()=>guard(()=>create());$('#notes-save').onclick=()=>guard(flush);$('#notes-search-button').onclick=()=>guard(refreshList);$('#notes-search').onkeydown=e=>{if(e.key==='Enter')guard(refreshList);};$('#notes-folder-filter').onchange=tagSelect.onchange=()=>guard(refreshList);$('#notes-trash').onclick=()=>guard(async()=>{await flush();trash=!trash;$('#notes-trash').textContent=trash?'返回笔记':'已删除';await refreshList();});
 $('#notes-delete').onclick=()=>guard(async()=>{if(!current)return;await flush();await api('notes_delete',{id:current.id});localStorage.removeItem('notes-draft-'+current.id);setEditor(await api('notes_get',{id:current.id,include_deleted:true}));await refreshList();toast('已移到已删除，可恢复。');});
 $('#notes-restore').onclick=()=>guard(async()=>{if(!current)return;setEditor(await api('notes_restore',{id:current.id}));trash=false;$('#notes-trash').textContent='已删除';await refreshList();});
 $('#notes-export').onclick=()=>guard(async()=>{await flush();if(!current)return;const data=await api('notes_export',{id:current.id});await exportText(current.title,data.text);});$('#notes-folder-export').onclick=()=>guard(exportFolder);$('#notes-versions').onclick=()=>guard(versions);
 $('#note-link-type').onchange=()=>guard(loadTargets);$('#notes-link-add').onclick=()=>{if(!current||current.deleted)return;const link={type:$('#note-link-type').value,id:$('#note-link-id').value.trim(),label:$('#note-link-label').value.trim()};if(!link.id){toast('请选择关联目标或填写 ID / URL');return;}if(!links.some(l=>l.type===link.type&&l.id===link.id)){links.push(link);renderLinks();changed();}};
 $('[data-page="notes"]').addEventListener('click',()=>guard(async()=>{await refreshList();await loadTargets();}));
 $$('.nav').forEach(b=>b.addEventListener('click',()=>{if(dirty)guard(flush);}));addEventListener('beforeunload',e=>{if(dirty||saving){cache();e.preventDefault();e.returnValue='';}});
 fields.forEach(id=>$('#'+id).disabled=true);
 for(const [parent,id] of [['.research-options','notes-enabled'],['#discover-panel .card-footer','notes-learning-enabled'],['.follow-row','notes-follow-enabled']]){const label=document.createElement('label');label.className='check notes-permission';label.innerHTML='<input id="'+id+'" type="checkbox"><span>读取笔记</span><small>命中内容会发送到所选模型</small>';$(parent).append(label);}
 document.documentElement.dataset.notesReady='true';
})();
