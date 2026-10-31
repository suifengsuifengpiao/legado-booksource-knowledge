# 这个目录不是「发行版」

**最新技能包不在这里，在仓库的「发行版 / Releases」页面：**

https://gitee.com/z157001/legado-booksource-knowledge/releases

## 为什么容易找错

Gitee 有两个地方都叫 releases：

| 你点的地方 | 实际是什么 | 有什么 |
|---|---|---|
| 「代码」标签页 → `releases/` 文件夹（就是这个目录） | git 仓库里的**普通文件夹** | 只有 2026-10-26 之前的早期归档 |
| 仓库的「发行版」标签页 | Gitee 的 **Release 功能** | v1.14.10-b2 ～ v1.15.5 全部技能包与源码包 |

手机网页版顶部的标签栏只有「概览 / 代码 / Issues / Pull Requests」，**没有「发行版」入口**，所以要往下拉点「桌面版」，或直接在地址栏输入上面的链接。

## 本目录里的 4 个文件（历史归档，不再更新）

| 文件 | 时间 |
|---|---|
| `legado-booksource-debug_v1.14.9.skill` | 2026-10-26 |
| `legado-booksource-debug_v1.14.10.skill` | 2026-10-26 |
| `legado-tools_v1.14.10.zip` | 2026-10-26 |
| `legado-tools-b2-runtime_v1.14.10.zip` | 2026-10-26 |

这些是早期直接 `git add` 进来的。之后按 **P0-4 裁决**：二进制产物不再进入 git 树（每次提交都会永久膨胀仓库体积、且无法真正删除），统一走 Release 附件。

**所以从 v1.15.0 起，git 里只有源码与文档，`.skill` 包一律在发行版页面。**
