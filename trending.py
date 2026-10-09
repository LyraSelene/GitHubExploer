"""Actual GitHub Trending periods, with persisted snapshots and stale fallback."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re
import threading
import time
from core import Transport, UserError

PERIODS = {'daily': '今日', 'weekly': '本周', 'monthly': '本月'}
class TrendingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items=[]; self.item=None; self.depth=0; self.stack=[]; self.current=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs); classes=attrs.get('class','').split()
        if tag=='article' and 'Box-row' in classes:
            self.item={'name':'','description':'','language':'','stars':'','period_stars':''};self.stack=[]
        if self.item is None:return
        if tag in {'br','img','input','meta','link','hr','wbr'}:return
        self.stack.append((tag,attrs,[]))
    def handle_data(self, data):
        for tag, attrs, values in self.stack:values.append(data)
    def handle_endtag(self, tag):
        if self.item is None:return
        match=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if match is None:return
        _,attrs,values=self.stack[match];self.stack=self.stack[:match]
        text=' '.join(''.join(values).split());href=attrs.get('href','')
        if tag=='a' and any(t=='h2' for t,_,_ in self.stack):
            if re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',href):self.item['name']=href[1:]
        if tag=='p':self.item['description']=text[:800]
        if attrs.get('itemprop')=='programmingLanguage':self.item['language']=text
        if tag=='a' and href.endswith('/stargazers'):self.item['stars']=text
        if tag=='span' and 'stars' in text.lower() and any(word in text.lower() for word in ('today','week','month')):self.item['period_stars']=text
        if tag=='article':
            if self.item['name']:
                self.item['url']='https://github.com/'+self.item['name'];self.items.append(self.item)
            self.item=None;self.stack=[]

class Trending:
    def __init__(self, store):self.store=store;self.lock=threading.Lock();self.attempts={}
    def get(self, period='daily', refresh=False):
        if period not in PERIODS or not isinstance(refresh,bool):raise UserError('热点周期需要是日、周或月。')
        key='github_trending_'+period
        with self.lock:
            cached=self.store.get(key,None);now=time.time()
            recent=cached and now-cached.get('timestamp',0)<900
            # Click spam and simultaneous windows share a short request cooldown.
            if (recent and not refresh) or now-self.attempts.get(period,0)<30:
                if cached:return {**cached,'cached':True,'stale':not recent}
                raise UserError('刚刚尝试过更新，请稍后再试。')
            self.attempts[period]=now
            source='https://github.com/trending?since='+period
            transport=Transport(threading.Event())
            try:
                parser=TrendingParser();parser.feed(transport.read(source,limit=2_000_000).decode('utf-8'))
                if not parser.items:raise UserError('GitHub 榜单暂不可解析，请稍后重试或打开来源。')
                result={'period':period,'items':parser.items[:25],'source':source,'timestamp':time.time(),
                        'updated':datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S +08:00')}
                self.store.set(key,result);return {**result,'cached':False,'stale':False}
            except Exception as exc:
                if cached:return {**cached,'cached':True,'stale':True,'error':'更新失败，显示上次榜单。'}
                if isinstance(exc,UserError):raise
                raise UserError('GitHub 热点暂时无法获取，请检查网络或稍后重试。') from exc
            finally:transport.close()
