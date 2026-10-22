export const SPEECH_STYLE='用清晰、自然、温和的普通话朗读，语速适中，句间适当停顿，准确读出日期、时间、数字和事项，不添加内容。';
export function speechChunks(markdown,limit=700){
 const text=String(markdown||'')
  .replace(/```[\s\S]*?```/g,'').replace(/!\[[^\]]*\]\([^)]*\)/g,'')
  .replace(/\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/\[(?:E)?\d+\]/g,'')
  .replace(/https?:\/\/[^\s<>]+/g,'').replace(/(^|\n)\s{0,3}#{1,6}\s+/g,'$1')
  .replace(/^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$/gm,'')
  .replace(/\b(20\d{2})-(\d{2})-(\d{2})\b/g,(_,y,m,d)=>`${y}年${Number(m)}月${Number(d)}日`)
  .replace(/\b([01]?\d|2[0-3]):([0-5]\d)\b/g,(_,h,m)=>`${Number(h)}点${Number(m)?Number(m)+'分':''}`)
  .replace(/\|/g,'，').replace(/[*_`>]/g,'').replace(/\n\s*[-+]\s+/g,'\n')
  .replace(/[ \t]+/g,' ').replace(/\n{3,}/g,'\n\n').trim();
 const chunks=[];let rest=text;
 while(rest.length>limit){
  let cut=Math.max(...['。','！','？','；','\n','. '].map(mark=>rest.lastIndexOf(mark,limit-1)));
  if(cut<limit/3)cut=Math.max(rest.lastIndexOf('，',limit-1),rest.lastIndexOf(' ',limit-1));
  if(cut<limit/3)cut=limit-1;
  if(/[\uD800-\uDBFF]/.test(rest[cut]))cut--;
  chunks.push(rest.slice(0,cut+1).trim());rest=rest.slice(cut+1).trim();
 }
 if(rest)chunks.push(rest);return chunks;
}
