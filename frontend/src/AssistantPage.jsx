import React,{useRef,useState} from 'react';
import * as I from 'lucide-react';
import {chatAssistant,uploadReport} from './api';

const Icon=({name,size=18,...props})=>{const Component=I[name]||I.CircleHelp;return <Component size={size} strokeWidth={1.8} {...props}/>};
const stopWords=new Set(['a','an','and','are','can','does','for','from','how','in','is','it','me','of','on','please','the','this','to','was','what','when','where','which','who','with','would']);

function answerFromReport(question,report){
 const rows=report.rows||[];
 const columns=rows.length?Object.keys(rows[0]):[];
 const isSummary=/summari[sz]|overview|describe|what('s| is) in|contents/i.test(question);
 if(isSummary){
    const columnList=columns.slice(0,12).join(', ')+(columns.length>12?`, and ${columns.length-12} more`:'');
    const sample=rows[0]?columns.slice(0,5).map(column=>`${column}: ${String(rows[0][column]??'').slice(0,120)}`).join(' | '):'No rows were returned in the preview.';
    return `The uploaded report contains ${report.totalRows} row(s). The API provides a preview of up to ${rows.length} row(s) across ${columns.length} column(s): ${columnList||'no columns detected'}. First preview row, selected fields: ${sample}`;
 }
 const terms=question.toLowerCase().match(/[a-z0-9_-]+/g)?.filter(term=>term.length>2&&!stopWords.has(term))||[];
 const matches=rows.map((row,index)=>({row,index,score:terms.filter(term=>JSON.stringify(row).toLowerCase().includes(term)).length})).filter(item=>item.score>0).sort((a,b)=>b.score-a.score).slice(0,5);
 if(!matches.length)return `I could not find a matching row in the ${rows.length}-row preview of ${report.filename}. The upload API returns at most 20 rows, so a match outside that preview will not appear here.`;
 const excerpts=matches.map(({row,index})=>`Row ${index+1}: ${Object.entries(row).map(([key,value])=>`${key}: ${String(value??'').slice(0,180)}`).join(' | ')}`);
 return `Found ${matches.length} matching row(s) in the uploaded preview of ${report.filename}:\n${excerpts.join('\n')}`;
}

export default function AssistantPage(){
 const [messages,setMessages]=useState([{role:'assistant',text:'Ask about the local investigation catalogue, or attach a CSV/JSON report and ask about its parsed preview.'}]);
 const [input,setInput]=useState('');
 const [report,setReport]=useState(null);
 const [busy,setBusy]=useState(false);
 const [uploading,setUploading]=useState(false);
 const fileRef=useRef(null);

 const attachFile=async(file)=>{
  if(!file)return;
  setUploading(true);
  try{
   const result=await uploadReport(file);
   const attached={filename:result.filename||file.name,totalRows:result.rows||0,rows:Array.isArray(result.preview)?result.preview:[],stored:result.stored===true};
   setReport(attached);
   setMessages(current=>[...current,{role:'assistant',text:`Attached ${attached.filename}. The API parsed ${attached.totalRows} row(s); report questions use its preview of up to ${attached.rows.length} row(s). The file is not stored by the backend.`}]);
  }catch(error){
   setMessages(current=>[...current,{role:'assistant',text:`Could not upload ${file.name}. ${error.message||'Check the backend connection and use a CSV or JSON file.'}`}]);
  }finally{setUploading(false);if(fileRef.current)fileRef.current.value='';}
 };

 const sendMessage=async(event)=>{
  event?.preventDefault();
  const question=input.trim();
  if(!question||busy)return;
  const history=messages.slice(-8).map(({role,text})=>({role,content:text}));
  setInput('');
  setMessages(current=>[...current,{role:'user',text:question}]);
  setBusy(true);
  try{
   const response=await chatAssistant(question,history);
   let answer=report?answerFromReport(question,report):(response.answer||'The assistant returned no answer.');
   if(report&&response.sources?.length){
    const sources=response.sources.map(source=>source.study_id).filter(Boolean);
    if(sources.length)answer+=`\n\nRelated catalogue records: ${[...new Set(sources)].join(', ')}.`;
   }
   setMessages(current=>[...current,{role:'assistant',text:answer}]);
  }catch(error){
   const answer=report?answerFromReport(question,report):`I could not reach the chat service. ${error.message||'Check the API connection and try again.'}`;
   setMessages(current=>[...current,{role:'assistant',text:answer}]);
  }finally{setBusy(false);}
 };

 return <div className="content-wrap assistant-content">
  <div className="page-heading simple"><div><div className="eyebrow">RESEARCH ASSISTANT</div><h1>Ask Firelytics AI</h1><p>Ask about the indexed investigations or attach a CSV/JSON report for questions about its parsed preview.</p></div></div>
  <section className="panel assistant-panel">
   <div className="assistant-topline"><div className="assistant-identity"><div className="ai-orb small-orb"><Icon name="Sparkles"/></div><div><h2>Research chat</h2><p>{report?`Report attached · ${report.filename}`:'Catalogue assistant · Ready for a report'}</p></div></div><span className={`tag ${report?'tag-orange':'tag-muted'}`}>{report?'REPORT ATTACHED':'CATALOGUE'}</span></div>
   <div className="chat-messages assistant-messages" aria-live="polite">
    {messages.map((message,index)=><div className={`chat-message ${message.role}`} key={`${index}-${message.role}`}><div className="chat-avatar">{message.role==='assistant'?<Icon name="Flame"/>:'YOU'}</div><div className="chat-bubble assistant-bubble">{message.text}</div></div>)}
    {busy&&<div className="assistant-thinking"><span className="status-dot"/> Reviewing your question…</div>}
   </div>
   {report&&<div className="report-attachment"><Icon name="FileCheck2"/><div><b>{report.filename}</b><small>{report.totalRows} total rows · {report.rows.length} preview rows · not stored</small></div><button className="icon-button tiny" title="Remove attached report" onClick={()=>setReport(null)}><Icon name="X"/></button></div>}
   <form className="assistant-composer" onSubmit={sendMessage}>
    <input value={input} onChange={event=>setInput(event.target.value)} placeholder={report?'Ask a question about the attached report…':'Ask about an investigation or attach a report…'} aria-label="Message Firelytics AI"/>
    <input ref={fileRef} type="file" accept=".csv,.json,text/csv,application/json" hidden onChange={event=>attachFile(event.target.files?.[0])}/>
    <button className="secondary-btn attach-report" type="button" title="Attach CSV or JSON report" onClick={()=>fileRef.current?.click()} disabled={uploading}><Icon name="Paperclip"/> <span>{uploading?'Uploading…':'Attach report'}</span></button>
    <button className="primary-btn" type="submit" disabled={busy||!input.trim()} title="Send message"><Icon name="Send"/> <span>Send</span></button>
   </form>
   <div className="assistant-note"><Icon name="Info"/><span>Uploads are parsed in memory only. Report answers use the API's first 20 preview rows; they are not a full-document analysis.</span></div>
  </section>
 </div>;
}
