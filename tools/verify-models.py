from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parents[1]
for row in json.loads((root/'model-manifest.json').read_text(encoding='utf-8')):
 p=root/row['path']
 if not p.is_file():raise SystemExit('Missing model: '+row['path']+'\nUse the full shared archive, not the code-only archive.')
 if p.stat().st_size!=row['bytes']:raise SystemExit('Model size mismatch: '+row['path'])
 with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 if actual!=row['sha256']:raise SystemExit('Model checksum mismatch: '+row['path'])
print('All required model files verified.')
