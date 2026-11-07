'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="paia-token"]').content;
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const clear = node => node.replaceChildren();
let config, state, draft = null, inputMode = 'type', view = 'input', attrSet = new Set(), visible = [], columns = [], sortBy = 'Query ID', sortDir = 1, page = 0, detailRow = null, lastJob = '', draftVersion = 0, runDraftVersion = -1;
let polling = false, pending = false, importing = false, importSequence = 0, submittedDraftVersion = null;
const names = {'Query ID':'入力ID','Accession':'UniProt ID','Mapping Status':'照合状態','Gene Name':'遺伝子名','Protein Name':'タンパク質名','Organism':'生物種','Protein Function':'機能','Molecular Weight (Da)':'分子量 (Da)','Isoelectric Point (pI)':'理論等電点 (pI)','Sequence Length':'配列長','Subcellular Localization':'細胞内局在','Tissue Specificity':'組織特異性','Kinase Activity':'キナーゼ','Zinc-Binding Sites':'亜鉛結合部位','Metal-Binding Sites':'金属結合部位','Phosphorylation Sites':'リン酸化部位','Disulfide Bonds':'ジスルフィド結合','Glycosylation Sites':'糖鎖修飾部位','Signal Peptide':'シグナルペプチド','Transmembrane Regions':'膜貫通領域','DNA-Binding Domains':'DNA結合領域','Active Sites':'活性部位','Coiled-Coil Regions':'コイルドコイル','Receptor':'受容体','Secreted Protein':'分泌タンパク質','Cell Adhesion':'細胞接着','Transporter / Channel':'輸送体・チャネル','Enzyme':'酵素','Transcription Factor':'転写因子','Protease':'プロテアーゼ','Cytokine / Growth Factor':'サイトカイン・増殖因子','Structural Protein':'構造タンパク質','Immune-Related':'免疫関連','Topological Domains':'トポロジー領域','GO Molecular Function':'GO：分子機能','GO Biological Process':'GO：生物学的過程','GO Cellular Component':'GO：細胞構成要素','Protein Domains':'ドメイン','Protein Families':'ファミリー','InterPro Entries':'InterPro登録','Pfam Entries':'Pfam登録','PTM Details':'翻訳後修飾の詳細','Lipidation Sites':'脂質修飾部位','Glycoprotein Annotation':'糖タンパク質の根拠','Membrane Location':'膜の局在','Extracellular Regions':'細胞外領域','Cell Surface Candidate':'細胞表面候補','Species Match':'生物種の対応','Taxonomy ID':'Taxonomy ID','Candidate Count':'候補数','InterPro Status':'InterPro取得状態','Retrieved At':'取得日時','Reviewed':'レビュー済み','Data Mode':'データの取得元'};
const statusNames = {'Matched':'一致','Not found':'不一致','Needs review':'候補の確認が必要','Fetch error':'通信エラー','Invalid query':'クエリを確認','Needs isoform review':'アイソフォーム要確認','Empty input':'空欄'};
const categoryNames = {'Physicochemical':'物理化学的性質','Functional / Structural':'機能・構造','Biological Classification':'生物学的分類','Spatial':'局在・組織','General Info':'基本情報','GO / Domains':'GO・ドメイン','PTM Details':'翻訳後修飾','Membrane / Surface':'膜・細胞表面'};
const friendly = key => names[key] || key;
const textValue = value => value === null || value === undefined || value === '' ? '—' : typeof value === 'boolean' ? (value ? '根拠あり' : '登録根拠なし') : typeof value === 'object' ? JSON.stringify(value) : String(value);
function notify(message, error = false) {
  const inline = error && ($('detail-dialog').open ? $('detail-error') : $('quit-dialog').open ? $('quit-error') : null);
  const target = inline || $('notice');
  target.setAttribute('role',error ? 'alert' : 'status');
  target.setAttribute('aria-live',error ? 'assertive' : 'polite');
  target.textContent = message; target.hidden = false;
  if (!inline) target.className = error ? 'error' : '';
  if (error) { target.tabIndex=-1; target.focus({preventScroll:false}); }
}
async function request(path, value, rawHeaders) {
  const headers = {'X-PAIA-Token':token, ...(rawHeaders || {})};
  const options = {headers};
  if (value !== undefined) { options.method = 'POST'; options.body = rawHeaders ? value : JSON.stringify(value); if (!rawHeaders) headers['Content-Type'] = 'application/json'; }
  let response;
  try { response = await fetch(path, options); } catch (_) { throw new Error('アプリに接続できません。起動用ウィンドウを確認してください。'); }
  if (!response.ok) { let error; try { error = (await response.json()).error; } catch (_) {} throw new Error(error || '操作に失敗しました。再試行してください。'); }
  return response;
}
const api = async (path, value) => (await request(path, value)).json();
function safe(fn) { return async (...args) => { try { await fn(...args); } catch (err) { notify(err.message, true); } }; }
function changeView(next, focus = true) {
  view = next;
  for (const v of ['input','results','guide']) $('view-' + v).hidden = v !== next;
  document.querySelectorAll('[data-view]').forEach(b => { b.classList.toggle('active',b.dataset.view === next); b.setAttribute('aria-current', b.dataset.view === next ? 'page' : 'false'); });
  $('breadcrumb').textContent = 'ワークスペース / ' + {input:'入力と設定',results:'結果を探索',guide:'使い方'}[next];
  if (focus) {
    $('main').focus({preventScroll:true});
    window.scrollTo({top:0,behavior:'instant'});
  }
}
function changed() { draftVersion++; $('stale').hidden = !state?.results.data.length || draftVersion === runDraftVersion; }
function setOptions(node, values, placeholder) {
  clear(node);
  if (placeholder !== undefined) { const o = el('option',placeholder); o.value = ''; node.append(o); }
  for (const [value,label] of values) { const o = el('option',label); o.value = value; node.append(o); }
}
function updateRunButton() { $('run').disabled = importing || pending || ['running','cancelling'].includes(state?.job.status); }
function switchInput(next, keepImport = false) {
  if (!keepImport) { importSequence++; importing=false; updateRunButton(); }
  inputMode = next;
  for (const v of ['type','file','demo']) { $('pane-'+v).hidden = v !== next; $('tab-'+v).setAttribute('aria-selected',String(v === next)); $('tab-'+v).tabIndex = v === next ? 0 : -1; }
  if (next === 'type') updateTyped(); else renderPreview();
}
function updateTyped() {
  const value = $('ids').value;
  draft = value.length ? {columns:['Protein ID'],data:value.replace(/\r\n?/g,'\n').split('\n').map(v => [v])} : null;
  renderPreview(); changed();
}
function renderPreview(preferred) {
  $('input-preview').hidden = !draft;
  if (!draft) return;
  const previous = preferred || $('id-column').value;
  setOptions($('id-column'),draft.columns.map(v => [v,v]));
  if (draft.columns.includes(previous)) $('id-column').value = previous;
  const index = draft.columns.indexOf($('id-column').value);
  const ids = draft.data.map(row => String(row[index] ?? '').trim()), nonempty = ids.filter(Boolean), unique = new Set(nonempty).size;
  clear($('input-stats'));
  for (const [label,count] of [['入力行',ids.length],['種類のID',unique],['重複行',nonempty.length-unique],['空欄行',ids.length-nonempty.length]]) { const s = el('span'); s.append(el('strong',count.toLocaleString()),el('span',label)); $('input-stats').append(s); }
  const table = $('preview-table'); clear(table); const head = el('thead'), tr = el('tr'); draft.columns.forEach(c=>tr.append(el('th',c))); head.append(tr); table.append(head);
  const body = el('tbody'); for (const row of draft.data.slice(0,5)) { const r=el('tr'); row.forEach(v=>r.append(el('td',v ?? ''))); body.append(r); } table.append(body);
}
function settings() { return {mode:$('mode').value, organism_id:$('species').value === 'custom' ? $('custom-species').value.trim() : $('species').value,id_type:$('id-type').value,attrs:[...attrSet]}; }
function applySettings(value) {
  $('mode').value = value.mode; $('id-type').value = value.id_type;
  const standard = ['9606','10090','10116',''].includes(value.organism_id);
  $('species').value = standard ? value.organism_id : 'custom'; $('custom-species').value = standard ? '' : value.organism_id; $('custom-species-wrap').hidden = standard;
  attrSet = new Set(value.attrs); renderAttributes(); updateMode();
}
function renderAttributes() {
  clear($('attributes'));
  for (const [category,attrs] of Object.entries(config.categories)) {
    const group = el('div',undefined,'attribute-group'); group.append(el('h3',categoryNames[category] || category));
    for (const attr of attrs) { const label=el('label'), box=el('input'); box.type='checkbox'; box.checked=attrSet.has(attr); box.addEventListener('change',()=>{ box.checked?attrSet.add(attr):attrSet.delete(attr); updateAttrSummary(); changed(); }); label.append(box,el('span',friendly(attr))); group.append(label); }
    $('attributes').append(group);
  }
  updateAttrSummary();
}
function updateAttrSummary() {
  $('attribute-count').textContent = attrSet.size + ' 項目';
  const list = [...attrSet]; $('preset-summary').textContent = list.slice(0,5).map(friendly).join(' · ') + (list.length > 5 ? ' ほか' + (list.length-5) + '項目' : '');
  const match=Object.entries(config.presets).find(([,a])=>{const all=a || Object.values(config.categories).flat();return all.length===attrSet.size && all.every(v=>attrSet.has(v));});
  $('preset').value = match ? match[0] : 'custom';
}
function updateMode() { $('mode-help').textContent = $('mode').value === 'offline' ? '保存済みの5種類のタンパク質だけを照合します。最新データではありません。' : 'IDをUniProt / InterProに送信します。最新データの取得にはネット接続が必要です。'; }
async function loadDemo() {
  const sequence=++importSequence; importing=true; updateRunButton();
  try {
    const loaded=await api('/api/demo'); if(sequence!==importSequence) return;
    draft=loaded; switchInput('demo',true); $('mode').value = 'offline'; updateMode(); renderPreview('Protein ID'); changed();
    notify('サンプル8行を読み込みました。「アノテーションを実行」で結果を確認できます。');
  } finally { if(sequence===importSequence){importing=false;updateRunButton();} }
}
async function loadFile(file) {
  if (!file) return;
  const sequence=++importSequence;
  importing=true;updateRunButton();notify('ファイルを読み込んでいます…');
  try {
    if (file.size > 24*1024*1024) throw new Error('ファイルは24MB以下にしてください。');
    const response = await request('/api/import',await file.arrayBuffer(),{'X-PAIA-Filename': 'input' + (file.name.match(/\.[^.]+$/)?.[0] || '')});
    const loaded = await response.json();
    if(sequence!==importSequence) return;
    draft = loaded; switchInput('file',true); $('filename').textContent = file.name; renderPreview(); changed(); notify('ファイルを読み込みました。IDが入った列を確認してください。');
  } finally { if(sequence===importSequence){importing=false;updateRunButton();} }
}
function resultRows() { return state.results.data.map((row,index)=>({...Object.fromEntries(state.results.columns.map((c,i)=>[c,row[i]])),index})); }
function renderResults() {
  const rows = resultRows(), matched=rows.filter(r=>r['Mapping Status']==='Matched').length;
  $('nav-count').textContent=rows.length; $('result-content').hidden=!rows.length; $('empty-results').hidden=!!rows.length; $('save-project').disabled=!rows.length;
  if(!rows.length) return;
  $('result-subtitle').textContent=`${state.stats.rows.toLocaleString()}行の入力から、${state.stats.unique.toLocaleString()}種類のIDを解析しました。`;
  clear($('metrics'));
  for(const [label,count,note,accent] of [['入力行',state.stats.rows,'重複・空欄を含む'],['一致したID',matched,`/ ${rows.length} 種類`,true],['確認が必要',rows.length-matched,'不一致・候補・エラー'],['取得項目',state.settings.attrs.length,'選択した注釈']]) {
    const item=el('div',undefined,'metric'+(accent?' metric-accent':'')); item.append(el('div',label,'metric-label')); const val=el('div',count.toLocaleString(),'metric-value'); val.append(el('span',note)); item.append(val); $('metrics').append(item);
  }
  const offline=state.settings.mode==='offline';
  $('provenance-banner').textContent=offline?'保存済みの公開サンプルデータです。新しいデータを取得した結果ではありません。':'公開データベースから取得しました。取得時点の登録情報と根拠をご確認ください。';
  $('run-time').textContent='最終実行：'+(state.created_at?new Date(state.created_at).toLocaleString('ja-JP'):'不明')+' · 元の空欄 '+state.stats.empty+'行 · 重複 '+state.stats.duplicates+'行';
  setOptions($('status-filter'),[...new Set(rows.map(r=>r['Mapping Status']))].map(v=>[v,statusNames[v]||v]),'すべての状態');
  setOptions($('location-filter'),[...new Set(rows.flatMap(r=>(r['Subcellular Localization']||'').split(';').map(v=>v.trim()).filter(Boolean)))].sort().map(v=>[v,v]),'すべての局在');
  setOptions($('class-filter'),config.boolean_attrs.filter(c=>state.results.columns.includes(c)).map(c=>[c,friendly(c)]),'すべての分類');
  setOptions($('numeric-filter'),config.numeric_attrs.filter(c=>state.results.columns.includes(c)).map(c=>[c,friendly(c)]),'指定なし');
  columns=['Query ID','Gene Name','Protein Name','Mapping Status','Molecular Weight (Da)','Subcellular Localization'].filter(c=>state.results.columns.includes(c));
  clear($('columns'));
  for(const c of state.results.columns) { const label=el('label'),check=el('input'); check.type='checkbox'; check.checked=columns.includes(c); check.addEventListener('change',()=>{ columns=check.checked?[...columns,c]:columns.filter(v=>v!==c); filterTable(); }); label.append(check,el('span',friendly(c))); $('columns').append(label); }
  resetFilters();
}
function resetFilters() { for(const id of ['search','status-filter','location-filter','class-filter','numeric-filter','numeric-min','numeric-max']) $(id).value=''; page=0; filterTable(); }
function filterTable() {
  const term=$('search').value.trim().toLocaleLowerCase(), status=$('status-filter').value, loc=$('location-filter').value, cls=$('class-filter').value,num=$('numeric-filter').value, low=$('numeric-min').value, high=$('numeric-max').value;
  visible=resultRows().filter(r=>(!term||Object.entries(r).some(([k,v])=>k!=='index' && String(v??'').toLocaleLowerCase().includes(term)))&&(!status||r['Mapping Status']===status)&&(!loc||(r['Subcellular Localization']||'').split(';').map(v=>v.trim()).includes(loc))&&(!cls||r[cls]===true)&&(!num||((r[num]!==null && r[num]!==undefined && r[num]!=='') && Number.isFinite(Number(r[num])) && (low===''||Number(r[num])>=Number(low))&&(high===''||Number(r[num])<=Number(high)))));
  visible.sort((a,b)=>{const av=a[sortBy],bv=b[sortBy];return sortDir*(typeof av==='number'&&typeof bv==='number'?av-bv:String(av??'').localeCompare(String(bv??''),'ja',{numeric:true}));});
  const pages=Math.max(1,Math.ceil(visible.length/50));page=Math.min(page,pages-1);
  $('visible-count').textContent=`${visible.length} / ${state.results.data.length} 種類のIDを表示`;
  $('export-filtered').disabled=!visible.length;
  const table=$('results-table');clear(table);const head=el('thead'),tr=el('tr');tr.append(el('th','詳細'));
  for(const c of columns) {const th=el('th'),button=el('button',friendly(c)+(sortBy===c?(sortDir===1?' ↑':' ↓'):''));th.setAttribute('scope','col');if(sortBy===c)th.setAttribute('aria-sort',sortDir===1?'ascending':'descending');button.title=c;button.addEventListener('click',()=>{sortDir=sortBy===c?-sortDir:1;sortBy=c;filterTable();});th.append(button);tr.append(th);}head.append(tr);table.append(head);
  const body=el('tbody');
  for(const row of visible.slice(page*50,(page+1)*50)) {
    const line=el('tr'),first=el('td'),button=el('button','詳細','detail-link');button.setAttribute('aria-label',String(row['Query ID'])+' の詳細');button.addEventListener('click',safe(()=>showDetail(row.index)));first.append(button);line.append(first);
    for(const c of columns){const td=el('td');if(c==='Mapping Status'){td.append(el('span',statusNames[row[c]]||row[c],'badge'+(row[c]==='Matched'?'':row[c]==='Fetch error'?' error':' warning')));}else{td.textContent=textValue(row[c]);td.title=textValue(row[c]);if(c==='Query ID')td.className='id-cell';}line.append(td);}body.append(line);
  }
  if(!visible.length){const td=el('td','条件に一致するタンパク質はありません。条件を解除すると全件に戻れます。');td.colSpan=columns.length+1;const line=el('tr');line.append(td);body.append(line);}
  table.append(body);$('page-info').textContent=`${page+1} / ${pages}`;$('prev').disabled=page===0;$('next').disabled=page>=pages-1;
  renderChart();
}
function renderChart(){const counts=new Map();visible.filter(r=>r['Mapping Status']==='Matched').forEach(r=>new Set((r['Subcellular Localization']||'').split(';').map(v=>v.trim()).filter(Boolean)).forEach(v=>counts.set(v,(counts.get(v)||0)+1)));clear($('location-chart'));const top=[...counts].sort((a,b)=>b[1]-a[1]).slice(0,6),max=top[0]?.[1]||1;if(!top.length)$('location-chart').append(el('p','局在の登録情報がありません。','help'));for(const [name,n]of top){const row=el('div',undefined,'bar-row'),track=el('div',undefined,'bar-track'),bar=el('div',undefined,'bar-fill');bar.style.width=(n/max*100)+'%';track.append(bar);row.append(el('span',name),track,el('span',n));row.title=name+': '+n; $('location-chart').append(row);}}
async function showDetail(index){
  const revision=state.revision;
  const row=await api('/api/detail/'+index+'?revision='+revision);
  if(state.revision!==revision)throw new Error('結果が更新されました。最新の一覧から詳細を開いてください。');
  detailRow=row;$('detail-error').hidden=true;clear($('detail-body'));$('detail-title').textContent=row['Gene Name']||row['Query ID'];
  const body=$('detail-body');body.append(el('p',row['Protein Name']||'対応するタンパク質は未確定です。'));body.append(el('p',`${row['Query ID']} · ${statusNames[row['Mapping Status']]||row['Mapping Status']} · ${row['Organism']||'生物種未確定'}`,'detail-meta'));
  if(row['Data Mode'])body.append(el('p',row['Data Mode'],'data-banner'));
  if(String(row['Species Match']).includes('Different'))body.append(el('p','選択した生物種と異なるIDです。意図したタンパク質か確認してください。','data-banner warn'));
  if(String(row['InterPro Status']).startsWith('Fetch error'))body.append(el('p','InterProの取得に失敗しました。欠落は性質がないことを示しません。','data-banner warn'));
  if(row['Mapping Status']==='Needs review'){
    const wrap=el('div',undefined,'candidate-box'),label=el('label','候補を選択して対応を確定（自動選択しません）'),select=el('select');select.id='candidate-choice';label.htmlFor=select.id;
    setOptions(select,(row._candidates||[]).map(c=>[c.primaryAccession,`${c.primaryAccession} · ${c.proteinDescription?.recommendedName?.fullName?.value||''} · ${c.organism?.scientificName||''}`]),'未確定のまま');
    const confirm=el('button','この候補で確定','primary compact');confirm.disabled=true;select.addEventListener('change',()=>{confirm.disabled=!select.value;});confirm.addEventListener('click',safe(async()=>{pending=true;confirm.disabled=true;try{const result=await api('/api/resolve',{revision,query_id:row['Query ID'],index,accession:select.value});$('detail-dialog').close();acceptState(result);startPolling();}finally{pending=false;confirm.disabled=!select.value;}}));
    wrap.append(label,select,el('p',`${row['Candidate Count']}件の候補のうち ${(row._candidates||[]).length}件を表示しています。見つからなければ入力を絞り込んでください。`,'help'),confirm);body.append(wrap);
  }
  if(row['Mapping Status']==='Matched'){
    if(/^https:\/\/www\.uniprot\.org\/uniprotkb\/[A-Z0-9-]+\/entry$/.test(row['UniProt URL']||'')){const link=el('a','UniProtで出典を開く');link.href=row['UniProt URL'];link.target='_blank';link.rel='noopener noreferrer';body.append(link);}
    body.append(el('p',`取得日時：${row['Retrieved At']||'不明'} · UniProt ${row['UniProt Release']||'版情報なし'} · Entry ${row['Entry Version']||'不明'}`,'detail-meta'));
    const dl=el('dl');for(const attr of state.settings.attrs){dl.append(el('dt',friendly(attr)),el('dd',textValue(row[attr])));}body.append(dl);
    const records=row._annotation_records||[],d=el('details'),summary=el('summary',`出典・根拠を確認（${records.length}件）`);d.append(summary);
    // Large evidence blocks stay collapsed until requested; textContent never executes imported markup.
    const pre=el('pre',JSON.stringify(records,null,2));d.append(pre);body.append(d);
    body.append(el('p','レビュー済みはデータベースの校閲状態です。すべての注釈に実験根拠があることを意味しません。','evidence-note'));
  }
  if(!$('detail-dialog').open)$('detail-dialog').showModal();
}
async function download(path,payload,filename){const response=await request(path,payload),blob=await response.blob();saveBlob(blob,filename);}
function saveBlob(blob,filename){const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function acceptState(next, restoreDraft=false){
  const previous=state?.revision;state=next;const busy=['running','cancelling'].includes(state.job.status);
  $('job-panel').hidden=!busy;$('job-message').textContent=state.job.message;$('job-count').textContent=`${state.job.completed} / ${state.job.total} ID`;$('progress').max=state.job.total||1;$('progress').value=state.job.completed;$('cancel').disabled=state.job.status==='cancelling';
  updateRunButton();$('restore').disabled=busy||pending;$('quit').disabled=busy||pending;
  document.querySelectorAll('#view-input input,#view-input textarea,#view-input select,#view-input button:not(#run)').forEach(n=>n.disabled=busy||pending);
  if(state.revision!==previous){if($('detail-dialog').open)$('detail-dialog').close();detailRow=null;renderResults();if(restoreDraft && state.input){draft=state.input;inputMode='file';switchInput('file');$('filename').textContent='前回実行時の入力を復元しました。表とID列を確認して再実行できます。';renderPreview(state.id_column);applySettings(state.settings);runDraftVersion=draftVersion;}}
  if((state.job.status!==lastJob || (state.job.status==='done' && state.revision!==previous)) && ['error','cancelled','done'].includes(state.job.status)){notify(state.job.message,state.job.status==='error');if(state.job.status==='done'){if(submittedDraftVersion!==null)runDraftVersion=submittedDraftVersion;changeView('results');}submittedDraftVersion=null;}
  lastJob=state.job.status;$('stale').hidden=!state.results.data.length||draftVersion===runDraftVersion;
}
function startPolling(){if(polling)return;polling=true;const tick=async()=>{try{const next=await api('/api/state');acceptState(next);if(['running','cancelling'].includes(next.job.status)){setTimeout(tick,400);return;}}catch(e){notify(e.message,true);}polling=false;};setTimeout(tick,150);}
async function run(){
  if(pending)return;if(importing)throw new Error('ファイルの読み込み完了を待ってから実行してください。');if(!draft)throw new Error('IDを入力するか、ファイルまたはサンプルを読み込んでください。');
  pending=true;submittedDraftVersion=draftVersion;updateRunButton();try{acceptState(await api('/api/run',{revision:state.revision,input:draft,id_column:$('id-column').value,settings:settings()}));startPolling();}catch(error){submittedDraftVersion=null;throw error;}finally{pending=false;updateRunButton();}
}
async function restoreProject(file){if(!file)return;if(file.size>128*1024*1024-1024)throw new Error('プロジェクトは128MB以下にしてください。');let project;try{project=JSON.parse(await file.text());}catch(_){throw new Error('JSONを読み込めません。元の作業はそのまま残っています。');}acceptState(await api('/api/restore',{revision:state.revision,project}),true);changeView('results');notify('プロジェクトを復元しました。入力・設定・根拠を確認できます。');}
async function quit(save){if(save && state.results.data.length){await download('/api/export/project',{revision:state.revision},'PAIA-project.json');$('quit-help').textContent='ダウンロードを開始しました。保存先でJSONを確認してから「終了する」を押してください。';return;}await api('/api/shutdown',{revision:state.revision});$('quit-dialog').close();notify('アプリを終了しました。このタブを閉じてください。');document.querySelectorAll('button').forEach(b=>b.disabled=true);}
async function init(){
  [config,state]=await Promise.all([api('/api/config'),api('/api/state')]);
  $('version').textContent='v'+config.version+' · Portable';
  setOptions($('id-type'),config.id_types.map(v=>[v,{'Auto-detect':'自動判定','Gene Name / Symbol':'遺伝子名','Protein Name':'タンパク質名'}[v]||v]));
  setOptions($('preset'),[...Object.keys(config.presets).map(v=>[v,v.split(' / ')[1]||v]),['custom','カスタム']]);
  applySettings(state.settings);$('preset').value='Basic / 基本情報';
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>changeView(b.dataset.view)));
  document.querySelectorAll('[data-input]').forEach(b=>{b.tabIndex=b.dataset.input===inputMode?0:-1;b.addEventListener('click',()=>switchInput(b.dataset.input));b.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const modes=['type','file','demo'],i=modes.indexOf(b.dataset.input),next=e.key==='Home'?'type':e.key==='End'?'demo':modes[(i+(e.key==='ArrowRight'?1:2))%3];switchInput(next);$('tab-'+next).focus();});});
  $('ids').addEventListener('input',updateTyped);$('id-column').addEventListener('change',()=>{renderPreview();changed();});
  $('preset').addEventListener('change',()=>{if($('preset').value==='custom')return;attrSet=new Set(config.presets[$('preset').value]||Object.values(config.categories).flat());renderAttributes();changed();});
  $('mode').addEventListener('change',()=>{updateMode();changed();});$('species').addEventListener('change',()=>{$('custom-species-wrap').hidden=$('species').value!=='custom';changed();});
  for(const id of ['custom-species','id-type'])$(id).addEventListener('change',changed);
  $('load-demo').addEventListener('click',safe(loadDemo));$('empty-demo').addEventListener('click',safe(async()=>{changeView('input');await loadDemo();}));
  $('input-file').addEventListener('change',safe(e=>loadFile(e.target.files[0])));
  $('dropzone').addEventListener('dragover',e=>{e.preventDefault();$('dropzone').classList.add('drag');});$('dropzone').addEventListener('dragleave',()=>$('dropzone').classList.remove('drag'));$('dropzone').addEventListener('drop',safe(async e=>{e.preventDefault();$('dropzone').classList.remove('drag');if(!['running','cancelling'].includes(state.job.status))await loadFile(e.dataTransfer.files[0]);}));
  $('run').addEventListener('click',safe(run));$('cancel').addEventListener('click',safe(async()=>acceptState(await api('/api/cancel',{}))));$('edit-input').addEventListener('click',()=>changeView('input'));
  for(const id of ['search','numeric-min','numeric-max'])$(id).addEventListener('input',()=>{page=0;filterTable();});for(const id of ['status-filter','location-filter','class-filter','numeric-filter'])$(id).addEventListener('change',()=>{page=0;filterTable();});
  $('reset-filters').addEventListener('click',resetFilters);$('prev').addEventListener('click',()=>{page--;filterTable();});$('next').addEventListener('click',()=>{page++;filterTable();});
  $('export-all').addEventListener('click',safe(()=>download('/api/export/csv',{revision:state.revision},'PAIA-all-rows.csv')));$('export-filtered').addEventListener('click',safe(()=>download('/api/export/csv',{revision:state.revision,indices:visible.map(r=>r.index)},'PAIA-filtered.csv')));
  $('save-project').addEventListener('click',safe(()=>download('/api/export/project',{revision:state.revision},'PAIA-project.json')));
  $('restore').addEventListener('click',()=>$('project-file').click());$('project-file').addEventListener('change',safe(async e=>{try{await restoreProject(e.target.files[0]);}finally{e.target.value='';}}));
  for(const id of ['close-detail','detail-done'])$(id).addEventListener('click',()=>$('detail-dialog').close());
  $('evidence-download').addEventListener('click',()=>{if(detailRow)saveBlob(new Blob([JSON.stringify(detailRow,null,2)],{type:'application/json'}),'PAIA-evidence.json');});
  $('quit').addEventListener('click',()=>{$('quit-error').hidden=true;$('save-and-quit').disabled=!state.results.data.length;$('quit-dialog').showModal();});$('quit-back').addEventListener('click',()=>$('quit-dialog').close());$('save-and-quit').addEventListener('click',safe(()=>quit(true)));$('quit-now').addEventListener('click',safe(()=>quit(false)));
  const initial=state;state=null;acceptState(initial,true);if(initial.results.data.length)changeView('results',false);if(['running','cancelling'].includes(initial.job.status))startPolling();
}
safe(init)();
