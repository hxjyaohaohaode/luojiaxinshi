// A personal profile describes the user; only server-issued roles grant workspaces.
export const personalNames = {student:'学生',teacher:'教师',staff:'教职工',other:'个人'};
export function workContexts(user) {
  const result = [{id:'personal',label:(personalNames[user?.profile?.campus_role]||'个人')+' · 我的事务'}];
  if (['counselor','college_admin'].includes(user?.campus_membership?.role)) {
    result.push({id:'college',label:user.campus_membership.role==='counselor'?'辅导员 · 学院事务':'学院管理员 · 学院事务'});
  }
  if (user?.role==='admin') result.push({id:'system',label:'系统管理员 · 系统维护'});
  return result;
}
export function resolveWorkContext(user, preferred) {
  const choices=workContexts(user);
  return choices.some(item=>item.id===preferred)?preferred:choices.some(item=>item.id==='college')?'college':choices.some(item=>item.id==='system')?'system':'personal';
}
export function contextForRoute(user,current,page) {
  const selected=resolveWorkContext(user,current);
  if (/^(notices|notice|new|intake|tasks|calendar|chat|memory|sources|insights)(\/|$)/.test(page)) return 'personal';
  if (/^campus(\/|$)/.test(page)) return selected==='system'?selected:workContexts(user).some(c=>c.id==='college')?'college':selected;
  return selected;
}
export function workspaceNav(context,user) {
  if(context==='college')return [['dashboard','grid','首页'],['campus/publish','plus','发布通知'],['campus/records','doc','发布记录'],['collaboration','check','协作办理'],['campus/members','tasks','学院成员'],['settings','settings','我的']];
  if(context==='system')return [['dashboard','grid','首页'],['campus/members','shield','学院与权限'],['campus/audit','history','权限记录'],['settings','settings','我的']];
  const planning=user?.profile?.campus_role==='teacher'?[['calendar','calendar','日程'],['tasks','tasks','待办']]:[['tasks','tasks','待办'],['calendar','calendar','日程']];
  const cooperation=user?.campus_membership?.role==='student'?[['collaboration','check','协作办理']]:[];
  return [['dashboard','grid','首页'],['notices','doc','通知'],['chat','spark','小信使'],...planning,...cooperation,['sources','history','订阅与来源'],['insights','chart','办理统计'],['settings','settings','我的']];
}
export function primaryWorkspaceNav(context,user) {
  const chat=['chat','spark','小信使'];
  if(context==='college')return [['dashboard','grid','首页'],['campus/publish','plus','发布'],chat,['campus/records','doc','记录']];
  if(context==='system')return [['dashboard','grid','首页'],['campus/members','shield','权限'],chat,['campus/audit','history','记录']];
  return [['dashboard','grid','首页'],['notices','doc','通知'],chat,
    user?.profile?.campus_role==='teacher'?['calendar','calendar','日程']:['tasks','tasks','待办']];
}
