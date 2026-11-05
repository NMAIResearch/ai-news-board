const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
function element(a) {
  const listeners = {};
  const names = new Set((a.class || '').split(' '));
  return { attrs:a, value:a.value || '', checked:'checked' in a, hidden:'hidden' in a, style:{}, textContent:'',
    getAttribute:k => a[k] || null,
    addEventListener:(k,f) => {listeners[k]=f;},
    fire:k => {if(listeners[k]) listeners[k]();},
    classList:{add:k=>names.add(k),remove:k=>names.delete(k),contains:k=>names.has(k),toggle:k=>{if(names.has(k)){names.delete(k);return false;}names.add(k);return true;}}
  };
}
const nodes = input.nodes.map(element);
for(let i=0;i<nodes.length-1;i++) nodes[i].nextElementSibling=nodes[i+1];
const doc={querySelectorAll:s=>nodes.filter(n=>n.classList.contains(s.slice(1))),getElementById:id=>nodes.find(n=>n.attrs.id===id)||null,body:{classList:{toggle:()=>false}}};
vm.runInNewContext(input.script,{document:doc});
const cards=doc.querySelectorAll('.card');
const shown=()=>cards.flatMap((c,i)=>c.style.display==='none'?[]:[i]);
const query=doc.getElementById('q');
const out={total:cards.length,initial:shown(),domains:{},conflicts:[]};
for(const chip of doc.querySelectorAll('.filter-chip')){
  chip.fire('click');out.domains[chip.attrs['data-chip']]={shown:shown(),query:query.value,topics:doc.querySelectorAll('.f-topic').filter(x=>x.checked).map(x=>x.value)};
}
const all=doc.querySelectorAll('.filter-chip').find(x=>x.attrs['data-chip']==='all');all.fire('click');
const cf=doc.getElementById('conflictonly');if(cf){cf.checked=true;cf.fire('change');out.conflicts=shown();cf.checked=false;cf.fire('change');}
query.value='zz-no-such-record-zz';query.fire('input');
const empty=doc.getElementById('feed-empty');
out.empty={shown:shown(),messageVisible:!!empty&&!empty.hidden&&empty.style.display!=='none',visibleHeadings:doc.querySelectorAll('.dayhead').filter(h=>!h.hidden&&h.style.display!=='none').length};
all.fire('click');out.reset=shown();
process.stdout.write(JSON.stringify(out));
