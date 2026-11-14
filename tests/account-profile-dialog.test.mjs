import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {bindProfileForm,saveProfileForm} from '../static/profile-editor.js';

const source=await readFile(new URL('../static/app.js',import.meta.url),'utf8');
const line=prefix=>{const value=source.split('\n').find(item=>item.startsWith(prefix));assert.ok(value,prefix);return value;};
// Run the actual dialog and field renderer, then the actual profile save helper.
// This records field values and outgoing CAS changes; it is not a browser claim.
function render(profile){
  const form={isConnected:true,querySelector:()=>null},state={session:{user:{profile}}};let html='';
  const context={state,bindProfileForm,moveSelection(){},$:(selector)=>selector==='#profile-form'?form:null,
    esc:value=>String(value??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),
    showDialog(title,value){assert.equal(title,'个人条件');html=value;}};
  vm.createContext(context);vm.runInContext([line('const field='),line('const area='),line('function profileDialog('),'profileDialog();'].join('\n'),context);
  const school=html.match(/<input name="school"[^>]*value="([^"]*)"/);assert.ok(school);
  return {school:school[1],form};
}

test('the real profile dialog preserves a deliberately cleared school when another field is saved',async()=>{
  const profile={school:'',college:'原学院',campus_role:'student'},view=render(profile),calls=[];
  assert.equal(view.school,'','An explicit empty value must not become a default on reopening');
  await saveProfileForm(async(path,options)=>{calls.push({path,...options});return {profile:{...profile,college:'新学院'}};},view.form,{school:view.school,college:'新学院'});
  assert.deepEqual(calls,[{path:'/profile',method:'PATCH',json:{changes:{college:'新学院'},expected:{college:'原学院'}}}]);
  assert.equal(profile.school,'');
});

test('the real profile dialog retains the original default only when the school value is missing',()=>{
  assert.equal(render({college:'原学院',campus_role:'student'}).school,'武汉大学');
});
