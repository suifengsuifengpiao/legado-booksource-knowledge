# samples/sweep/ · A2 的 22 格（11 个结构字符 × clean/note 两形态）

**来源**：主灵盲审原始夹具（`/tmp/blind/sweep_*`），**逐字节复制**进包，未改一个字节（含 `bookSourceName` 的 `S0`–`S10`）。
保留原样是为了让「夹具指纹」可追：本包的这 22 份与盲审那份 `cmp` 一致，接收方不必猜我有没有改过。

## 这 22 格在证明什么

每一格是同一个 url，只差**尾部有没有一个裸换行**：

| 形态 | exploreUrl 里 url 的写法 | 解析走向 |
|---|---|---|
| `_clean` | `https://a.com/b<CH>1234567/x/{{page}}` | JSON 直接可解 → 结构成功路径 |
| `_note` | 同上 + url 字符串末尾一个裸换行 | `json.loads` 报 `Invalid control character` → 按宿主宽容度复解成功 → **NOTE 路径** |

`<CH>` 是 11 个结构字符：`( ) ; ! * $ | < > [ ]`（旧 `_r5_raw_urls` 的切分字符表）。

**判据**：两格必须报**同一段** `b<CH>1234567`。

- v1.15.15：11 个 `_note` 格全部 `exit=0` 静默 —— 旧实现在 NOTE 路径从原文用 `https?://[^\s"'\\]+` 粗提，再按这 11 个字符切碎、只留 `http` 开头的碎片，`b(` 之后整段被丢掉，数字也跟着消失。**同一份缺陷，加个换行就消失**。
- v1.15.16：22 格 `22/22` 全报，且 clean / note 段的字符串逐字符相同（`enumerate(arr)` 逐条判 `url` 字段，不再从原文猜）。

## 索引（N → 字符）

| N | 字符 | clean | note |
|---|---|---|---|
| 0 | `(` | `sweep_0_clean.json` | `sweep_0_note.json` |
| 1 | `)` | `sweep_1_clean.json` | `sweep_1_note.json` |
| 2 | `;` | `sweep_2_clean.json` | `sweep_2_note.json` |
| 3 | `!` | `sweep_3_clean.json` | `sweep_3_note.json` |
| 4 | `*` | `sweep_4_clean.json` | `sweep_4_note.json` |
| 5 | `$` | `sweep_5_clean.json` | `sweep_5_note.json` |
| 6 | `\|` | `sweep_6_clean.json` | `sweep_6_note.json` |
| 7 | `<` | `sweep_7_clean.json` | `sweep_7_note.json` |
| 8 | `>` | `sweep_8_clean.json` | `sweep_8_note.json` |
| 9 | `[` | `sweep_9_clean.json` | `sweep_9_note.json` |
| 10 | `]` | `sweep_10_clean.json` | `sweep_10_note.json` |

## 怎么复算

```bash
python3 evals/run_evals.py 2>&1 | grep a2_sweep       # 22 条，每条断言「[JSON[0]]「T」+ 段名 b<CH>1234567」且 forbid「[原文抽取]」
python3 scripts/check_request_layer.py samples/sweep/sweep_0_note.json --strict   # WARN=1(阻断) exit=1
```

**边界**：这 22 格只覆盖「url **路径**里含结构字符 + 长数字」这一族。查询串里的长数字按 v1.15.16 口径**不报**（见 `references/maintenance.md` 的放宽面登记），所以不在此处设格。
