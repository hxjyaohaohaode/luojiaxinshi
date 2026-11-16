// Classification is local and deterministic; no model or external service.
export const SOURCE_CATEGORIES=['学校公告','教务教学','资助奖助','就业招聘','学生事务','学院通知','图书馆','校园服务','群聊与公众号','其他'];

export function sourceCategory(data,preset={}){
  if(SOURCE_CATEGORIES.includes(data.category))return data.category;
  if(['wechat_public','qq_group','wechat_group'].includes(data.platform))return '群聊与公众号';
  const id=preset.id||'',name=String(data.name||''),institution=String(data.institution||''),text=name+' '+institution;
  if(['whu-notices','whu-school-target-notices'].includes(id))return '学校公告';
  if(id==='whu-library-notices'||/图书馆/.test(text))return '图书馆';
  if(id.startsWith('whu-employment')||/就业|招聘|宣讲|实习/.test(name))return '就业招聘';
  if(id==='whu-student-aid'||/资助|奖学金|助学金/.test(name))return '资助奖助';
  if(id.startsWith('whu-college-')||['whu-sres-notices','whu-journal-affairs'].includes(id)||/学院|学部/.test(institution))return '学院通知';
  if(id.startsWith('whu-undergrad')||/教务|教学|本科生院|研究生院/.test(text))return '教务教学';
  if(['whu-unit-xgbnew','whu-unit-future'].includes(id)||/学工|团委|学生工作/.test(text))return '学生事务';
  if(/财务|后勤|国际交流|校园|校医院|信息化/.test(text))return '校园服务';
  if(preset.group&&preset.group!=='校级部门'&&preset.group!=='校级来源'&&!String(preset.group).includes('部门'))return '学院通知';
  return '其他';
}
