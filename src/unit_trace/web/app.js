import {renderGraph} from './graph.js';

const $ = selector => document.querySelector(selector);
const clone = value => structuredClone(value);
const state = {project:null,lastReport:null,pendingRevision:0,lastEvaluatedHash:null,lastEvaluatedProject:null,dirty:true};
let profile, templates, selected = null, pendingImport = null;
const token = $('meta[name="unit-trace-session"]').content;
const titles = {flow:'Flow · rectangular channel',density:'Density · sample mass',spring:'Spring · stiffness',electric:'Electric · power',energy:'Energy · kinetic',diffusion:'Diffusion · estimate',concentration:'Concentration · aliquot',pendulum:'Pendulum · gravity'};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key)+':'+canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
async function hash(project) {
  const bytes = new TextEncoder().encode(canonical(project));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
}
function notice(message) { $('#notice').textContent = message; }
function updateStatus(message) {
  $('#calculation-state').textContent = message || (state.dirty ? (state.lastReport?'Old result · pending calculation':'Pending calculation') : 'Current result');
  for (const kind of ['json','svg','html']) $('#export-'+kind).disabled = state.dirty || !state.lastReport;
}
function edited() {
  if (state.pendingRevision >= 2147483647) {
    notice('Revision limit reached. Save the input and start a new session.');
    state.dirty = true; updateStatus(); return;
  }
  state.pendingRevision += 1;
  state.dirty = true;
  updateStatus();
}
async function api(path, data) {
  let response;
  try {
    response = await fetch(path,{method:data===undefined?'GET':'POST',headers:{'X-Unit-Trace-Session':token,...(data===undefined?{}:{'Content-Type':'application/json'})},...(data===undefined?{}:{body:JSON.stringify(data)})});
  } catch {
    $('#connection-state').textContent='Disconnected';
    throw new Error('Disconnected. Start the local service again to calculate.');
  }
  $('#connection-state').textContent='Connected locally';
  if (!response.ok) {
    const body = await response.json();
    const error = new Error('Input could not be accepted.');
    error.issues = body.errors || [];
    throw error;
  }
  return response;
}
function showIssues(issues) {
  $('#issues').replaceChildren();
  document.querySelectorAll('.field-error').forEach(n=>n.remove());
  for (const issue of issues) {
    const row = element('div',undefined,'issue');
    if (issue.nodeId) {
      const button=element('button',issue.nodeId); button.addEventListener('click',()=>selectNode(issue.nodeId));row.append(button);
    }
    row.append(element('strong',issue.code+' · '),element('span',issue.message+' ['+issue.field+']'));
    if(issue.code==='numeric_limit'&&issue.field.includes('expected')) row.append(element('p','The user range could not be checked; the computed quantity is retained.','warning'));
    $('#issues').append(row);
    const editor=Array.from(document.querySelectorAll('.node-editor')).find(n=>n.dataset.id===issue.nodeId);
    if(editor) editor.append(element('p',issue.code+': '+issue.message,'field-error'));
  }
  if (!issues.length) $('#issues').append(element('p','No current issues. Ranges, when present, are supplied by you.','muted'));
}
async function evaluate() {
  const submittedProject=clone(state.project), previousProject=state.lastEvaluatedProject&&clone(state.lastEvaluatedProject);
  const revision=state.pendingRevision;
  state.dirty=true;updateStatus('Calculating…');notice('');
  try {
    const expectedHash=await hash(submittedProject);
    const data=await (await api('/api/evaluate',{project:submittedProject,revision,...(previousProject?{previousProject}:{})})).json();
    if(revision!==state.pendingRevision||canonical(state.project)!==canonical(submittedProject)||data.revision!==revision){notice('An outdated calculation response was discarded.');return;}
    if(data.report.projectHash!==expectedHash){notice('Response hash does not match the submitted project.');updateStatus();return;}
    // Commit the report and its exact immutable input baseline together, including
    // structurally valid error/blocked/warning results.
    Object.assign(state,{lastReport:data.report,lastEvaluatedHash:expectedHash,lastEvaluatedProject:submittedProject,dirty:false});
    selected=data.report.firstError?.nodeId || (data.report.nodes.some(n=>n.id===selected)?selected:data.report.nodes[0]?.id);
    updateStatus();renderReport();
  } catch(error) {
    if(revision!==state.pendingRevision){notice('An outdated calculation response was discarded.');return;}
    state.dirty=true;updateStatus();notice(error.message);
    if(error.issues)showIssues(error.issues);
  }
}
function field(record,key,label,onEdit,limit=64) {
  const wrapper=element('label',label), input=element('input');
  input.value=record[key]??'';input.maxLength=limit;input.setAttribute('aria-label',record.id+' '+label.toLowerCase());
  input.addEventListener('input',()=>{onEdit(input.value);edited();});wrapper.append(input);return wrapper;
}
function renderEditors() {
  $('#project-title').value=state.project.title;
  for(const [kind,key] of [['variable','variables'],['formula','formulas']]){
    const container=$('#'+key);container.replaceChildren();
    for(const record of state.project[key]){
      const card=element('div',undefined,'node-editor');card.dataset.id=record.id;
      const head=element('div',undefined,'node-editor-head');head.append(element('strong',record.id));
      const remove=element('button','Remove','remove');remove.setAttribute('aria-label','Remove '+record.id);
      remove.addEventListener('click',()=>{state.project[key]=state.project[key].filter(n=>n!==record);edited();renderEditors();});head.append(remove);card.append(head);
      const meta=element('div',undefined,'field-pair');
      meta.append(field(record,'id','ID',value=>{record.id=value;},32),field(record,'label','Label',value=>{record.label=value;},80));card.append(meta);
      if(kind==='variable'){
        const pair=element('div',undefined,'field-pair');pair.append(field(record,'value','Value',value=>record.value=value,32),field(record,'unit','Unit',value=>record.unit=value));card.append(pair);
        const row=element('div',undefined,'convert-row'), targetLabel=element('label','Convert to'), target=element('input');target.maxLength=64;target.setAttribute('aria-label',record.id+' convert to');targetLabel.append(target);
        const button=element('button','Convert');button.setAttribute('aria-label','Convert '+record.id);button.addEventListener('click',()=>convert(record.id,target.value));row.append(targetLabel,button);card.append(row);
      }else{
        card.append(field(record,'expression','Expression',value=>record.expression=value,512),field(record,'outputUnit','Output unit',value=>{if(value)record.outputUnit=value;else delete record.outputUnit;}));
      }
      const toggleLabel=element('label',undefined,'range-toggle'), toggle=element('input');toggle.type='checkbox';toggle.checked=!!record.expected;toggle.setAttribute('aria-label',record.id+' range');toggleLabel.append(toggle,element('span','Check my expected range'));card.append(toggleLabel);
      toggle.addEventListener('change',()=>{if(toggle.checked)record.expected={min:'0',max:'1',unit:kind==='variable'?record.unit:(record.outputUnit||'1')};else delete record.expected;edited();renderEditors();});
      if(record.expected){const ranges=element('div',undefined,'range-fields');for(const name of ['min','max','unit']){const wrap=element('label','Expected '+name),input=element('input');input.value=record.expected[name];input.maxLength=name==='unit'?64:32;input.setAttribute('aria-label',record.id+' expected '+name);input.addEventListener('input',()=>{record.expected[name]=input.value;edited();});wrap.append(input);ranges.append(wrap);}card.append(ranges);}
      container.append(card);
    }
  }
}
async function convert(targetId,toUnit) {
  const target=state.project.variables.find(n=>n.id===targetId);
  if(!target)return;
  const captured={targetId,editRevision:state.pendingRevision,value:target.value,fromUnit:target.unit,toUnit};
  try{
    const response=await api('/api/convert',{value:captured.value,fromUnit:captured.fromUnit,toUnit});
    const data=await response.json(),current=state.project.variables.find(n=>n.id===targetId);
    if(!current||state.pendingRevision!==captured.editRevision||current.value!==captured.value||current.unit!==captured.fromUnit){notice('An outdated conversion response was discarded.');return;}
    current.value=data.quantity.roundtrip;current.unit=captured.toUnit;edited();renderEditors();notice('Input converted without changing its physical quantity. Factor '+data.conversion.factor+'. Run calculation to refresh results.');
  }catch(error){notice(error.message);if(error.issues)showIssues(error.issues);}
}
function detailLine(label,value,parent=$('#details')){const div=element('div',undefined,'detail-line');div.append(element('strong',label),element('div',value??'Not available'));parent.append(div);}
function selectNode(id) {
  selected=id;renderDetails();
  document.querySelectorAll('#node-list button').forEach(button=>button.classList.toggle('selected',button.dataset.node===id));
}
function renderDetails() {
  const root=$('#details');root.replaceChildren();
  const node=state.lastReport?.nodes.find(n=>n.id===selected);
  if(!node){root.append(element('p','Select a node to see its explanation.'));return;}
  const input=[...state.lastEvaluatedProject.variables,...state.lastEvaluatedProject.formulas].find(n=>n.id===node.id);
  root.append(element('h2',node.id),element('p',input.label,'muted'),element('p',node.status+' · '+node.kind,node.status));
  detailLine('Symbolic formula / input',node.symbolic);
  if(node.error?.span){const code=element('code'),{start,end}=node.error.span;code.append(document.createTextNode(node.symbolic.slice(0,start)),element('mark',node.symbolic.slice(start,end)),document.createTextNode(node.symbolic.slice(end)));root.append(code);detailLine('First failing operation span',`[${start}, ${end})`);}
  detailLine('Numeric substitution',node.substitution);
  if(node.quantity){root.append(element('p',node.quantity.roundtrip+' '+node.quantity.unit,'node-value'));detailLine('Dimensionality',node.quantity.dimensionality);}
  else detailLine('Quantity','No quantity · '+node.status);
  detailLine('Conversions',node.conversions.length?node.conversions.map(c=>`${c.reason}: ${c.fromUnit} → ${c.toUnit} · factor ${c.factor}`).join('\n'):'No conversion (factor 1)');
  if(node.rootErrorIds.length)detailLine('Root error IDs',node.rootErrorIds.join(', '));
  if(node.error)detailLine(node.error.code,node.error.message);
  for(const issue of node.warnings)detailLine(issue.code,issue.message+(issue.code==='numeric_limit'?' User range could not be checked.':''));
  for(const [index,trace] of node.traces.entries()){
    const part=element('div',undefined,'trace');part.append(element('h3',`Step ${index+1} · ${trace.operator} · [${trace.span.start}, ${trace.span.end})`));
    detailLine('Symbolic',trace.symbolic,part);detailLine('Substitution',trace.substitution,part);
    detailLine('Result',trace.result?`${trace.result.roundtrip} ${trace.result.unit} · ${trace.result.dimensionality}`:'Failed · '+trace.issueId,part);
    for(const c of trace.conversions)detailLine('Conversion',`${c.fromUnit} → ${c.toUnit} · factor ${c.factor}`,part);
    root.append(part);
  }
}
function renderReport() {
  const report=state.lastReport;
  renderGraph($('#graph'),state.lastEvaluatedProject,report,selectNode);
  $('#node-list').replaceChildren();
  for(const id of report.topologicalOrder){const node=report.nodes.find(n=>n.id===id),button=element('button');button.dataset.node=id;
    const parents=report.edges.filter(edge=>edge.to===id).map(edge=>edge.from);
    button.textContent=`${id} · ${node.status}\n${node.quantity?node.quantity.roundtrip+' '+node.quantity.unit:'No quantity'}\nDepends on: ${parents.join(', ')||'input'}`;
    button.classList.toggle('affected',report.affectedIds.includes(id));button.addEventListener('click',()=>selectNode(id));$('#node-list').append(button);
  }
  $('#changes').textContent=`Affected: ${report.affectedIds.join(', ')||'none'} · Removed: ${report.removedIds.join(', ')||'none'}`;
  selectNode(selected);showIssues([...report.rootErrors,...report.nodes.flatMap(n=>n.warnings)]);
}
function applyProject(project) {
  // Protect the editor's container assumptions; Python performs complete schema,
  // syntax, unit and graph validation at the computation boundary.
  if(!project||typeof project!=='object'||project.schemaVersion!==1||project.profile!=='unit-trace-scalar-v1'||typeof project.title!=='string'||!Array.isArray(project.variables)||!Array.isArray(project.formulas)||project.variables.length>80||project.formulas.length>20)throw new Error('Unsupported or invalid Project structure.');
  for(const [key,fields]of [['variables',['id','label','value','unit']],['formulas',['id','label','expression']]])for(const n of project[key])if(!n||fields.some(f=>typeof n[f]!=='string')||(n.expected!==undefined&&(!n.expected||['min','max','unit'].some(k=>typeof n.expected[k]!=='string'))))throw new Error('Invalid node structure.');
  state.project=clone(project);edited();renderEditors();
}
function applyTemplate(variant) {
  const item=templates.find(item=>item.id===$('#template').value);
  const normal=item.variants.normal,chosen=item.variants[variant],changes=[];
  for(const key of ['variables','formulas'])for(let i=0;i<chosen[key].length;i++)for(const field of Object.keys(chosen[key][i]))if(chosen[key][i][field]!==normal[key][i][field])changes.push(`${chosen[key][i].id}.${field}: ${normal[key][i][field]} → ${chosen[key][i][field]}`);
  $('#variant-description').textContent=changes.length?'Changed fields: '+changes.join('; '):'Normal template · no expected ranges are preset.';
  applyProject(chosen);notice('');
}

