from pathlib import Path
import secrets,shutil
root=Path(__file__).resolve().parents[1]
if not (root/'.env').exists():shutil.copyfile(root/'.env.example',root/'.env')
p=root/'Admin/Backend/.env'
if not p.exists():
 text=(root/'Admin/Backend/.env.example').read_text(encoding='utf-8')
 p.write_text(text+'SECRET_KEY='+secrets.token_urlsafe(48)+'\n',encoding='utf-8')
print('Local configuration ready. Existing keys were preserved.')
