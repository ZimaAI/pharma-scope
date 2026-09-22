#!/usr/bin/env python3
"""Offline DOM smoke tests for the prototype, NOT backend E2E tests.
Install playwright and a Chromium build; optionally set CHROMIUM_EXECUTABLE.
set_content intentionally avoids any network navigation. Browser persistent storage,
file:// browser policies, live APIs, accessibility certification are NOT validated.
"""
from pathlib import Path
import json, os, shutil
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parent
results=[]
def passed(name):
    results.append({'name':name,'status':'PASS'})
    print('PASS',name)
with sync_playwright() as p:
    exe=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
    kwargs={'headless':True,'args':['--no-sandbox']}
    if exe: kwargs['executable_path']=exe
    browser=p.chromium.launch(**kwargs)
    page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url))
    page.set_content((ROOT/'index.html').read_text(encoding='utf-8'))
    page.set_default_timeout(5000)
    def route(name):
        page.evaluate('(x)=>{location.hash=x;render();}',name)
        page.wait_for_timeout(90)
    def action(name):page.locator(f'button[data-action="{name}"], input[data-action="{name}"]').first.click()
    def screenshot(name):
        page.evaluate("document.querySelector('#toast-root').innerHTML=''")
        (ROOT/'previews').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/'previews'/name),full_page=True)
    expect(page.locator('#main h1')).to_contain_text('每一次进展')
    expect(page.locator('.modebar')).to_contain_text('DEMO')
    passed('Dashboard and always-visible demo boundary')
    screenshot('01-dashboard.png')
    for name in ['drugs','trials','changes','literature','research','reports','subscriptions','settings']:
        route(name);expect(page.locator('#main h1')).to_be_visible()
    passed('All nine primary navigation areas render')
    route('literature');action('evidence:paper-002');expect(page.locator('.drawer')).to_contain_text('DEMO-PM-002');expect(page.locator('#evidence-quote')).to_contain_text('PX-202');action('close')
    action('missing-abstract');expect(page.locator('.modal')).to_contain_text('摘要缺失');assert page.locator('#evidence-quote').count()==0;action('close')
    passed('Literature keeps correct drug identity and explicit missing abstract')
    route('dashboard');page.locator('#global-search').fill('PX-202');page.locator('#global-search').press('Enter')
    page.wait_for_timeout(250)
    expect(page.locator('#table-search')).to_have_value('PX-202')
    passed('Global search preserves query across navigation')
    route('drugs');action('new-drug');page.locator('#drug-name').fill('bad');action('create-drug')
    expect(page.locator('#toast-root')).to_contain_text('格式');expect(page.locator('.modal')).to_be_visible()
    page.locator('#drug-name').fill('PX-707');page.locator('#drug-desc').fill('<b>虚构对象</b>');action('create-drug')
    page.wait_for_timeout(150);expect(page.locator('#main')).to_contain_text('<b>虚构对象</b>')
    passed('Drug form validation, creation and HTML escaping')
    route('trials');page.locator('#status-filter').select_option('RECRUITING')
    assert page.locator('tbody tr').count()>0
    passed('Trial status filtering')
    route('trials/DEMO-CT-002');expect(page.locator('#main')).to_contain_text('仅基线样例')
    assert page.locator('[data-action="evidence:after"]').count()==0
    passed('Other trials do not reuse PX-101 evidence')
    route('changes/EV-01');expect(page.locator('.diff-content').first).to_contain_text('120')
    action('evidence:before');expect(page.locator('#evidence-quote')).to_have_text('120')
    expect(page.locator('.drawer')).to_contain_text('2026-09-15')
    page.keyboard.press('Escape');expect(page.locator('.drawer')).to_have_count(0)
    passed('Enrollment comparison and exact before evidence')
    action('diff:status');action('evidence:status-before');expect(page.locator('#evidence-quote')).to_have_text('RECRUITING');action('close')
    passed('Status evidence has the corresponding before value')
    route('changes/EV-04');expect(page.locator('.diff-content').nth(1)).to_contain_text('150')
    action('evidence:correction-after');expect(page.locator('#evidence-quote')).to_have_text('150');action('close')
    passed('Source correction 160 to 150 references its own snapshot')
    action('diff:reversion');expect(page.locator('.diff-content').first).to_contain_text('150');action('evidence:reversion-after')
    expect(page.locator('.drawer')).to_contain_text('2026-09-18');expect(page.locator('.drawer')).to_contain_text('2026-09-14');action('close')
    passed('Content reversion preserves new observation and old snapshot')
    route('changes/EV-03');expect(page.locator('#main')).to_contain_text('不能计算业务变化')
    assert page.locator('.diff-panel').count()==0
    passed('Baseline does not fabricate change differences')
    route('changes/EV-01');screenshot('02-changes.png')
    route('reports/REP-003');expect(page.locator('#main')).to_contain_text('早于09-16')
    assert page.locator('.cite').count()==0
    route('reports/REP-002');expect(page.locator('#main')).to_contain_text('不能借用PX-101')
    passed('Reports respect object identity and earlier knowledge cutoff')
    route('reports/REP-001');expect(page.locator('[data-action="approve:REP-001"]')).to_be_disabled()
    passed('Author approval is disabled in prototype')
    page.locator('#role-select').select_option('reviewer')
    expect(page.locator('[data-action="approve:REP-001"]')).to_be_disabled()
    page.locator('#review-confirm').check();expect(page.locator('[data-action="approve:REP-001"]')).to_be_enabled()
    screenshot('03-report-review.png')
    action('evidence:after');screenshot('04-evidence-drawer.png');action('close')
    action('approve:REP-001');expect(page.locator('[data-action="publish:REP-001"]')).to_be_visible()
    action('publish:REP-001');expect(page.locator('#main')).to_contain_text('没有发送邮件')
    action('inbox');expect(page.locator('.modal')).to_contain_text('已发布');action('close')
    passed('Independent review confirmation, approval, publish, mock inbox')
    with page.expect_download() as info: action('export:REP-001')
    download=info.value
    tmp=ROOT/'previews'/'export-test.md';download.save_as(tmp)
    content=tmp.read_text(encoding='utf-8');assert 'DEMO' in content and '120' in content;tmp.unlink()
    passed('Markdown export labels fictional data')
    route('research');action('new-run');page.locator('#run-q').fill('短');action('create-run')
    expect(page.locator('#toast-root')).to_contain_text('至少');page.locator('#run-q').fill('整理PX-101的登记变化，提供前后证据与缺口。');action('create-run')
    page.wait_for_timeout(150);action('start-run');page.wait_for_timeout(850*7+300)
    assert page.evaluate('state.runs[0].status')=='completed'
    assert page.evaluate('state.runs[0].reportId')
    screenshot('05-agent-run.png')
    passed('Validated task creation, seven-step offline replay and own draft')
    action('new-run');page.locator('#run-fault').check();action('create-run');page.wait_for_timeout(150);action('start-run');page.wait_for_timeout(850*7+300)
    assert page.evaluate('state.runs[0].status')=='partial'
    expect(page.locator('#main')).to_contain_text('不能据此声称没有新增文献')
    own=page.evaluate('state.runs[0].reportId');route('reports/'+own)
    expect(page.locator('#main')).to_contain_text('尚未完成PubMed核查')
    passed('Source failure yields partial with a per-report coverage gap')
    action('submit-review:'+own);page.locator('#review-confirm').check();action('reject:'+own)
    action('reject-confirm:'+own);expect(page.locator('.modal')).to_be_visible();page.locator('#review-note').fill('需要补充原始来源核查。');action('reject-confirm:'+own)
    expect(page.locator('#main')).to_contain_text('需修改')
    passed('Review rejection requires a reason')
    action('new-run');action('create-run');page.wait_for_timeout(100);action('start-run');page.wait_for_timeout(300);action('cancel-run')
    assert page.evaluate('state.runs[0].status')=='cancelled'
    passed('Replay cancellation stops its local timer')
    route('subscriptions');before=page.evaluate('state.subscriptions[0].enabled');action('toggle-sub:SUB-1')
    assert page.evaluate('state.subscriptions[0].enabled')!=before
    action('new-sub');page.locator('#sub-name').fill('我的虚构研发周报');action('create-sub');expect(page.locator('#main')).to_contain_text('我的虚构研发周报')
    passed('Subscription toggle and local creation')
    for val,txt in [('empty','暂无资料'),('error','来源请求未完成'),('denied','没有访问')]:
        page.locator('#scene').select_option(val);expect(page.locator('#main')).to_contain_text(txt)
    page.locator('#scene').select_option('loading');expect(page.locator('.skeleton').first).to_be_visible()
    page.locator('#scene').select_option('normal')
    passed('Loading, empty, failure and denied component states')
    action('new-run');page.locator('.modal button').last.focus();page.keyboard.press('Tab')
    assert page.evaluate('!!document.activeElement.closest(".modal")')
    page.keyboard.press('Escape');expect(page.locator('.modal')).to_have_count(0)
    passed('Modal keyboard focus containment and Escape close')
    for width in [1440,1024,390]:
        page.set_viewport_size({'width':width,'height':900})
        for name in ['dashboard','changes/EV-01','reports/REP-001']:
            route(name)
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'),(width,name)
        if width==390:
            route('dashboard');action('menu');expect(page.locator('#sidebar')).to_have_class('sidebar open')
            page.locator('#sidebar [data-nav="trials"]').click();page.wait_for_timeout(100)
            screenshot('06-mobile.png')
    passed('1440 / 1024 / 390 layouts without document overflow; mobile navigation')
    page.set_viewport_size({'width':1440,'height':1000});route('settings');action('reset');action('confirm-reset');page.wait_for_timeout(150)
    assert page.evaluate('state.runs.length')==0 and page.evaluate('state.drugs.length')==6
    passed('Reset restores deterministic fixture state')
    assert not errors,errors
    passed('No uncaught JavaScript page errors')
    assert not [u for u in requests if u.startswith(('https://','http://'))],requests
    passed('No HTTP requests during prototype interaction tests')
    report={'type':'offline DOM prototype smoke test','date':'2026-09-22','browser':browser.version,'method':'Playwright set_content; no network navigation','passed':len(results),'checks':results,'page_errors':errors,'http_requests':[],'not_tested':['Real backend or OpenAPI endpoints','Real model or clinical sources','Browser persistent storage/file URL policies','Real security authorization','Production deployment or server peak memory','Comprehensive accessibility audit']}
    (ROOT.parent/'delivery/prototype-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    browser.close()
print(f'Completed {len(results)} checks; this is not a backend test.')
