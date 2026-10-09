"""Read only staged blobs; never print potential credential values."""
from pathlib import Path
import subprocess,re,json
root=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git',*args],cwd=root)
paths=[p for p in git('diff','--cached','--name-only','-z').decode('utf8').split('\0') if p]
forbidden=[];findings=[];total=0
patterns=[
 re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})\b'),
 re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
 re.compile(rb'https?://[A-Za-z0-9._~%+-]+:[A-Za-z0-9._~%+-]+@'),
]
for path in paths:
 p=Path(path)
 if p.suffix.lower() in ['.sqlite','.sqlite3','.db','.exe','.apk','.jks','.key','.pem'] or p.name.startswith('.env') or path.startswith(('dist','__pycache__','data/')):forbidden.append(path)
 blob=git('show',':'+path);total+=len(blob)
 if len(blob)>90*1024*1024:forbidden.append(path+' (size)')
 if b'\0' not in blob:
  for i,line in enumerate(blob.splitlines(),1):
   # Exact, inspected negative-test fixtures: neither contains a real secret.
   example_url=b'http://'+b'user:pass'+b'@192.168.1.5:80/'
   example_key=b"return_value=b'-----BEGIN "+b"PRIVATE KEY-----\\nsecret'"
   fixture=(path=='android/AddressPolicyCheck.java' and example_url in line) or (path=='test_github_import.py' and example_key in line)
   if not fixture and any(pattern.search(line) for pattern in patterns):findings.append({'file':path,'line':i})
result={'files':len(paths),'bytes':total,'forbidden_paths':forbidden,'credential_pattern_matches':findings}
print(json.dumps(result,ensure_ascii=False))
assert not forbidden and not findings,'Review staged backup before committing'
