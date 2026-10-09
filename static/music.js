'use strict';
(() => {
  const player=document.querySelector('#music-player'),slot=document.querySelector('#music-slot'),toggle=document.querySelector('#music-toggle');
  const url='https://music.163.com/outchain/player?type=2&id=3413072220&auto=1&height=66';
  const switches=[document.querySelector('#music-enabled'),document.querySelector('#settings-music-enabled')];
  let enabled=false,busy=false;
  function apply(value){enabled=value;switches.forEach(input=>input.checked=value);
    if(value&&!slot.firstChild){const frame=document.createElement('iframe');frame.title='网易云音乐 · 直到大地变成一颗酸橙';frame.src=url;frame.allow='autoplay';frame.referrerPolicy='no-referrer';slot.replaceChildren(frame);}
    if(!value)slot.replaceChildren();toggle.textContent=value?'停止 BGM':'播放 BGM';player.classList.toggle('playing',value);
  }
  async function change(value){if(busy)return;busy=true;const previous=enabled;apply(value);switches.forEach(input=>input.disabled=true);toggle.disabled=true;
    try{await api('music',{enabled:value});}catch(error){apply(previous);throw error;}finally{busy=false;switches.forEach(input=>input.disabled=false);toggle.disabled=false;}
  }
  toggle.onclick=()=>guard(()=>change(!enabled));
  switches.forEach(input=>input.onchange=()=>guard(()=>change(input.checked)));
  document.querySelector('#music-source').onclick=()=>openUrl('https://music.163.com/song?id=3413072220');
  const wait=setInterval(()=>{if(typeof state!=='undefined'&&state.data){clearInterval(wait);apply(state.data.music?.enabled===true);}},50);
})();
