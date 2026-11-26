from pathlib import Path
import hashlib,json,os,subprocess,urllib.request,urllib.error

ROOT=Path(__file__).resolve().parents[1]
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result is not None:
            from urllib.parse import urlsplit
            if urlsplit(req.full_url).netloc!=urlsplit(newurl).netloc:
                result.remove_header('Authorization')
        return result

def main():
    rows=json.loads((ROOT/'model-manifest.json').read_text(encoding='utf-8'))
    missing=[r for r in rows if not (ROOT/r['path']).is_file() or (ROOT/r['path']).stat().st_size!=r['bytes']]
    if not missing:
        print('모델 파일이 준비되어 있습니다.');return
    config_path=ROOT/'github-repository.json'
    if not config_path.exists():raise SystemExit('GitHub 저장소 설정이 아직 준비되지 않았습니다.')
    config=json.loads(config_path.read_text(encoding='utf-8'))
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
        try:
            result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=env,timeout=15)
            creds=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
            token=creds.get('password')
        except (OSError,subprocess.TimeoutExpired):pass
    if not token:raise SystemExit('비공개 모델 다운로드에는 GitHub 로그인이 필요합니다. Git Credential Manager로 로그인하거나 릴리스 파일을 직접 받아주세요.')
    opener=urllib.request.build_opener(SafeRedirect())
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'photo-verification-setup'}
    try:
        url='https://api.github.com/repos/'+config['repository']+'/releases/tags/'+config['model_tag']
        with opener.open(urllib.request.Request(url,headers=headers),timeout=60) as response:release=json.load(response)
        available={a['name']:a for a in release['assets']}
        for row in missing:
            asset=available.get(row['asset'])
            if not asset:raise SystemExit('릴리스에 모델이 없습니다: '+row['asset'])
            target=ROOT/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
            partial=target.with_name(target.name+'.part')
            print('모델 다운로드: '+row['asset'],flush=True)
            digest=hashlib.sha256();size=0
            with opener.open(urllib.request.Request(asset['url'],headers=dict(headers,Accept='application/octet-stream')),timeout=120) as source,partial.open('wb') as output:
                while chunk:=source.read(1024*1024):output.write(chunk);digest.update(chunk);size+=len(chunk)
            if size!=row['bytes'] or digest.hexdigest()!=row['sha256']:
                partial.unlink(missing_ok=True);raise SystemExit('모델 검증 실패: '+row['asset'])
            partial.replace(target)
    except urllib.error.HTTPError as error:
        raise SystemExit('GitHub 모델 다운로드 실패(HTTP '+str(error.code)+'). 저장소 접근 권한과 릴리스를 확인해주세요.') from None
if __name__=='__main__':main()
