# Final read-only checks and application link
import html, requests
from IPython.display import HTML, display
assert startup.report.get('SYSTEM_READY') == 'YES', 'Startup has not completed'
base='http://127.0.0.1:8501'
r=requests.get(base+'/startup-health',timeout=20); r.raise_for_status()
workers=r.json()
for key in ('notification_worker','persistence_worker'):
    assert workers.get(key)=='RUNNING', key+' not running'
    print(key+'=RUNNING')
schema=requests.get(base+'/openapi.json',timeout=20); schema.raise_for_status()
assert 'post' in schema.json()['paths'].get('/api/agent/chat',{}), 'Agent chat API missing'
print('agent_api_schema=PASS')
source=requests.get(base+'/api/source_status',timeout=20); source.raise_for_status()
print('source_status_api=PASS')
print('SYSTEM_READY=YES')
url=startup.report['ui_url']
print('DATT_UI_URL='+url)
display(HTML('<a target="_blank" href="'+html.escape(url,quote=True)+'">OPEN DATT</a>'))
