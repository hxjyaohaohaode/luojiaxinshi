先把已经确定的准备时间安排好。以下为示例，不代表学校正式期限。

```genui
{"op":"begin","v":1}
{"op":"state","set":{"hours":2,"checked":[]}}
{"op":"node","id":"root","type":"Stack","children":["heading","hours","total","steps"]}
{"op":"node","id":"heading","type":"Heading","props":{"text":"本周准备计划（示例）"}}
{"op":"node","id":"hours","type":"Slider","props":{"label":"每天安排","min":0,"max":8,"step":0.5,"bind":"hours","unit":"小时"}}
{"op":"node","id":"total","type":"Stat","props":{"label":"七天合计","value":{"$expr":"round(hours*7,1)"},"unit":"小时"}}
{"op":"node","id":"steps","type":"Checklist","props":{"label":"准备事项","bind":"checked","items":[{"id":"a","label":"核对通知原文"},{"id":"b","label":"准备所需材料"}]}}
{"op":"end"}
```

正式截止时间仍需对照通知原文。
