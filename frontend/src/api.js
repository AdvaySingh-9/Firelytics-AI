import { investigations } from './data';
let BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api').replace(/\/$/, '');
export function setApiBase(url) { BASE = url.replace(/\/$/, ''); }
let mode = 'demo';
export const getMode = () => mode;
export async function request(path, options={}, timeoutMs=30000) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(), timeoutMs);
  try {
    const headers = options.body instanceof FormData ? (options.headers||{}) : {'Content-Type':'application/json', ...(options.headers||{})};
    const response = await fetch(`${BASE}${path}`, { ...options, signal:controller.signal, headers });
    if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
    mode = 'api'; return await response.json();
  } finally { clearTimeout(timeout); }
}
export async function loadInvestigations() {
  try { const d=await request('/investigations'); return Array.isArray(d)?d:(d.items||d.data||investigations); }
  catch { mode='demo'; return investigations; }
}
export async function checkHealth() { return request('/health'); }
export async function chatAssistant(message, history=[]) {
  return request('/chat',{method:'POST',body:JSON.stringify({message,history})});
}
export async function uploadReport(file) {
  const form=new FormData();
  form.append('file',file);
  return request('/upload',{method:'POST',body:form});
}
export async function smartSearch(query) {
  try { return await request('/search',{method:'POST',body:JSON.stringify({query})}); }
  catch { const q=query.toLowerCase(); const items=investigations.filter(x=>(x.study_id+' '+x.title+' '+x.acronym+' '+x.objective+' '+x.assets.join(' ')).toLowerCase().includes(q) || (q.includes('flex')&&x.study_id==='PSI-69') || (q.includes('metadata')&&x.availability==='metadata_only')); return {query,results:items,mode:'demo',message:'Local catalogue search. Connect the search endpoint and NASA data index for semantic retrieval.'}; }
}
export async function createInvestigationSession(studyId) {
  try { return await request('/sessions',{method:'POST',body:JSON.stringify({study_id:studyId})},60000); }
  catch (error) { mode='demo'; return {error:error.message,workspace_status:'unavailable'}; }
}
export async function getInvestigationSession(sessionId) {
  return request(`/sessions/${encodeURIComponent(sessionId)}`);
}
export async function endInvestigationSession(sessionId) {
  if (!sessionId) return;
  try { await request(`/sessions/${encodeURIComponent(sessionId)}`,{method:'DELETE',keepalive:true}); } catch { /* TTL cleanup remains the fallback. */ }
}
export async function analyzeInvestigation(sessionId, question, history=[], uploadedData=[]) {
  return request(`/sessions/${encodeURIComponent(sessionId)}/analyze`,{method:'POST',body:JSON.stringify({question,history,uploaded_data:uploadedData})},90000);
}
export async function ingestInvestigationBatch(sessionId, batchSize=8) {
  return request(`/sessions/${encodeURIComponent(sessionId)}/ingest`, {method:'POST', body:JSON.stringify({batch_size:batchSize})}, 90000);
}
export async function explainStudy(study, sessionId, uploadedData=[]) {
  return request('/explain',{method:'POST',body:JSON.stringify({study_id:study.study_id,session_id:sessionId,uploaded_data:uploadedData})},120000);
}
export async function compareStudies(ids, uploadStudyId=null, uploadedData=[]) {
  return request('/compare',{method:'POST',body:JSON.stringify({study_ids:ids,upload_study_id:uploadStudyId,uploaded_data:uploadedData})},90000);
}

export async function exploreInvestigationDatasets(sessionId, question='Analyze the uploaded experimental dataset and explain its contents and relevance', uploadedData=[]) {
  return request(`/sessions/${encodeURIComponent(sessionId)}/datasets`, {method:'POST', body:JSON.stringify({question,uploaded_data:uploadedData})}, 120000);
}

export async function uploadResearchFile(file, sessionId, studyId) {
  if (!sessionId || !studyId) throw new Error('Open the intended investigation before uploading a file.');
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', sessionId);
  form.append('study_id', studyId);
  const response = await fetch(`${BASE}/upload`, { method: 'POST', body: form });
  if (!response.ok) throw new Error(`Upload/extraction failed (${response.status}): ${await response.text()}`);
  mode = 'api';
  return response.json();
}
