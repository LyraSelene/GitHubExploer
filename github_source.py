"""Shared public GitHub metadata and fixed-commit reader; no code execution."""
import re
import urllib.parse
from core import Transport, UserError

class GitHubTransport(Transport):
    def open(self, url, payload=None, headers=None, authenticated=False):
        p=urllib.parse.urlsplit(url)
        if p.scheme!='https' or p.hostname not in {'api.github.com','raw.githubusercontent.com'} or p.username or p.password or p.port not in (None,443):
            raise UserError('GitHub 只读请求地址被拒绝。')
        if payload is not None or headers and any(k.lower() in {'authorization','cookie'} for k in headers):
            raise UserError('公开仓库不使用 Token、Cookie 或写入请求。')
        # Core Transport already implements bounded reads/timeouts and NoRedirect.
        return super().open(url, headers=headers, authenticated=True)


def parse_url(url):
    if not isinstance(url,str) or len(url)>2048: raise UserError('请填写公开 GitHub 链接。')
    p=urllib.parse.urlsplit(url.strip())
    if p.scheme!='https' or p.hostname!='github.com' or p.username or p.password or p.port not in (None,443) or p.query or (p.fragment and not re.fullmatch(r'L\d+(?:-L\d+)?',p.fragment)):
        raise UserError('仅支持 https://github.com 的公开仓库地址；不支持私有仓库、登录或 Token。')
    parts=[urllib.parse.unquote(v) for v in p.path.strip('/').split('/')]
    if len(parts)<2 or any(not re.fullmatch(r'[\w.-]+',v,re.ASCII) or v in {'.','..'} for v in parts[:2]):
        raise UserError('仓库地址应为 owner/repository。')
    owner,name=parts[:2]; name=name.removesuffix('.git')
    if not name: raise UserError('仓库名称无效。')
    tail=parts[2:]
    if tail and (tail[0] not in {'tree','blob','commit'} or len(tail)<2): raise UserError('支持仓库首页、tree、blob 或 commit 链接。')
    if any(v in {'.','..',''} or '\\' in v or '\x00' in v for v in tail): raise UserError('GitHub 路径无效。')
    return owner,name,tail

class GitHubRepository:
    def __init__(self,transport,trees=None): self.transport=transport;self.trees=trees or {}
    def scan(self,url):
        owner,name,tail=parse_url(url)
        api=f'https://api.github.com/repos/{owner}/{name}'
        metadata=self.transport.json(api)
        if metadata.get('private') is True or not metadata.get('default_branch'):
            raise UserError('仅支持公开仓库；默认分支不可读，不支持登录或 Token。')
        # GitHub repository names are case insensitive. Prefer its canonical
        # spelling so alternate URL casing cannot create duplicate snapshots.
        canonical_owner=(metadata.get('owner') or {}).get('login',owner)
        canonical_name=metadata.get('name',name)
        if all(isinstance(v,str) and re.fullmatch(r'[\w.-]+',v,re.ASCII) for v in (canonical_owner,canonical_name)):
            owner,name=canonical_owner,canonical_name
            api=f'https://api.github.com/repos/{owner}/{name}'
        branch=metadata['default_branch']; scope=''; ref=branch
        if tail:
            if tail[0]=='commit': ref=tail[1]
            else:
                # Branch names may contain slashes. Resolve longest valid prefix,
                # with a hard budget instead of retrying an unavailable repository.
                segments=tail[1:]; commit=None
                for n in range(min(len(segments),8),0,-1):
                    candidate='/'.join(segments[:n])
                    try: commit=self.transport.json(api+'/commits/'+urllib.parse.quote(candidate,safe=''))
                    except UserError as exc:
                        if 'HTTP 404' in str(exc): continue
                        raise
                    ref=candidate; scope='/'.join(segments[n:]);break
                if commit is None: raise UserError('分支、commit 或路径不存在；不支持私有仓库。')
        if not tail or tail[0]=='commit': commit=self.transport.json(api+'/commits/'+urllib.parse.quote(ref,safe=''))
        sha=commit.get('sha','')
        if not re.fullmatch(r'[0-9a-fA-F]{40}',sha): raise UserError('GitHub 未返回有效的固定 commit。')
        tree=self.trees.get((owner.lower(),name.lower(),sha))
        if tree is None:tree=self.transport.json(api+'/git/trees/'+sha+'?recursive=1',10_000_000)
        if tree.get('truncated'): raise UserError('仓库目录树被 GitHub 截断，请选择较小仓库；未伪装为完整扫描。')
        entries=[v for v in tree.get('tree',[]) if v.get('type')=='blob']
        if len(entries)>10000: raise UserError('目录超过 10,000 个文件，第一版请选择较小仓库。')
        return {'owner':owner,'name':name,'commit':sha,'branch':branch,'ref':ref,'scope':scope,
                'url':f'https://github.com/{owner}/{name}','description':metadata.get('description') or '',
                'language':metadata.get('language') or '', 'commit_time':(commit.get('commit',{}).get('committer') or {}).get('date',''),
                'tree':entries}
    def read(self,repo,path,limit=120000):
        if not isinstance(path,str) or path not in {f['path'] for f in repo['tree']}: raise UserError('文件不在固定版本目录中。')
        url=f"https://raw.githubusercontent.com/{repo['owner']}/{repo['name']}/{repo['commit']}/"+urllib.parse.quote(path,safe='/')
        return self.transport.read(url) if limit==120000 else self.transport.read(url,limit)
