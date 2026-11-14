/** Reproducible ESM route chunks and ordered CSS layers; no runtime build step. */
import {build,version} from 'esbuild';
import {readFile,writeFile,mkdir,rm,readdir} from 'node:fs/promises';
import {resolve,relative,dirname,isAbsolute,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {gzipSync,brotliCompressSync} from 'node:zlib';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const out=resolve(root,'static/dist');
const check=process.argv.includes('--check');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const portable=path=>relative(root,path).replaceAll('\\','/');
const result=await build({
  absWorkingDir:root,entryPoints:['static/app.js','static/styles.css'],outdir:out,
  bundle:true,splitting:true,format:'esm',platform:'browser',target:['es2022'],
  entryNames:'[name]-[hash]',chunkNames:'chunks/[name]-[hash]',assetNames:'assets/[name]-[hash]',
  minify:true,metafile:true,write:false,charset:'utf8',legalComments:'eof',
  loader:{'.svg':'file','.png':'file','.webm':'file','.woff2':'file'},
  plugins:[{name:'local-static-urls',setup(build){
    build.onResolve({filter:/^\/static\//},args=>{
      const path=resolve(root,args.path.slice(1));
      const within=relative(resolve(root,'static'),path);
      if(!within||within==='..'||within.startsWith('..'+sep)||isAbsolute(within))throw Error('Static URL escapes its root');
      return {path};
    });
  }}],
});
const outputs=new Map(result.outputFiles.map(file=>[portable(file.path),Buffer.from(file.contents)]));
const sourcePaths=[...new Set([...Object.keys(result.metafile.inputs),'static/index.html'])].sort();
const sources={};for(const path of sourcePaths)sources[path]=sha(await readFile(resolve(root,path)));
const buildSources={};for(const path of ['scripts/build_frontend.mjs','package.json','package-lock.json'])buildSources[path]=sha(await readFile(resolve(root,path)));
const entries={};
for(const [path,data] of Object.entries(result.metafile.outputs)){
  if(data.entryPoint==='static/app.js')entries.js='/'+path;
  if(data.entryPoint==='static/styles.css')entries.css='/'+path;
  if(data.imports.some(item=>item.external&&item.path.startsWith('/static/')))throw Error('Unbundled local stylesheet or module: '+path);
}
if(!entries.js||!entries.css)throw Error('Missing JS/CSS build entry');
let index=await readFile(resolve(root,'static/index.html'),'utf8');
if(!index.includes('href="/static/styles.css"')||!index.includes('src="/static/app.js"'))throw Error('Source HTML entry contract changed');
index=index.replace('href="/static/styles.css"',`href="${entries.css}"`).replace('src="/static/app.js"',`src="${entries.js}"`);
outputs.set('static/dist/index.html',Buffer.from(index));
const metrics={};const hashes={};
for(const [path,bytes] of outputs){
  hashes[path]=sha(bytes);
  metrics[path]={bytes:bytes.length,gzip:gzipSync(bytes,{level:9}).length,brotli:brotliCompressSync(bytes).length};
}
const manifest={format:1,esbuild:version,entries,sources,build_sources:buildSources,outputs:hashes};
outputs.set('static/dist/manifest.json',Buffer.from(JSON.stringify(manifest,null,2)+'\n'));
if(check){
  for(const [path,bytes] of outputs){
    let saved;try{saved=await readFile(resolve(root,path));}catch{throw Error('Missing built asset: '+path);}
    if(!saved.equals(bytes))throw Error('Stale frontend build: '+path+'; run npm run build');
  }
  async function files(dir){let all=[];for(const item of await readdir(dir,{withFileTypes:true})){const path=resolve(dir,item.name);all.push(...(item.isDirectory()?await files(path):[portable(path)]));}return all;}
  for(const path of await files(out))if(!outputs.has(path))throw Error('Obsolete frontend output: '+path);
}else{
  await rm(out,{recursive:true,force:true});
  for(const [path,bytes] of outputs){const absolute=resolve(root,path);await mkdir(dirname(absolute),{recursive:true});await writeFile(absolute,bytes);}
}
console.log(JSON.stringify({checked:check,entries,files:outputs.size,source_files:sourcePaths.length,metrics},null,2));
