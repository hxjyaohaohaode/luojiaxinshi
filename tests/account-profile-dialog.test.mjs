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

function summary(profile){
  const start=source.indexOf('function settingsSummary(){'),end=source.indexOf('\nfunction updateSettingsSummary(',start);
  assert.ok(start>=0&&end>start,'Run the complete production settings summary');
  const context={state:{session:{user:{profile,display_name:'本人',username:'profile-check'},ai:{},genui:{}}}};
  vm.createContext(context);
  return vm.runInContext(source.slice(start,end)+'\nsettingsSummary();',context);
}

test('the real profile dialog preserves a deliberately cleared school when another field is saved',async()=>{
  const profile={school:'',college:'原学院',campus_role:'student'},view=render(profile),calls=[];
  assert.equal(view.school,'','An explicit empty value must not become a default on reopening');
  await saveProfileForm(async(path,options)=>{calls.push({path,...options});return {profile:{...profile,college:'新学院'}};},view.form,{school:view.school,college:'新学院'});
  assert.deepEqual(calls,[{path:'/profile',method:'PATCH',json:{changes:{college:'新学院'},expected:{college:'原学院'}}}]);
  assert.equal(profile.school,'');
  assert.equal(summary(profile).school,'原学院','The settings summary must preserve the same explicit empty school');
  assert.equal(summary({...profile,college:'新学院'}).school,'新学院','Saving another field must not restore a cleared school in the summary');
  assert.equal(summary({school:''}).school,'','Clearing every optional location field must leave the summary empty');
});

test('the real profile dialog retains the original default only when the school value is missing',()=>{
  assert.equal(render({college:'原学院',campus_role:'student'}).school,'武汉大学');
  assert.equal(summary({college:'原学院',campus_role:'student'}).school,'武汉大学 · 原学院');
  assert.equal(render({school:null,college:'原学院',campus_role:'student'}).school,'武汉大学');
  assert.equal(summary({school:null,college:'原学院',campus_role:'student'}).school,'武汉大学 · 原学院');
  assert.equal(summary({school:'本人填写的学校',college:'原学院'}).school,'本人填写的学校 · 原学院');
});
