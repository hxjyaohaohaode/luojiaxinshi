// Shared by list and command search. Server snippets are plain text; renderers
// must escape them. Only active original sources participate in local matching.
export function noticeSearchText(notice={}) {
  const sources=(notice.sources||[]).filter(source=>source.active!==false);
  const tasks=(notice.tasks||[]).map(task=>task.data||task);
  return [notice.title,notice.source_label,notice.source_name,notice.source_url,
    notice.body,notice.search_snippet,notice.search_excerpt,
    ...sources.flatMap(source=>[source.name,...(source.sections||[]).map(section=>section.text)]),
    ...tasks.flatMap(task=>[task.title,task.submission_method,task.location,task.contact,...(task.materials||[])])
  ].filter(value=>typeof value==='string'&&value).join('\n');
}

export function noticeSearchExcerpt(notice,query='') {
  const supplied=notice.search_snippet||notice.search_excerpt;
  if(supplied)return supplied;
  const text=noticeSearchText(notice).replace(/\s+/g,' ').trim(),needle=query.trim().toLocaleLowerCase();
  if(!needle)return '';
  const index=text.toLocaleLowerCase().indexOf(needle);if(index<0)return '';
  const start=Math.max(0,index-45),end=Math.min(text.length,start+190);
  return `${start?'…':''}${text.slice(start,end)}${end<text.length?'…':''}`;
}
