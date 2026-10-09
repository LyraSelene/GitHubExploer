from pathlib import Path
import json,hashlib
from PyInstaller.archive.readers import CArchiveReader
root=Path(__file__).resolve().parents[1];exe=root/'dist-ui/InfraResearcher.exe';archive=CArchiveReader(str(exe))
checks={p.name:archive.extract('static\\'+p.name)==p.read_bytes() for p in (root/'static').iterdir() if p.is_file()}
assert all(checks.values()),checks
result={'static_files':len(checks),'matches':all(checks.values()),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'size':exe.stat().st_size,'mtime':exe.stat().st_mtime}
(root/'build/water-actions/package.json').write_text(json.dumps(result,indent=2));print(result)
