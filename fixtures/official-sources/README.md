# Public-source parser excerpts

Captured on 2026-10-29 by anonymous public HTTPS GET requests. These compact
HTML fixtures retain the observed list/article regions; unrelated navigation
and footer examples are minimal test chrome. They are not authenticated data.

- `whu-index.html`: https://www.whu.edu.cn/tzgg.htm — the current table's 10 rows.
- `journal-index.html`: https://journal.whu.edu.cn/undergraduate/affairs/index — the current list's 10 rows, including cross-column article paths.
- `whu-article.html`: https://www.whu.edu.cn/info/5231/276744.htm — original heading, publication date, and article region.
- `journal-article.html`: https://journal.whu.edu.cn/graduate/notice/20260918whfl — original heading, publication date, and article region.
- `sres-index.html`: https://sres.whu.edu.cn/xxgk/tzgg.htm — the 15 current notice rows, including a pinned April notice and the original dynamic article link.
- `sres-article.html`: https://sres.whu.edu.cn/info/3771/346681.htm — original title, publication date, body and PDF attachment link.
- `sres-pdf-article.html`: https://sres.whu.edu.cn/info/3771/345931.htm — an attachment-only article. Its literal `showVsbpdfIframe` PDF URL is retained; the unrelated list of page preview images is omitted.

The SRES full-page captures are in `artifacts/sres-demo-2026-10-29/`; they
were fetched anonymously with the application's public HTTP transport.

Full fetched pages and live-read evidence are under
`artifacts/public-sources-2026-10-29/`. Unit tests run offline and do not claim
that every article, permission-controlled page, or future site layout works.
