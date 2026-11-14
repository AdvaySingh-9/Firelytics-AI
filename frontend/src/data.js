export const nasaBase = 'https://psi.nasa.gov/physci/repo/data/investigations/';
const rows = [
  ['PSI-62','Metadata only',[]],
  ['PSI-60','Metadata only',[]],
  ['PSI-142','Analyzed data + experimental table',['Analyzed Data','Experimental Table']],
  ['PSI-98','Research documents + raw data',['Engineering Documents','Raw Data','Science Documents','Experimental Table']],
  ['PSI-99','Science documents + raw data',['Experimental Table','Raw Data','Science Documents']],
  ['PSI-106','Experimental table + raw data',['Experimental Table','Raw Data']],
  ['PSI-100','Research documents + raw data',['Engineering Documents','Presentations','Raw Data','Science Documents','Experimental Table']],
  ['PSI-21','Experimental table + raw data',['Experimental Table','Raw Data']],
  ['PSI-68','Full research package',['Experimental Table','Science Documents','Calibration','Engineering Documents','Raw Data']],
  ['PSI-69','Full research package',['Experimental Table','Engineering Documents','Presentations','Raw Data','Calibration','Science Documents']],
  ['PSI-26','Research documents + raw data',['Presentations','Science Documents','Engineering Documents','Raw Data','Experimental Table']]
];
export const investigations = rows.map(([id, summary, assets]) => ({
  study_id:id, title:id==='PSI-69'?'Flame Extinguishment Experiment':`NASA PSI Investigation ${id.replace('PSI-','')}`,
  acronym:id==='PSI-69'?'FLEX':'—', summary, assets, asset_count:assets.length+1,
  availability: assets.length===0?'metadata_only':assets.includes('Analyzed Data')?'analyzed_data':assets.includes('Science Documents')?'research_documents':'experimental_data',
  source_url:nasaBase+id, source:'NASA Physical Sciences Informatics',
  objective:id==='PSI-69'?'Study liquid-fuel droplet burning and flame-extinguishment behavior in microgravity.':'Investigation objective not yet enriched in the local project catalogue.',
  note:assets.length===0?'The supplied inventory indicates metadata only. No report or measurement files are listed in this project inventory.':'Asset categories are based on the inventory supplied by the project team; inspect NASA PSI for file-level details.'
}));
export const navItems = [
  {id:'overview',label:'Overview',icon:'LayoutDashboard',group:'WORKSPACE'},
  {id:'search',label:'AI Smart Search',icon:'Search',group:'WORKSPACE'},
  {id:'library',label:'Experiment Library',icon:'Library',group:'RESEARCH'},
  {id:'compare',label:'Compare Studies',icon:'GitCompareArrows',group:'RESEARCH'},
  {id:'analytics',label:'Research Analytics',icon:'ChartNoAxesCombined',group:'RESEARCH'},
  {id:'safety',label:'Safety Insights',icon:'ShieldCheck',group:'INTELLIGENCE'},
  {id:'explorer',label:'Data Explorer',icon:'Database',group:'INTELLIGENCE'},
  {id:'assistant',label:'Research Assistant',icon:'MessageSquareText',group:'INTELLIGENCE'},
  {id:'settings',label:'Settings & API',icon:'Settings2',group:'SYSTEM'}
];
