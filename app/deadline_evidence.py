"""Conservative Chinese deadline evidence; no inferred year or event occurrence."""
from dataclasses import dataclass,field
from datetime import date,datetime,timedelta,timezone
import re

CST=timezone(timedelta(hours=8))
ANCHOR=re.compile(r'(?P<full>(?<!\d)(?P<y>20\d{2})[年./-]\s*(?P<m>\d{1,2})[月./-]\s*(?P<d>\d{1,2})日?(?!\d))|(?P<partial>(?<!\d)\d{1,2}月\s*\d{1,2}日)|(?P<relative>通知发布当天|通知发布次日|发布当天|发布次日|今天|今日|明天|后天|当天|次日)')
CLOCK=re.compile(r'(?<!\d)(?P<period>凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|晚间)?\s*(?P<h>\d{1,2})(?:[:：](?P<minute>\d{1,2})(?!\d)|[点时](?:(?P<cnminute>\d{1,2})分?|(?P<half>半)|整)?)(?!\d)')
RELATIVE={'今天':0,'今日':0,'明天':1,'后天':2,'通知发布当天':0,'发布当天':0,'通知发布次日':1,'发布次日':1}


def clocks(text):
    for match in CLOCK.finditer(text):
        h=int(match['h']);m=int(match['minute'] or match['cnminute'] or (30 if match['half'] else 0));p=match['period']
        if m>59 or h>24:continue
        if p in {'下午','傍晚','晚上','晚间'}:
            if h==0:continue
            if h<12:h+=12
            elif h==12 and p!='下午':h=24
        elif p in {'上午','早上','清晨'}:
            if h>=12:continue  # "上午12点" is ambiguous; never guess midnight.
        elif p=='凌晨':
            if h==12:h=0
            elif h>11:continue
        elif p=='中午':
            if h==1:h=13
            elif h not in {11,12,13}:continue
        if h==24 and m:continue
        yield h,m


@dataclass
class DeadlineEvidence:
    days:set=field(default_factory=set)
    pairs:set=field(default_factory=set)
    end_of_day:set=field(default_factory=set)

    def supports_date(self,day,clock):
        return day in self.days or clock=='00:00' and (day,'00:00') in self.pairs

    def supports_time(self,day,clock):
        return (day,clock) in self.pairs


def analyze(quotes,published_at=None):
    result=DeadlineEvidence();floating=[];unknown=False;reference=None
    if published_at:
        value=datetime.fromisoformat(published_at)
        if value.tzinfo is not None:reference=value.astimezone(CST).date()
    for quote in quotes:
        anchors=list(ANCHOR.finditer(quote))
        if not anchors:
            floating.extend(clocks(quote));continue
        for i,anchor in enumerate(anchors):
            day=None
            if anchor['full']:
                try:day=date(int(anchor['y']),int(anchor['m']),int(anchor['d']))
                except ValueError:pass
            elif anchor['relative'] in RELATIVE and reference:
                day=reference+timedelta(days=RELATIVE[anchor['relative']])
            if day is None:unknown=True;continue
            result.days.add(day.isoformat())
            # A new date (even without a year), relative event or sentence ends this binding.
            end=anchors[i+1].start() if i+1<len(anchors) else len(quote)
            tail=re.split(r'[。；;\n]',quote[anchor.end():end],maxsplit=1)[0]
            for hour,minute in clocks(tail):
                target=day
                if hour==24:
                    result.end_of_day.add(day.isoformat());target+=timedelta(days=1);hour=0
                result.pairs.add((target.isoformat(),f'{hour:02}:{minute:02}'))
    bound_days=result.days|{day for day,_ in result.pairs}
    if len(bound_days)==1 and not unknown:
        day=next(iter(bound_days))
        for hour,minute in floating:
            if hour<24:result.pairs.add((day,f'{hour:02}:{minute:02}'))
    return result


def normalize_end_of_day(raw,published_at=None):
    """Accept the explicit 24:00 notation only with a matching full source date."""
    if not isinstance(raw,dict) or not isinstance(raw.get('tasks'),list):return raw
    tasks=[]
    for original in raw['tasks']:
        task=original
        if isinstance(task,dict) and task.get('due_time')=='24:00':
            items=task.get('deadline_evidence',[])
            quotes=[e['quote'] for e in items if isinstance(e,dict) and isinstance(e.get('quote'),str)] if isinstance(items,list) else []
            evidence=analyze(quotes,published_at)
            if task.get('due_date') in evidence.end_of_day:
                task={**task,'due_date':(date.fromisoformat(task['due_date'])+timedelta(days=1)).isoformat(),'due_time':'00:00'}
        tasks.append(task)
    return {**raw,'tasks':tasks}
