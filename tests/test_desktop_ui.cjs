// Exercise asynchronous state transitions in the shipped UI, without a browser.
// The DOM/rendering and network are mocked; the actual import/run logic executes.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

test('file loading, submitted versions, immediate completion and safe exit', async () => {
  const nodes = new Map();
  const document = {
    querySelector: () => ({content: 'test'}),
    querySelectorAll: () => [],
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {
        value: 'Protein ID', hidden: false, open: false,
        setAttribute(name,value) { this[name]=value; },
        focus() { this.focused=true; },
        close() { this.open = false; }
      });
      return nodes.get(id);
    }
  };
  const source = fs.readFileSync(path.join(__dirname,'../desktop_ui/app.js'), 'utf8')
    .replace('safe(init)();', '')
    .replace('const api =', 'let api =');
  await vm.runInNewContext(source + `
  (async () => {
    const originalNotify=notify;
    renderResults=()=>{}; renderPreview=()=>{}; updateMode=()=>{};
    notify=()=>{}; changeView=()=>{}; startPolling=()=>{}; settings=()=>({});
    state={revision:1,results:{data:[[1]]},
      job:{status:'done',total:1,completed:1,message:''}};
    draft={columns:['Protein ID'],data:[['P00533']]};
    draftVersion=1; runDraftVersion=1; lastJob='done';
    let finishImport, submitted=[];
    request=async()=>new Promise(resolve=>{finishImport=resolve});
    api=async(path,payload)=>{
      submitted.push(payload.input.data[0][0]);
      return {...state,job:{status:'running',total:1,completed:0,message:''}};
    };
    const file=name=>({size:10,name,arrayBuffer:async()=>new ArrayBuffer(0)});
    const loading=loadFile(file('new.csv'));
    await Promise.resolve(); await Promise.resolve();
    assert.equal($('run').disabled,true);
    await assert.rejects(run(),/読み込み完了/);
    assert.equal(submitted.length,0);
    finishImport({json:async()=>({columns:['Protein ID'],data:[['P04637']]})});
    await loading;
    assert.equal(importing,false);
    assert.equal($('run').disabled,false);
    assert.equal(draft.data[0][0],'P04637');

    await run();
    const submittedVersion=draftVersion;
    draft={columns:['Protein ID'],data:[['OTHER']]}; changed();
    acceptState({...state,revision:2,
      job:{status:'done',total:1,completed:1,message:''}});
    assert.equal(runDraftVersion,submittedVersion);
    assert.equal($('stale').hidden,false);

    const keptDraft=draft;
    const superseded=loadFile(file('late.csv'));
    await Promise.resolve(); await Promise.resolve();
    switchInput('demo');
    finishImport({json:async()=>({columns:['Protein ID'],data:[['LATE']]})});
    await superseded;
    assert.equal(draft,keptDraft);
    assert.equal(importing,false);

    // Offline work may finish before the start request returns.
    api=async()=>({...state,revision:3,job:{status:'done',total:1,completed:1,message:''}});
    await run();
    assert.equal(runDraftVersion,draftVersion);
    assert.equal($('stale').hidden,true);

    // Starting a download must not immediately discard the in-memory work.
    let downloads=0, shutdowns=0;
    download=async()=>{downloads++};
    api=async()=>{shutdowns++};
    await quit(true);
    assert.equal(downloads,1);
    assert.equal(shutdowns,0);
    assert.match($('quit-help').textContent,/JSONを確認/);

    // Errors remain visible and focusable inside the active modal.
    $('detail-dialog').open=true;
    originalNotify('保存に失敗しました。再試行してください。',true);
    assert.equal($('detail-error').hidden,false);
    assert.equal($('detail-error').role,'alert');
    assert.equal($('detail-error').focused,true);
    assert.match($('detail-error').textContent,/保存に失敗/);
    $('detail-dialog').open=false;
    originalNotify('IDを入力してください。',true);
    assert.equal($('notice').role,'alert');
    assert.equal($('notice').focused,true);
  })();
  `, {document, assert, console, setTimeout});
});
