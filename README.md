# 珞珈信使

珞珈信使帮武汉大学学生收通知、查截止日期、准备材料。可以订阅学院和职能部门的官网栏目，也可以把群里的通知原文和附件存进来。需要办理的事项经你确认后进入待办和日历，每条都能回看原文。

## 现在开始使用

1. Windows 安装 Python 3.12，把仓库克隆或解压到本机，双击根目录的 `启动工作台.cmd`。浏览器会打开 [本机工作台](http://127.0.0.1:8765)。
2. 注册并登录。第一次进入首页，跟着「新手指引」点「收通知」，或选「我想订阅武大官网」。
3. 想先看一遍操作，在指引里点「看视频演示」。以后可以从「我的 → 个人资料 → 新手指引」重看。[观看完整演示](static/assets/onboarding/first-steps.mp4)

官网通知与公开附件由后台采集。需要小信使帮忙分析通知时，再按说明配置小米 MiMo。[通知来源](docs/integrations/INTEGRATIONS.md) · [模型配置](docs/integrations/MIMO_INTEGRATION.md)

## 按需查阅

| 想做什么 | 从哪里开始 |
| --- | --- |
| 了解通知、待办、日历和对话的完整用法 | [使用与功能详解](docs/product/GUIDE.md) |
| 在 macOS 或 Linux 启动，或参与开发 | [协作开发指南](CONTRIBUTING.md) |
| 部署服务、备份数据、恢复工作台 | [运行与维护](docs/operations/OPERATIONS.md) |
| 查看测试方法和最近的运行结果 | [测试说明](docs/operations/TESTING.md) · [GitHub Actions](https://github.com/hxjyaohaohaode/luojiaxinshi/actions/workflows/checks.yml) |
| 找项目方案、视觉稿、架构和历史记录 | [文档目录](docs/README.md) |

后端代码在 [app](app/)，前端和界面资源在 [static](static/)，测试在 [tests](tests/)。项目当前版本为 **1.24.0**。[第三方资源与许可](THIRD_PARTY_NOTICES.md)
