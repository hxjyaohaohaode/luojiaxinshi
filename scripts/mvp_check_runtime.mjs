import path from 'node:path';
import {mkdirSync} from 'node:fs';

// Separate each acceptance run without replacing retained model experiments.
export function artifactPath(name=''){
  const allowed=path.resolve('artifacts'),root=path.resolve(process.env.MVP_ARTIFACT_DIR||'artifacts/mvp-acceptance');
  if(root!==allowed&&!root.startsWith(allowed+path.sep))throw new Error('Acceptance artifacts must stay inside this workspace artifacts directory');
  const file=path.resolve(root,name);
  if(file!==root&&!file.startsWith(root+path.sep))throw new Error('Invalid acceptance artifact name');
  mkdirSync(root,{recursive:true});return file;
}

export async function visibleHidden(page,selector='body'){
  return page.evaluate(selector=>[...document.querySelectorAll(selector+' [hidden]')].filter(el=>el.getBoundingClientRect().width&&el.getBoundingClientRect().height).map(el=>({tag:el.tagName,id:el.id,cls:el.className,text:el.textContent.trim().slice(0,100)})),selector);
}
