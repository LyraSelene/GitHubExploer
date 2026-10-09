'use strict';
(() => {
  let timer;
  function render(value){$('#remote-status').textContent=value.enabled?'已开启 · 已配对 '+value.devices+' 台设备':'未开启';$('#remote-addresses').textContent=value.urls.join('\n')||'开启后显示本机 Wi-Fi 连接地址';$('#remote-code').textContent=value.code||'—';$('#remote-expiry').textContent=value.enabled?(value.code?'配对码约 '+Math.ceil(value.code_seconds/60)+' 分钟后失效':'配对码已过期，可刷新'):'连接每次需手动开启，退出应用后关闭';$('#remote-start').hidden=value.enabled;$('#remote-stop').hidden=!value.enabled;$('#remote-renew').hidden=!value.enabled;}
  async function refreshRemote(){render(await api('remote_status'));}
  $('#remote-open').onclick=()=>guard(async()=>{await refreshRemote();openModal('remote-modal');clearInterval(timer);timer=setInterval(()=>{if($('#remote-modal').classList.contains('open'))guard(refreshRemote);else clearInterval(timer);},5000);});
  $('#remote-start').onclick=()=>guard(async()=>{render(await api('remote_start'));toast('已开启手机连接；在手机浏览器输入上方地址并配对');});$('#remote-stop').onclick=()=>guard(async()=>{render(await api('remote_stop'));toast('已关闭并撤销全部设备访问');});$('#remote-renew').onclick=()=>guard(async()=>{render(await api('remote_renew'));});
  const chatButton=$('[data-page="chat"]');chatButton.onclick=()=>guard(async()=>{if(window.pywebview){const result=await window.pywebview.api.open_chat();if(result.error)throw Error(result.error);}else window.open('companion.html','_blank','noopener');});
})();
