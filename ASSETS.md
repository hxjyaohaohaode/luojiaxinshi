# 珞珈小信使视觉资产

本项目的原创应用角色。图像使用内置 imagegen 生成；第二张使用第一张作为角色一致性参考。两张图片均为带真实透明通道的 PNG，已保存于项目内，页面不依赖外部图床。

## 风格依据

参考武汉大学官网的 [武大标识规范](https://www.whu.edu.cn/xxgk/wdbs.htm)：珞珈绿 RGB(17,87,64)、珞珈蓝 RGB(0,37,84)，并使用樱花粉、暖白及少量浅金配色。老图书馆、青瓦与樱花作为校园意象，转化成原创青瓦帽、信使披风、通知卡片与书本。图片不含校徽或校名印章，角色身份为本应用原创形象。

## 文件与页面用途

| 文件 | 用途 |
|---|---|
| `static/assets/luojia-messenger-welcome.png` | 挥手、拿通知卡片；欢迎区与登录页 |
| `static/assets/luojia-messenger-reading.png` | 安静捧书；列表空状态与通知提交提示 |

使用固定宽高和异步解码避免图片加载引起跳动。小角色仅在适合的位置出现，原文和表单中不铺设装饰。非首屏角色延迟加载；公开装饰资产允许浏览器缓存一天，账号和业务数据继续使用 `no-store`。

轻互动提供上下文提示、键盘操作、关闭选项以及系统减少动效支持。必要的保存、撤回与错误反馈不受陪伴开关影响。无需音频、额外授权或第三方请求。

## 最终生成提示词

### 欢迎姿态

```text
Use case: stylized-concept. Asset type: production web application mascot, transparent PNG cutout, a single reusable character illustration, square 1024x1024 composition. Create an original adorable campus notice messenger called '珞珈小信使' for a Wuhan University campus notification assistant.
Subject: a small round ivory-white bird, soft chubby silhouette, friendly tiny dark navy eyes, little pale golden beak, understated rosy cheeks, short rounded wings. It wears a refined forest-green student messenger cape and a small satchel, a simple green tiled-roof shaped cap inspired by the elegant traditional roof silhouette of Wuhan University's historic library, with one delicate pale-pink five-petal cherry blossom on the cap. One wing proudly holds a cream folded notification card with three neat dark-green horizontal strokes and a small check symbol; the other wing waves gently. The paper notice and scholarly roof cap make the character distinctive and related to turning notices into action.
Style: premium editorial 2.5D illustration, soft matte porcelain/paper-clay texture, clean confident shapes, fine crafted edges, gentle dimensional shading, charming but calm and suitable for a serious university productivity application.
Main colors: official Luojia green #115740 and Luojia navy #002554, ivory #F8F7EF, restrained light cherry pink and pale warm gold.
Pose: full body centered, slight three-quarter view facing toward the viewer's left; entire character and card inside canvas, clear silhouette at 160px. Character fills about 84% of canvas, even breathing room around it.
Lighting: soft neutral studio lighting, subtle contact shadow only, NO background scene. Transparent background with real alpha, no white rectangle, no checkerboard drawn into the art.
No words, no Chinese characters, no typography, no watermark, no university seal, no official university logo. This is an original app mascot inspired by campus identity, not a claim of an officially appointed mascot. Avoid photorealism, glossy plastic, neon gradients, excessive stars, noisy texture, baby toys, exaggerated anime eyes, extra limbs, and multiple characters.
```

### 捧书姿态

```text
Use case: identity-preserve. Edit target: the supplied original campus bird mascot. Create a second consistent pose for an empty-state illustration inside a refined university productivity app.
Preserve this EXACT character identity: same round ivory bird, navy eyes, golden beak and feet, subtle pink cheeks, elegant green roof-shaped cap, one pink five-petal cherry blossom, green cape with gold edging, small matching messenger satchel. Preserve the same premium soft matte 2.5D illustration medium, lighting, palette #115740 green / #002554 navy / ivory / cherry pink, detailed but clean edges.
Change only the pose, facial mood, and handheld prop: the bird is calmly sitting, feet visible, a gentle closed-beak smile with open attentive eyes; both wings cradle a small open cream notebook with just 2 or 3 understated green ruled lines. No checkmarks, no check circles, no success badge, so it conveys 'ready when you are' rather than a confirmed success.
Full body centered, compact charming rounded silhouette readable at 90 to 120 px. Isolated character ONLY, real transparent alpha background; soft tiny contact shadow may remain. Character fills 82 percent of a square canvas with generous clean edges. No scene, no extra floating objects, no panel background, no words, no official seal, no typography, no watermark, no copied university logo. Keep two wings and two feet anatomically consistent.
```
