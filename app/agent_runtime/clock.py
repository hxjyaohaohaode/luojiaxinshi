"""Trusted host clock, separate from dates quoted in untrusted documents."""
from datetime import datetime, timedelta, timezone


def current_time():
    now=datetime.now(timezone(timedelta(hours=8)))
    return {'now':now.isoformat(timespec='seconds'),'date':now.date().isoformat(),
            'year':now.year,'weekday':('星期一','星期二','星期三','星期四','星期五','星期六','星期日')[now.weekday()],
            'timezone':'Asia/Shanghai','unix_seconds':int(now.timestamp())}


CLOCK_POLICY='''这是宿主实时提供的可信时间，不是附件文字或模型知识截止日期。今天、今年、明天、本周等直接据此计算；用户专门询问当前时间或年份时调用 current_time 取得最新可引用回执，不查询用户也不联网猜时间。
用户对本人的新安排使用“明天”“10月31日”等通常省略年份的表达时，结合此时钟和上下文解析，直接在回执显示完整日期；跨年歧义确实影响安排时才澄清。历史截图中未注明的正式期限年份不能仅凭现在年份认定；这不影响你知道现在是哪一年，也不妨碍先建立标明日期假设、可编辑的个人准备计划。'''