// A strict local JSON reader preserves duplicate-key/depth/string guards before
// a potentially 8 MiB Bundle is reduced to its bounded Project for HTTP.
function strictJSON(text) {
  let at=0;
  const fail=()=>{throw new Error('Invalid JSON: duplicate keys, excessive depth, or invalid text.');};
  const space=()=>{while(/[\t\n\r ]/.test(text[at]||'!'))at++;};
  function string(){const start=at++;let escaped=false;while(at<text.length){const c=text[at++];if(!escaped&&c==='"'){let result;try{result=JSON.parse(text.slice(start,at));}catch{fail();}if(/\u0000|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(result))fail();return result;}if(!escaped&&c==='\\')escaped=true;else escaped=false;}fail();}
  function value(depth){space();const c=text[at];if(c==='"')return string();if(c==='{'||c==='['){if(depth>=16)fail();at++;const object=c==='{',result=object?Object.create(null):[],end=object?'}':']',keys=new Set();space();if(text[at]===end){at++;return result;}while(true){space();let key;if(object){if(text[at]!=='"')fail();key=string();if(keys.has(key))fail();keys.add(key);space();if(text[at++]!==':')fail();}const v=value(depth+1);if(object)result[key]=v;else result.push(v);space();if(text[at]===end){at++;return result;}if(text[at++]!==',')fail();}}const match=/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(at));if(!match)fail();at+=match[0].length;const result=JSON.parse(match[0]);if(typeof result==='number'&&!Number.isFinite(result))fail();return result;}
  const result=value(0);space();if(at!==text.length)fail();return result;
}
async function importProject(file) {
  if(!file)return;
  edited();
  const importRevision=state.pendingRevision;
  pendingImport=null;$('#profile-mismatch').hidden=true;
  try{
    if(file.size>8388608)throw new Error('JSON import exceeds 8 MiB.');
    const bytes=await file.arrayBuffer();
    if(importRevision!==state.pendingRevision){notice('An outdated file import was discarded.');return;}
    const data=strictJSON(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    if(data&&Object.hasOwn(data,'project')){
      if(canonical(Object.keys(data).sort())!==canonical(['project','report','schemaVersion'])||data.schemaVersion!==1)throw new Error('Unsupported Bundle fields or schema.');
      const source=data.report?.profile;
      const boundedText=value=>typeof value==='string'&&value.length>=1&&value.length<=128;
      const mapping=(value,hashes=false)=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length<=32&&Object.entries(value).every(([key,v])=>boundedText(key)&&boundedText(v)&&(!hashes||/^[0-9a-f]{64}$/.test(v)));
      if(!source||source.id!=='unit-trace-scalar-v1'||source.schemaVersion!==1||canonical(Object.keys(source).sort())!==canonical(Object.keys(profile).sort())||!boundedText(source.pythonVersion)||!boundedText(source.pintVersion)||!mapping(source.dependencies)||!mapping(source.definitionHashes,true)||!Number.isInteger(source.unitWhitelistVersion)||source.unitWhitelistVersion<1||source.unitWhitelistVersion>2147483647)throw new Error('Unsupported or invalid saved engine profile.');
      if(canonical(source)!==canonical(profile)){
        pendingImport=clone(data.project);$('#profile-mismatch pre').textContent='Saved profile:\n'+JSON.stringify(source,null,2)+'\nCurrent profile:\n'+JSON.stringify(profile,null,2);$('#profile-mismatch').hidden=false;notice('engine_mismatch: choose whether to recompute this Project.');return;
      }
      applyProject(data.project);
    }else applyProject(data);
    notice('Project imported. Saved results were discarded. Run calculation to recompute.');
  }catch(error){notice(error.message);}
  finally{$('#import-project').value='';}
}
async function exportProject(format) {
  if(state.dirty||!state.lastReport)return;
  const revision=state.pendingRevision,submitted=clone(state.project);
  try{
    if(await hash(submitted)!==state.lastEvaluatedHash)throw new Error('Project hash changed. Run calculation again.');
    const response=await api('/api/export',{project:submitted,format}),blob=await response.blob();
    if(revision!==state.pendingRevision||state.dirty||canonical(submitted)!==canonical(state.project)){notice('An outdated export was discarded.');return;}
    const url=URL.createObjectURL(blob),link=element('a');link.href=url;link.download='unit-trace.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('Saved the current '+format.toUpperCase()+' artifact.');
  }catch(error){notice(error.message);if(error.issues)showIssues(error.issues);}
}
$('#run').addEventListener('click',evaluate);
$('#project-title').addEventListener('input',event=>{state.project.title=event.target.value;edited();});
$('#template').addEventListener('change',()=>applyTemplate('normal'));
for(const variant of ['normal','dimension','scale'])$('#'+variant).addEventListener('click',()=>applyTemplate(variant));
$('#restore').addEventListener('click',()=>applyTemplate('normal'));
for(const kind of ['variable','formula'])$('#add-'+kind).addEventListener('click',()=>{const key=kind==='variable'?'variables':'formulas';if(state.project[key].length>=(kind==='variable'?80:20)){notice('Node limit reached.');return;}let i=1;const prefix=kind==='variable'?'input':'result';while([...state.project.variables,...state.project.formulas].some(n=>n.id===prefix+i))i++;state.project[key].push(kind==='variable'?{id:prefix+i,label:prefix+i,value:'1',unit:'1'}:{id:prefix+i,label:prefix+i,expression:'1'});edited();renderEditors();});
$('#import-project').addEventListener('change',event=>importProject(event.target.files[0]));
$('#accept-profile').addEventListener('click',()=>{try{applyProject(pendingImport);$('#profile-mismatch').hidden=true;pendingImport=null;notice('Saved results discarded. Run calculation with the current engine.');}catch(error){notice(error.message);}});
$('#cancel-profile').addEventListener('click',()=>{$('#profile-mismatch').hidden=true;pendingImport=null;});
for(const kind of ['json','svg','html'])$('#export-'+kind).addEventListener('click',()=>exportProject(kind));
for(const button of document.querySelectorAll('[data-panel]'))button.addEventListener('click',()=>{document.querySelectorAll('.panel').forEach(panel=>panel.classList.toggle('mobile-hidden',panel.id!==button.dataset.panel));button.setAttribute('aria-pressed','true');for(const other of document.querySelectorAll('[data-panel]'))if(other!==button)other.setAttribute('aria-pressed','false');});
async function start(){try{[profile,{templates}]=await Promise.all([api('/api/profile').then(r=>r.json()),api('/api/templates').then(r=>r.json())]);$('#engine-profile').textContent=JSON.stringify(profile,null,2);for(const item of templates){const option=element('option',titles[item.id]);option.value=item.id;$('#template').append(option);}applyTemplate('normal');document.querySelector('[data-panel="editor"]').click();await evaluate();}catch(error){notice(error.message);}}
start();
