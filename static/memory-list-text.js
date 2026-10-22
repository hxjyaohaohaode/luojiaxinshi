// A list excerpt is derived from the original wording, never an AI rewrite.
// A complete first sentence/line can be a title; otherwise repeat the original
// in the preview rather than dropping characters hidden by the title's clamp.
export function memoryListText(value) {
  const content=String(value??'').trim();
  if(!content)return {title:'',preview:''};
  const boundary=content.search(/[。！？\n\r]/u);
  const end=boundary<0?content.length:boundary+(/[。！？]/u.test(content[boundary])?1:0);
  const first=content.slice(0,end).trim();
  if([...first].length<=48)return {title:first,preview:content.slice(end).trim()};
  return {title:[...first].slice(0,44).join('')+'…',preview:content};
}

const memoryDayFormat=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'});
const memoryTimeFormat=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
export function memoryTimestamp(value,includeTime=false){
  if(value===null||value===undefined||value===''||typeof value==='boolean')return '';
  const instant=new Date(Number(value)*1000);
  if(!Number.isFinite(instant.getTime()))return '';
  return (includeTime?memoryTimeFormat:memoryDayFormat).format(instant);
}
