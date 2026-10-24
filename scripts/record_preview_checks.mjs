import assert from 'node:assert/strict';
export async function verifyRecordPreview(page,base){
 await page.goto(base+'/static/record-preview.js');
 await page.setContent('<main id="preview"></main>');
 const text=JSON.stringify({record_type:'用户确认的待办记录，期限是否已核实以 deadline_confirmed 为准',values:{title:'提交申请表',due_date:'2026-10-25',deadline_confirmed:false},version:5,workflow:{data:{stage:'waiting',receipt:'已收件'}}});
 await page.evaluate(async({base,text})=>{
   const {attachmentPreview}=await import(base+'/static/attachments.js');
   const api=async()=>({page:1,pages:1,matched:1,sections:[{locator:'记录快照',text}]});
   attachmentPreview(document.querySelector('#preview'),{id:'snapshot',name:'办理记录',kind:'text'},'/api/test/download',{full:true,api});
 },{base,text});
 await page.waitForFunction(()=>document.querySelector('.source-section')?.textContent.includes('提交申请表'));
 const readable=await page.locator('.source-section').textContent();
 for(const value of ['正式期限：2026-10-25','期限待核实','办理进度：等待中','提交凭证：已收件'])assert.ok(readable.includes(value));
 assert.ok(!/record_type|deadline_confirmed|version|values/.test(readable));
 const original='{"version":5,"values":{"experiment":22}}';
 await page.evaluate(async({base,original})=>{
   const {attachmentPreview}=await import(base+'/static/attachments.js');
   attachmentPreview(document.querySelector('#preview'),{name:'实验数据.json',kind:'json',sections:[{locator:'第1段',text:original}]},'/api/test/download');
 },{base,original});
 assert.equal(await page.locator('.preserve-lines').textContent(),original);
 await page.evaluate(async base=>{
   const {CitationView}=await import(base+'/static/genui/citations.js');
   const content=document.createElement('div'),footer=document.createElement('footer');document.body.append(content,footer);
   const view=new CitationView(content,footer,{});
   view.update({id:'execution-test',citations:[{source_id:'tool-result',locator:'记录 internal-id deadline_text',quote:JSON.stringify({kind:'task',id:'internal-id',notice_id:'internal-notice',version:8,status:'pending',data:{title:'提交课程作业',deadline_text:'下周五前'}})}],evidence_sources:[{id:'tool-result',name:'本人日历与待办查询',evidence_kind:'execution'}]},{sources:[]});
   view.open(1);
 },base);
 const citation=await page.locator('.reply-sources-panel').textContent();
 assert.ok(citation.includes('提交课程作业'));assert.ok(citation.includes('下周五前'));
 assert.ok(!/internal-id|notice_id|version|deadline_text/.test(citation));
}
