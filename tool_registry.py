"""Single registry for host and plugin tools.

The registry is intentionally dependency-free so core.py and chat.py can use
the same definitions without an import cycle.
"""
from __future__ import annotations
import json
import time

BUILTINS = [
    {'name':'search_github','description':'搜索公开 GitHub 仓库，元数据不是源码审阅。','parameters':{'type':'object','properties':{'query':{'type':'string'},'language':{'type':'string'}},'required':['query'],'additionalProperties':False},'output_format':'json','source':'builtin:github','permissions':['network']},
    {'name':'open_repository','description':'加载公开仓库首页的默认分支固定 commit、目录与 README。','parameters':{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False},'output_format':'text','source':'builtin:github','permissions':['network']},
    {'name':'list_repository_files','description':'按路径关键词筛选固定 commit 的仓库文件列表。','parameters':{'type':'object','properties':{'keyword':{'type':'string'}},'required':['keyword'],'additionalProperties':False},'output_format':'json','source':'builtin:source','permissions':['source_read']},
    {'name':'read_repository_file','description':'读取固定 commit 中一个文本文件的指定行。','parameters':{'type':'object','properties':{'path':{'type':'string'},'start_line':{'type':'integer'},'end_line':{'type':'integer'}},'required':['path','start_line','end_line'],'additionalProperties':False},'output_format':'text','source':'builtin:source','permissions':['source_read']},
    {'name':'read_repository_history','description':'读取固定 commit 之前的最近提交摘要。','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False},'output_format':'text','source':'builtin:source','permissions':['source_read']},
    {'name':'read_repository_discussion','description':'读取当前仓库已知编号的 Issue/PR 讨论。','parameters':{'type':'object','properties':{'number':{'type':'integer'}},'required':['number'],'additionalProperties':False},'output_format':'text','source':'builtin:source','permissions':['source_read']},
    {'name':'search_local_reports','description':'按标题搜索本机研究报告。','parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query'],'additionalProperties':False},'output_format':'json','source':'builtin:reports','permissions':['reports_read']},
    {'name':'read_local_report','description':'读取一份本机研究报告正文。','parameters':{'type':'object','properties':{'id':{'type':'integer'}},'required':['id'],'additionalProperties':False},'output_format':'json','source':'builtin:reports','permissions':['reports_read']},
    {'name':'read_learning_progress','description':'读取本机学习记录与用户自评进度。','parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False},'output_format':'json','source':'builtin:reports','permissions':['reports_read']},
    {'name':'search_materials','description':'检索用户明确授权的本地资料库。','parameters':{'type':'object','properties':{'query':{'type':'string'},'title_only':{'type':'boolean'},'tag':{'type':'string'},'project':{'type':'string'}},'required':['query'],'additionalProperties':False},'output_format':'json','source':'builtin:materials','permissions':['materials_read']},
]

def validate_schema(schema):
    if not isinstance(schema,dict) or schema.get('type')!='object' or not isinstance(schema.get('properties'),dict) or not isinstance(schema.get('required'),list):
        raise ValueError('工具参数 schema 必须是 object。')
    if any(not isinstance(k,str) or not isinstance(v,dict) for k,v in schema['properties'].items()):raise ValueError('工具属性 schema 无效。')
    if any(k not in schema['properties'] for k in schema['required']):raise ValueError('工具 required 字段无效。')
    if schema.get('additionalProperties') is not False or len(schema['properties'])>16:raise ValueError('参数必须拒绝未知字段，最多16项。')
    for value in schema['properties'].values():
        if value.get('type') not in {'string','integer','boolean'}:raise ValueError('第一版只支持字符串、整数、布尔参数。')

def openai_tool(spec):
    return {'type':'function','function':{'name':spec['name'],'description':spec['description'],'parameters':spec['parameters']}}

class ToolRegistry:
    def __init__(self,plugins=None):self.plugins=plugins
    def builtin(self,name=None):return [x for x in BUILTINS if name is None or x['name']==name]
    def all(self):return self.builtin()+([] if not self.plugins else self.plugins.tools(enabled_only=False))
    def public(self):return [{k:v for k,v in item.items() if k not in {'parameters'}}|{'parameter_schema':item['parameters']} for item in self.all()]
    def openai(self,tools=None):return [openai_tool(x) for x in (tools if tools is not None else self.all())]
    def call(self,name,args,permissions,allowed,handlers=None,brokers=None):
        from core import UserError, Cancelled
        started=time.perf_counter();status='denied';reason='本轮未授权或工具未启用';output=''
        tool=next((t for t in self.all() if t['name']==name),{'name':str(name)[:60],'source':'unknown','permissions':[]})
        try:
            if name not in allowed or tool['source']=='unknown':raise UserError('此工具未启用，无法访问。')
            if any(p not in permissions for p in tool['permissions']):raise UserError('权限拒绝：本轮未授权此工具。')
            schema=tool['parameters']
            if not isinstance(args,dict) or len(json.dumps(args,ensure_ascii=False))>40000:raise UserError('工具参数无效或过大。')
            if any(k not in args for k in schema['required']) or any(k not in schema['properties'] for k in args):raise UserError('工具参数缺少字段或有未知字段。')
            for key,value in args.items():
                typ=schema['properties'][key]['type']
                if not ((typ=='string' and isinstance(value,str)) or (typ=='integer' and type(value) is int) or (typ=='boolean' and type(value) is bool)):raise UserError('工具参数类型无效。')
                if isinstance(value,str) and len(value)>35000:raise UserError('单个工具参数最多35000字符。')
            if tool.get('plugin_id'):
                output=self.plugins.invoke(tool,args,permissions,brokers or {})
            else:
                handler=(handlers or {}).get(name)
                if not handler:raise UserError('此入口未提供该工具。')
                output=handler(args)
            if not isinstance(output,str):output=json.dumps(output,ensure_ascii=False)
            output=output[:18000];status='success';reason='执行完成';return output
        except Cancelled:
            status='cancelled';reason='用户取消';raise
        except UserError:
            # Host messages are bounded, but plugin payloads never become exception text.
            reason='权限、参数或读取范围不满足';return '工具未启用或权限/参数无效，无法访问。'
        except Exception as exc:
            status='error';reason='工具异常：'+type(exc).__name__
            if tool.get('plugin_id'):self.plugins.log(tool['plugin_id'],'error',reason+'；详情未回显，主程序继续运行。')
            return '插件或工具调用失败，主程序继续运行。'
        finally:
            if self.plugins:self.plugins.audit(tool,status,reason,args,output,(time.perf_counter()-started)*1000)
