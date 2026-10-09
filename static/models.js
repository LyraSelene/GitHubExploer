'use strict';
(() => {
  let profiles=[], routes={}, selected=null;
  const tasks={research:'研究 / GitHub 学习',chat:'Agent 对话',summary:'总结 / 复习卡片 / 报错分析',ppt:'PPT 内容'};
  function edit(id){
    selected=profiles.find(p=>p.id===id)||null;
    const p=selected||{name:'',vendor:'OpenAI 兼容',base_url:'https://api.openai.com/v1',model:'',capabilities:['chat','research','summary','ppt'],source_tools:true};
    $('#profile-model-name').value=p.name;$('#model-vendor').value=p.vendor;$('#base-url').value=p.base_url;$('#model-name').value=p.model;
    $('#api-key').value='';$('#api-key').placeholder=p.has_key?'已通过 DPAPI 保存 · 留空保留':'本地 Ollama 可留空';
    $('#model-default').checked=!!p.is_default;$('#model-mobile').checked=!!p.mobile_authorized;$('#source-tools').checked=!!p.source_tools;$('#model-clear-key').checked=false;
    $$('[data-model-cap]').forEach(el=>el.checked=p.capabilities.includes(el.dataset.modelCap));
    $('#model-delete').disabled=!selected;$('#connection-status').textContent='';
    $('#model-editor-title').textContent=selected?'编辑模型':'新增模型';
    $('#model-stats').textContent=selected?`请求 ${p.metrics.request_count} 次 · 估算 ${p.metrics.estimated_tokens} token · 平均 ${p.metrics.avg_latency_ms} ms · 失败 ${p.metrics.failure_count} 次`:'保存后可测试与查看调用统计';
    $('#model-last-error').textContent=p.metrics?.last_error||'暂无最近错误';
    renderList();
  }
  function renderList(){
    $('#model-profiles').innerHTML=profiles.map(p=>`<button class="model-profile ${p.id===selected?.id?'selected':''}" data-profile-id="${p.id}"><strong>${esc(p.name)} ${p.is_default?'· 默认':''}</strong><small>${esc(p.vendor)} · ${esc(p.model)}</small><small>${p.mobile_authorized?'手机已授权':'手机未授权'} · ${p.metrics.request_count} 次请求</small></button>`).join('')||'<p class="hint">添加第一个模型配置。</p>';
    $$('[data-profile-id]').forEach(b=>b.onclick=()=>edit(Number(b.dataset.profileId)));
  }
  function renderRoutes(){
    $('#model-routes').innerHTML=Object.entries(tasks).map(([task,label])=>{
      const route=routes[task]||{},options=(id,empty)=>`<option value="">${empty}</option>`+profiles.filter(p=>p.capabilities.includes(task)).map(p=>`<option value="${p.id}" ${p.id===id?'selected':''}>${esc(p.name)}</option>`).join('');
      return `<div class="model-route" data-task="${task}"><strong>${label}</strong><label>主模型<select data-primary>${options(route.primary_id,'使用默认模型')}</select></label><label>备用模型<select data-backup>${options(route.backup_id,'无备用模型')}</select></label><label class="check"><input type="checkbox" data-fallback ${route.fallback_enabled?'checked':''}><span>允许自动切换</span></label></div>`;
    }).join('');
  }
  async function load(){
    const d=await api('models_list');profiles=d.models;routes=d.routes;renderList();renderRoutes();
    $('#model-errors').innerHTML=d.errors.map(e=>`<p>${esc(e.created_at)} · ${esc(tasks[e.task]||e.task)} · 配置 #${e.profile_id}<br>${esc(e.error)}</p>`).join('')||'暂无错误记录';
  }
  function values(){return {id:selected?.id,name:$('#profile-model-name').value.trim(),vendor:$('#model-vendor').value,base_url:$('#base-url').value.trim(),model:$('#model-name').value.trim(),api_key:$('#api-key').value,clear_key:$('#model-clear-key').checked,capabilities:$$('[data-model-cap]:checked').map(e=>e.dataset.modelCap),is_default:$('#model-default').checked,mobile_authorized:$('#model-mobile').checked,source_tools:$('#source-tools').checked};}
  async function save(){try{const saved=await api('model_save',values());await load();edit(saved.id);await refresh();toast('模型配置已保存');return saved.id;}finally{$('#api-key').value='';}}
  async function show(){await load();edit(profiles.find(p=>p.is_default)?.id);const device=await api('remote_status');$('#models-device-status').textContent=device.enabled?'局域网手机连接已开启；只允许使用勾选授权的模型。':'局域网手机连接未开启；模型授权在电脑端管理。';openModal('settings-modal');}
  async function test(capability){
    const buttons=[$('#test-connection'),$('#model-test-capabilities')];buttons.forEach(b=>b.disabled=true);
    try{const id=await save();$('#connection-status').textContent='正在测试，可能产生服务费用…';const r=await api(capability?'model_test_capabilities':'model_test_connection',{id,task:$('#model-test-task').value});await load();edit(id);$('#connection-status').textContent=r.message+(r.checks?' '+r.checks.map(c=>c.name+'：'+(c.passed?'通过':'未通过')).join('；'):'');}
    catch(e){$('#connection-status').textContent=e.message;await load();}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
  ['settings-open','model-open'].forEach(id=>{if($('#'+id))$('#'+id).onclick=()=>guard(show);});
  $('#model-add').onclick=()=>edit(null);$('#save-settings').onclick=()=>guard(save);$('#test-connection').onclick=()=>test(false);$('#model-test-capabilities').onclick=()=>test(true);
  $('#model-vendor').onchange=()=>{if($('#model-vendor').value==='Ollama')$('#base-url').value='http://127.0.0.1:11434/v1';};
  $('#model-delete').onclick=()=>guard(async()=>{if(!selected)return;await api('model_delete',{id:selected.id});await load();edit(profiles.find(p=>p.is_default)?.id);await refresh();toast('模型已删除');});
  $('#model-routes-save').onclick=()=>guard(async()=>{const result={};$$('[data-task]').forEach(row=>{result[row.dataset.task]={primary_id:Number(row.querySelector('[data-primary]').value)||null,backup_id:Number(row.querySelector('[data-backup]').value)||null,fallback_enabled:row.querySelector('[data-fallback]').checked};});routes=await api('model_routes_save',result);await refresh();toast('任务模型选择已保存');});
  $('#models-device-open').onclick=()=>{closeModal('settings-modal');$('#remote-open').click();};
  document.documentElement.dataset.modelsReady='true';
})();
