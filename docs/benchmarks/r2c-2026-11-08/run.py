import subprocess, os, sys
for renderer in ('1','0'):
    with open(f'.r2-tmp/{sys.argv[1]}-{renderer}.log','w') as log:
        try:
            result = subprocess.run(['.venv-work/bin/python','.r2-tmp/measure.py'], env=dict(os.environ, PYTHONPATH=os.getcwd(), INGETRAZO_PERF='1', INGETRAZO_WGPU=renderer),stdout=log,stderr=log,timeout=240)
            log.write(f'\nPROCESS_EXIT {result.returncode}\n')
        except subprocess.TimeoutExpired:
            log.write('\nTIMEOUT 240s\n')
