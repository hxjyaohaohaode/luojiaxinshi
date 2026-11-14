# 轻量工作台与分钟刷新证据

## 对应目标与保持的业务语义

本轮补足LJ-117／119／121的首页、日历刷新成本。首页仍统计本人全部通知与事项，日历仍获得全部日期记录；不把前50条当成完整库存。原文、草稿、材料正文、办理备注与证据仍由完整详情读取，编辑和导出使用完整事项与现有版本控制。

`app/notice_queue.py`拆成稳定事实加载`annotation_inputs`与纯计算`annotate_inputs`。已有通知列表继续经过相同函数。分钟刷新重新执行适用性、生命周期、重点时间、推荐和收件意图规则，不复制另一套判断。日期与跟进计算抽到`app/task_timing.py`，完整事项与轻量事项共用；日期级期限在当天不会变成“已过期”，也不补造正式时刻。

## 接口契约

`GET /api/workspace/projection?include=notices,tasks`支持仅选择`tasks`或`notices`。顶层结构：

```json
{
  "projection": "light",
  "revision": "按数据库实例、本人、稳定版本计算的哈希",
  "clock": 32000000,
  "clock_only": false,
  "included": ["notices", "tasks"],
  "counts": {"notices": 61, "tasks": 61},
  "notices": [],
  "tasks": []
}
```

上例数字仅用于说明格式，数组中的实体按本人当前库存返回，没有隐藏的50条截断。`counts`始终为完整本人库存，即使只请求其中一种实体。

| 返回部分 | 内容 |
|---|---|
| 通知稳定字段 | ID、标题、来源、时间、版本、状态、处理方式、事项数量、材料待核对数量、更新待核对数量、归组与阶段摘要。 |
| 通知派生字段 | `intent`、`recommended`、`assessment`、`tracking`、`publication_context`。重点日期与过期判断重算；去掉原文引句和草稿摘要。 |
| 事项稳定字段 | ID、所属通知、版本、状态、日期／时段／地点、关键工作流状态、复核／变更／日历标记与材料数量。`data.details=''`、`data.materials=[]`；单条也有`projection:'light'`。 |
| 事项派生字段 | `overdue`、`due_soon`、`followup_due`、`handling_state`。办理状态的种类与标签保持；说明最多240字，并以`detail_truncated`标识截断。 |

分钟请求使用`clock_only=1&revision=<上次稳定版本>`。稳定快照命中时`clock_only:true`，通知仅返回ID及上述派生字段，事项仅返回ID及上述派生字段；客户端按ID合并。稳定版本变化、进程重启、缓存过期或容量淘汰时`clock_only:false`，返回完整轻量数组，替换该实体集合。不能把`clock_only:true`的稀疏数组当成新的全部库存。

`revision`不包含分钟值，通知、事项、账号与来源相关提交会使它变化；校园接收版本和对应不可变策略也纳入版本。`deployment_instance_id`防止恢复到相同用户／版本计数后误用原缓存。`clock`为UTC分钟值；条件请求使用私人ETag，跨账号不会共用响应。

## 保留日历备注全文搜索

`GET /api/workspace/calendar-search?q=关键词`只在用户显式输入关键词时读取本人的事项标题、地点、说明。按原日历的“标题＋空格＋地点＋空格＋说明”小写包含规则匹配；参数trim后最多500字符。结果为`{query,revision,task_ids}`，只返回全部本人命中ID，不返回正文、不按日期截断。日期、完成状态、类别与本人事项范围继续由日历已有规则处理。选中事项查看、办理和修改时读取完整详情。

## 缓存与权限边界

缓存位于单个应用进程，键绑定数据库绝对路径、账号和请求实体集合；内部稳定输入包含推导规则所需的已保存草稿。每次先执行会话认证，再在读取快照的事务内核实账号仍存在。注销后认证不可通过，本进程已缓存项也主动移除。

缓存最多24项，按序列化大小加对象开销估算限制为48MiB，5分钟过期。超出预算的账户仍返回完整轻量数据，但不保留快照；下一次请求返回`clock_only:false`并重新计算。因而“分钟不重读草稿”的验证只适用于有效缓存命中，不能宣称所有规模和内存配置都完全没有数据库读取。恢复、回滚、并发修改仍依据提交后的数据库版本，缓存不授予读取或写入权限。

## 可复现验证

`tests/test_workspace_projection.py`覆盖：

- 61条通知和61条事项的完整覆盖；通知意图／推荐／数量与原API一致；事项日期、日历窗口、状态与原API一致。
- 合成长说明、材料和私有备注夹具的轻量响应小于原两个数组响应合计的35%；响应中不存在私有备注标记。
- 跨北京时间午夜的日期级期限、个人跟进、通知机会过期和校园发布有效期；稳定版本保持，分钟投影变化。
- 缓存命中的分钟请求禁止重建稳定快照，并通过SQL跟踪断言不读`draft`、`sections`或全事项行。
- 稳定修改和恢复实例使快照失效；回滚不发布虚假版本；过期、淘汰和超限不会返回残缺库存。
- 匿名、其他账号和注销后均不能取得原账号数据；其他账号ETag不能造成304越界。
- 日历命中第61条的说明、Unicode大小写和地点搜索，完整ID库存与账号隔离。

```bash
CAMPUS_AUTO_LOAD_ENV=0 .venv/bin/python -m pytest \
  tests/test_workspace_projection.py tests/test_notice_queue.py \
  tests/test_proactive_tracking.py tests/test_sprint_lists.py \
  tests/test_sprint_campus_delivery.py --disable-warnings
```

测试全为临时数据库、合成记录和捕获供应商调用。没有依靠真实学校系统授权、生产账号或真实通知投递来证明通过。最终提交的全量验证以总报告和对应CI记录为准。
