// Layout and render only: all dependencies, quantities and statuses come from Python.
const NS = 'http://www.w3.org/2000/svg';
function svgElement(name, attrs = {}, text) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
const colors = {ok:'#166534', warning:'#92400e', error:'#b91c1c', blocked:'#475569'};
export function renderGraph(container, project, report, select) {
  container.replaceChildren();
  const levels = new Map(), counts = new Map(), positions = new Map();
  for (const id of report.topologicalOrder) {
    const parents = report.edges.filter(edge => edge.to === id).map(edge => levels.get(edge.from) + 1);
    const level = Math.max(0, ...parents), row = counts.get(level) || 0;
    levels.set(id, level); counts.set(level, row + 1);
    positions.set(id, {x:24 + row*225, y:24 + level*130});
  }
  const width = Math.max(300, Math.max(0, ...counts.values())*225 + 24);
  const height = Math.max(180, (Math.max(0, ...levels.values())+1)*130 + 10);
  const svg = svgElement('svg', {width, height, viewBox:`0 0 ${width} ${height}`, 'aria-label':'Calculation dependency graph'});
  for (const edge of report.edges) {
    const a = positions.get(edge.from), b = positions.get(edge.to);
    const affected = report.affectedIds.includes(edge.to);
    svg.append(svgElement('path', {d:`M${a.x+95} ${a.y+82} L${b.x+95} ${b.y}`, fill:'none', stroke:affected?'#1e40af':'#aabbd0', 'stroke-width':affected?3:1.5, ...(affected?{'stroke-dasharray':'5 3'}:{})}));
  }
  for (const node of report.nodes) {
    const {x,y} = positions.get(node.id);
    const group = svgElement('g', {role:'button', tabindex:0, 'aria-label':`${node.id}: ${node.status}`, 'data-node':node.id});
    group.append(svgElement('rect', {x,y,width:190,height:82,rx:node.kind==='formula'?14:2,fill:'#fff',stroke:colors[node.status],'stroke-width':2}));
    group.append(svgElement('text', {x:x+12,y:y+22,fill:'#172d49','font-size':14,'font-family':'Consolas,monospace'},node.id));
    group.append(svgElement('text', {x:x+12,y:y+42,fill:colors[node.status],'font-size':12},`${node.kind} · ${node.status}`));
    const value = node.quantity ? `${Number(node.quantity.value.toPrecision(6))} ${node.quantity.unit}` : 'No quantity';
    group.append(svgElement('text',{x:x+12,y:y+64,fill:'#172d49','font-size':11},value));
    group.addEventListener('click',()=>select(node.id));
    group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(node.id);}});
    svg.append(group);
  }
  container.append(svg);
}
