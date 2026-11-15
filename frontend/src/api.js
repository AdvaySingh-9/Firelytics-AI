import { investigations } from './data';
let BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '');
export function setApiBase(url) { BASE = url.replace(/\/$/, ''); }
let mode = 'demo';
export const getMode = () => mode;
export async function request(path, options={}) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(), 9000);
  try {
    const response = await fetch(`${BASE}${path}`, { ...options, signal:controller.signal, headers:{'Content-Type':'application/json', ...(options.headers||{})} });
    if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
    mode = 'api'; return await response.json();
  } finally { clearTimeout(timeout); }
}
export async function loadInvestigations() {
  try { const d=await request('/investigations'); return Array.isArray(d)?d:(d.items||d.data||investigations); }
  catch { mode='demo'; return investigations; }
}
export async function checkHealth() { return request('/health'); }
export async function smartSearch(query) {
  try { return await request('/search',{method:'POST',body:JSON.stringify({query})}); }
  catch { const q=query.toLowerCase(); const items=investigations.filter(x=>(x.study_id+' '+x.title+' '+x.acronym+' '+x.objective+' '+x.assets.join(' ')).toLowerCase().includes(q) || (q.includes('flex')&&x.study_id==='PSI-69') || (q.includes('metadata')&&x.availability==='metadata_only')); return {query,results:items,mode:'demo',message:'Local catalogue search. Connect the search endpoint and NASA data index for semantic retrieval.'}; }
}
export async function explainStudy(study) {
  try { return await request('/explain',{method:'POST',body:JSON.stringify({study_id:study.study_id})}); }
  catch { return {mode:'demo',title:study.title,sections:[{heading:'What is available',body:study.summary+'. '+study.note},{heading:'Research context',body:study.objective},{heading:'Evidence boundary',body:'This explanation is based only on the investigation metadata and asset categories currently recorded in this project. It does not claim to summarize files that have not been ingested.'}]}; }
}
export async function compareStudies(ids) {
  try { return await request('/compare',{method:'POST',body:JSON.stringify({study_ids:ids})}); }
  catch { return {mode:'demo',items:investigations.filter(x=>ids.includes(x.study_id))}; }
}
