# 动效源文件

本目录保存用户提供的两份 SVG 动效原稿，内容与原文件一致。仓库根目录运行：

```powershell
python scripts/build_motion_assets.py
```

提取器生成 `static/motion-assets.js`、`static/motion-source.css` 和 `static/assets/motion-provenance.json`。两份源文件也包含在源码发布包中；应用运行时只加载生成后的资源。
