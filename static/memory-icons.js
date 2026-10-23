// Icons describe the stored node's role. A user folder named "notes.md" is
// still a folder; only source records are classified by their file extension.
const shapes = {
  library: 'M4 4h5v16H4z M9 4h5v16H9z m7 1 4-1 3 15-4 1z M6 8h1 M11 8h1',
  folder: 'M3 7V5h6l2 2h10v13H3z',
  'folder-open': 'M3 17V5h6l2 2h9v3 M3 20l3-10h17l-3 10z',
  preference: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
  constraint: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M12 8v5 M12 16h.01',
  decision: 'M9 4H4v16h16v-7 M8 11l4 4L21 5',
  fact: 'M8 3h8l4 4v14H4V3z M15 3v5h5 M8 12h8 M8 16h6',
  episode: 'M3 10a9 9 0 1 1 2 9 M3 3v7h7 M12 7v6l4 2',
  skill: 'M4 4h6l2 2 2-2h6v15h-6l-2 2-2-2H4z M12 6v15 M7 8h2 M15 8h2 M7 12h2 M15 12h2',
  intention: 'M21 12a9 9 0 1 1-9-9 M17 12a5 5 0 1 1-5-5 M12 12l9-9 M16 3h5v5',
  summary: 'M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5',
  notice: 'M4 10h5l11-5v14L9 14H4z M7 14l2 7h4l-2-6 M20 9h2v6h-2',
  project: 'M3 7h18v13H3z M8 7V4h8v3 M3 12h18 M10 12v3h4v-3',
  image: 'M3 3h18v18H3z M3 17l6-6 4 4 3-3 5 5 M16 7h.01',
  audio: 'M9 17V5l11-2v12 M9 8l11-2 M9 17a3 3 0 1 1-3-3h3 M20 15a3 3 0 1 1-3-3h3',
  video: 'M3 4h18v16H3z m7 4 6 4-6 4z',
  archive: 'M5 3h14v18H5z M10 3h4 M10 7h4 M10 11h4 M10 15h4v3h-4z',
  database: 'M4 6a8 3 0 0 1 16 0 8 3 0 0 1-16 0v12a8 3 0 0 0 16 0V6 M4 12a8 3 0 0 0 16 0',
  code: 'm8 6-6 6 6 6 M16 6l6 6-6 6 M14 3l-4 18',
  file: 'M14 3H5v18h14V8z M14 3v5h5 M8 13h8 M8 17h5',
};
const labels = {library:'全部记忆',folder:'目录','folder-open':'已展开目录',preference:'偏好与习惯',constraint:'要求与约束',decision:'决定',fact:'事实与背景',episode:'经历',skill:'方法与经验',intention:'目标与计划',summary:'概览',notice:'通知原文',project:'项目资料',image:'图片',audio:'音频',video:'视频',archive:'压缩文件',database:'数据库',code:'代码',file:'文档',word:'Word 文档',markdown:'Markdown 文档',pdf:'PDF 文档',spreadsheet:'电子表格',presentation:'演示文稿',text:'文本',json:'JSON 数据'};
const fileTypes = {
  word:['doc','docx','odt','rtf'], markdown:['md','markdown','mdx'], pdf:['pdf'],
  spreadsheet:['xls','xlsx','ods','csv','tsv'], presentation:['ppt','pptx','odp'],
  image:['png','jpg','jpeg','gif','webp','svg','bmp','tif','tiff','heic','avif'],
  audio:['mp3','wav','m4a','ogg','flac','aac','opus'], video:['mp4','webm','mov','mkv','avi','m4v'],
  archive:['zip','7z','rar','tar','gz'], database:['db','sqlite','sqlite3'],
  text:['txt','log'], json:['json','jsonl'], code:['js','ts','jsx','tsx','py','html','css','yaml','yml','toml','xml','sql','sh','rs'],
};
const badges = {word:'W',markdown:'MD',pdf:'PDF',spreadsheet:'X',presentation:'P',text:'TXT',json:'{}'};

function icon(type,tone=type){
  const badge=badges[type];
  return `<span class="memory-type-icon memory-type-${tone}" data-memory-icon="${type}" title="${labels[type]}" aria-hidden="true">${badge?`<span class="memory-file-badge memory-file-badge-${type}">${badge}</span>`:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"><path d="${shapes[type]||shapes.file}"/></svg>`}</span>`;
}

function sourceType(title,kind){
  const ext=String(title||'').trim().split('.').pop().toLowerCase();
  return Object.entries(fileTypes).find(([,extensions])=>extensions.includes(ext))?.[0]
    || ({resource_notice:'notice',resource_project:'project'}[kind]) || 'file';
}

export function memoryNodeIcon(node,open=false){
  const key=node.node_key||'';
  if(key==='root')return icon('library');
  if(node.system!==false&&node.system!==0){
    if(key.startsWith('source:'))return icon(sourceType(node.title,key.split(':')[1]));
    const kind=key.match(/\/kind:([^/]+)$/)?.[1];
    if(kind&&Object.hasOwn(labels,kind))return icon(kind);
  }
  return icon(open?'folder-open':'folder','folder');
}

export function memoryEntryIcon(entry){
  return icon(entry.source_kind?sourceType(entry.title,entry.source_kind):(Object.hasOwn(shapes,entry.kind)?entry.kind:'file'));
}
