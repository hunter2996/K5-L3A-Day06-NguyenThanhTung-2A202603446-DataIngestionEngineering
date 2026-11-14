# Báo cáo cá nhân — Day 6: Data Ingestion Engineering

- **Họ và tên**: Nguyễn Thanh Tùng
- **MSSV**: `2A202603446`
- **Tài liệu nguồn & mã nguồn chính**: [data/manifest.json](../../data/manifest.json), [benchmark/questions.json](../../benchmark/questions.json), [starter/src/run.py](../../starter/src/run.py)

---

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang**:
  - **Chủ đề & nguồn**: Sách giáo trình *Introductory Statistics 2e* (Barbara Illowsky & Susan Dean, OpenStax, Rice University, nguồn tại `https://openstax.org/details/books/introductory-statistics-2e`, bản PDF cục bộ tại `starter/data/introductory-statistics-2e_-_WEB.pdf`, `sha256`: `a79a953b75e570030c74ea6f700b8bd70f41dc8c01bf4e9618e6a0adba3a382a`, PDF Producer `Prince 16.2`, CreationDate `2026-04-20`, accessed `2026-11-13`).
  - **Quyền sử dụng**: Creative Commons Attribution Non-Commercial ShareAlike 4.0 International License (**CC BY-NC-SA 4.0**, ghi rõ trên trang 4 của PDF) — cho phép sử dụng, trích đoạn và chạy model cục bộ cho mục đích học tập/phi thương mại với ghi công tác giả. Không gửi dữ liệu lên API bên ngoài.
  - **Số trang & quy tắc tính trang**: Tổng PDF có `847` trang; chọn **`130` trang nội dung hợp lệ** thuộc Chương 1–3 (`Chapter 1: pp. 17–56` = 40 trang, `Chapter 2: pp. 77–132` = 56 trang, `Chapter 3: pp. 179–212` = 34 trang), tổng `274,966` ký tự thô và `265,356` ký tự sau chuẩn hóa. Quy tắc chọn: giữ lại các trang vật lý đánh số 1-indexed chứa bài giảng (`Introduction`, sections `1.1–1.4`, `2.1–2.7`, `3.1–3.5`), bài thực hành lab (`1.5–1.6`, `2.8`, `3.6`), `Key Terms` và `Chapter Review`; loại bỏ bìa/trang trắng (`1–2`), mục lục/bản quyền (`3–16`), phần bài tập `Practice`/`Homework`/`Solutions` (`57–76`, `134–178`, `214–238`), hai trang ranh giới `Formula Review` bị rớt ký hiệu công thức vector và cắt giữa trang sang `Practice` (`133`, `213`), cùng Chương 4–13 (`239–847`).

- **Chuẩn hóa, lỗi và giới hạn**:
  - Hàm `normalize_text` trong [starter/src/ingestion.py](../../starter/src/ingestion.py) áp dụng Unicode NFKC, xóa zero-width/BOM (`\u200b`, `\ufeff`), chuẩn hóa NBSP (`\xa0`), loại bỏ header/footer lặp OpenStax (`Access for free at openstax.org`, dòng tiêu đề kèm số trang sách), trích xuất `book_page` trước khi xóa footer, và nối dòng bị ngắt cứng trong PDF thành đoạn văn logic phân tách bằng `\n\n` (bảo toàn ranh giới tiêu đề mục, `EXAMPLE`, `TRY IT`, `Figure`, `Table`, gạch đầu dòng).
  - **Lỗi trích xuất & chẩn đoán đã ghi nhận** ([results/ingestion_errors.json](../../results/ingestion_errors.json)): `12` bản ghi chẩn đoán trên 130 trang — gồm `1` trang mật độ text thấp (`p.127`, `246` ký tự chuẩn hóa do nhiều bảng/ảnh minh họa) và `11` trang có khoảng trống quanh dấu `=` do `pypdf` không đọc được công thức dựng bằng vector/SVG (`pp. 87, 99, 111, 180, 181, 182, 188, 189, 197, 202, 203`). Ngoài ra, biểu đồ (`histogram`, `box plot`, `tree/Venn diagram`) chỉ giữ được caption/văn bản mô tả xung quanh, và `Stem Leaf` table trên `p.78` bị trải phẳng thành chuỗi số trên một dòng.

- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí**:
  - **Embedding**: Provider `sentence-transformers (local)`, runtime `sentence-transformers==6.3.0` (`torch==2.15.0+cpu`, `transformers==5.23.0`), model `sentence-transformers/all-MiniLM-L6-v2`, **`384` chiều**, chuẩn hóa vector L2 (`normalize_embeddings=True`), dùng chung cùng một hàm encode và không có fallback ngẫu nhiên/mock ([starter/src/embeddings.py](../../starter/src/embeddings.py)).
  - **Vector store & search mode**: `PostgreSQL 16.16` + `pgvector 0.8.7` chạy qua Docker (`day6_student_starter-postgres-1`, `127.0.0.1:55433`, DB `day6_lab`), metric **cosine distance (`<=>`)**, chế độ **exact search** (sequential scan không dùng HNSW/IVFFlat nên không có sai số gần đúng ở quy mô 365–641 chunks).
  - **Kiểm chứng idempotency & lọc SQL**: Chạy lại `store.upsert("B", ...)` giữ nguyên số chunk `365 -> 365` (`deleted_obsolete = 0`); kiểm thử riêng với key ngoài `ALLOWED_FILTER_KEYS` ném `ValueError` và kiểm thử rút gọn chunk chứng minh `deleted_obsolete = 1` ([starter/src/store.py](../../starter/src/store.py)).
  - **Lệnh chạy tái lập**: Trong `starter/`, chạy `.\.venv\Scripts\python.exe -m src.run`.
  - **Chi phí**: **\$0.00** (chạy 100% local CPU, `0` token API đám mây). Pipeline embed tổng `1,006` document chunks (`555,619` ký tự: `641` chunks A + `365` chunks B; C dùng lại hoàn toàn vector của B) và `20` query trong tổng `32.304s`.

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn**:
  - **Trường bắt buộc**: `document_id` (`openstax-intro-stats-2e`), `source` (`starter/data/introductory-statistics-2e_-_WEB.pdf`), `page` (số trang vật lý 1-indexed của PDF để đối chiếu chính xác nguồn).
  - **Trường lọc bổ sung**:
    1. `chapter` (`chapter_1`, `chapter_2`, `chapter_3`): suy xuất xác định (deterministic) từ PDF outline bookmark; chọn vì các thuật ngữ nền tảng (*sample*, *mean*, *outlier*, *bar graph*, *probability*, *with replacement*) xuất hiện lặp lại ở nhiều chương với ngữ cảnh khác nhau.
    2. `content_type` (`lesson`, `lab`, `review`): phân loại theo tiêu đề section từ PDF outline (`1.5/1.6/2.8/3.6` -> `lab`; `Key Terms`/`Chapter Review` -> `review`; bài giảng còn lại -> `lesson`); chọn để tách định nghĩa cô đọng cuối chương (`review`) khỏi phần diễn giải chi tiết hoặc bài tập trên lớp.
  - **Trường truy vết phụ trợ**: `section`, `chapter_title`, `book_page` (số trang in ở footer), `chunk_index`, `char_len`.

---

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C)**:
  - **Strategy A (Baseline fixed-size)**: `fixed_size(size=500, overlap=50)`, giữ metadata chuẩn, **không filter** (`filters=None`), tạo `641` chunks (min `64`, median `500`, mean `453.5`, p95 `500`, max `500` ký tự; tổng `290,721` ký tự có overlap).
  - **Strategy B (Structure-aware, unfiltered)**: `by_paragraph(max_size=1000)` (gắn tiêu đề đơn lẻ vào đoạn kế tiếp, tách đoạn quá dài theo ranh giới câu, gộp đoạn kế tiếp tối đa `1000` ký tự, overlap `0`), metadata giữ nguyên như A, **không filter** (`filters=None`), tạo `365` chunks (min `79`, median `811`, mean `725.7`, p95 `989`, max `1000` ký tự; tổng `264,898` ký tự).
  - **Strategy C (Structure-aware + Metadata filter)**: Dùng **chính xác cùng 365 chunks, metadata và 365 vector của Strategy B** (`upserted` từ `chunks_b`, `vectors_b`). **Khác biệt duy nhất giữa B và C**: khi truy vấn trong benchmark có `question["filter"] != null`, `PgVectorStore.search` áp dụng `WHERE` SQL chính xác trên `chapter` / `content_type` trước khi xếp hạng cosine top-3; các câu `filter: null` chạy không filter giống hệt B.

- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence**:
  - Bộ [benchmark/questions.json](../../benchmark/questions.json) gồm **20 câu** (`9 direct`, `6 conditional`, `5 paraphrase`):
    - **Dev (`15` câu: `q01–q15`)**: phủ các section `1.1–1.3`, `2.2–2.3`, `2.5`, `2.7`, `3.1–3.3`; gồm **`4` câu có metadata filter** (`q03`, `q05`: `chapter_1`; `q09`: `chapter_2`; `q14`: `chapter_3`).
    - **Test (`5` câu: `q16–q20`)**: **tách rời cả section và gold page** khỏi `dev` (`1.4` p.47 `q16`, `2.4` p.107 `q17`, `2.6` p.117 `q18`, `3.4` p.195 `q19`, `Chapter 3 Key Terms` p.212 `q20`); gồm **`3` câu có metadata filter** (`q16`: `{"chapter": "chapter_1"}`, `q18`: `{"chapter": "chapter_2"}`, `q20`: `{"chapter": "chapter_3", "content_type": "review"}`) và `2` câu `filter: null` (`q17`, `q19`). (Rủi ro rò rỉ còn lại: dev và test vẫn thuộc cùng một giáo trình và nhóm tác giả.)
  - **Kiểm chứng evidence**: Toàn bộ `20` cặp (`gold_source_id`, `gold_page`, `evidence_quote`, `evidence_clauses`) cùng `alternative_gold` đã được kiểm tra khớp nguyên văn 100% trên text chuẩn hóa từ `load_pdf`, và điều kiện `filter` không chứa bất kỳ số trang hay câu trả lời vàng nào. Trong `evaluate_query`, `Evidence Hit@3` chỉ tính đạt khi **cùng một chunk đơn lẻ** nằm trong top-3 khớp `source/page` và chứa đầy đủ mọi mệnh đề trong `evidence_clauses` (hoặc toàn văn `evidence_quote`); các ca bằng chứng bị xé qua nhiều chunk cùng trang được log riêng vào `split_evidence_union_top3` để phân tích lỗi.

- **Tiêu chí chọn chiến lược đã chốt trước khi xem test**:
  - Ghi trước trong [benchmark/questions.json](../../benchmark/questions.json) và [artifacts/experiment_log.csv](../../artifacts/experiment_log.csv) trước khi chạy truy vấn test: ưu tiên theo thứ tự **(1)** `dev Evidence Hit@3`, **(2)** điểm đánh giá thủ công `Chunk Coherence` & `Grounding Quality` (`/2`), **(3)** `dev Hit@1` và tỷ lệ tuân thủ metadata filter (`filter compliance`), **(4)** hiệu quả lưu trữ/embed/latency. Không tinh chỉnh tham số B hay C sau khi quan sát tập `test`.

---

## Kết quả

| Strategy | Split | Hit@1 (`n/N`, %) | Evidence Hit@3 (`n/N`, %) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A (`fixed_size 500/50`, no filter) | `dev` | `4/15` (`26.7%`) | `5/15` (`33.3%`) | 641 | Embed `18.543s` + Upsert `0.307s` + Search 20q `0.527s` | \$0 (CPU) |
| A (`fixed_size 500/50`, no filter) | `test` | `2/5` (`40.0%`) | `2/5` (`40.0%`) | 641 | (dùng chung index A; query embed 20q `0.262s`) | \$0 (CPU) |
| B (`by_paragraph 1000`, no filter) | `dev` | `8/15` (`53.3%`) | `12/15` (`80.0%`) | 365 | Embed `13.510s` + Upsert `0.155s` + Search 20q `0.398s` | \$0 (CPU) |
| B (`by_paragraph 1000`, no filter) | `test` | `5/5` (`100.0%`) | `5/5` (`100.0%`) | 365 | (dùng chung index B; query embed 20q `0.262s`) | \$0 (CPU) |
| C (`by_paragraph 1000 + filter`) | `dev` | `8/15` (`53.3%`) | `13/15` (`86.7%`) | 365 (dùng lại B) | Reuse vectors B + Upsert `0.150s` + Search 20q `0.457s` | \$0 (CPU) |
| C (`by_paragraph 1000 + filter`) | `test` | `5/5` (`100.0%`) | `5/5` (`100.0%`) | 365 (dùng lại B) | (dùng chung index C; query embed 20q `0.262s`) | \$0 (CPU) |

*Ghi chú về chỉ số tách chunk (`split_evidence_union_top3`)*: ở Strategy A, `source_page_hit_at_3` thực tế đạt `14/15` (`93.3%`) trên `dev` và `5/5` (`100.0%`) trên `test`, nhưng **5 câu** (`q01`, `q02`, `q05`, `q06` ở dev; `q16` ở test) chỉ có đủ bằng chứng khi ghép nhiều chunk trên cùng trang lại, nên không được tính vào single-chunk `Evidence Hit@3`. Ở B và C, số ca split-across-chunks bằng **`0`**.

| Strategy | Coherence trung bình /2 (`n`) | Metadata đủ và đúng (`n/N`) | Filter tuân thủ (`n/N` hoặc `N/A`) | Grounding `0/1/2` (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | **`0.00 / 2.00`** (`n = 10` vị trí, tổng `0/20`) | `15/15` trang/chapter/type (`100%`), `14/15` section chính xác khối (`93.3%`) | `N/A` (`0` câu bật filter; `1/9` test hit ở câu scoped rơi nhầm `lesson` p.180) | `0`: 1 (`q20`), `1`: 2 (`q16, q18`), `2`: 2 (`q17, q19`) → TB **`1.20 / 2.00`** (`6/10`) |
| B | **`1.60 / 2.00`** (`n = 10` vị trí, tổng `16/20`) | `15/15` trang/chapter/type (`100%`), `14/15` section chính xác khối (`93.3%`) | `N/A` (`0` câu bật filter; `2/9` test hit ở câu scoped trượt khỏi `ch3 review` ở `q20`) | `0`: 0, `1`: 0, `2`: 5 (`q16–q20`) → TB **`2.00 / 2.00`** (`10/10`) |
| C | **`1.60 / 2.00`** (`n = 10` vị trí, tổng `16/20`) | `15/15` trang/chapter/type (`100%`), `14/15` section chính xác khối (`93.3%`) | **`3/3` test queries (`9/9` hits, `100%`)**; **`7/7` toàn tập (`21/21` hits)**; `2` câu không filter = `N/A` | `0`: 0, `1`: 0, `2`: 5 (`q16–q20`) → TB **`2.00 / 2.00`** (`10/10`) |

- **Đường dẫn trace, nhãn thủ công và cách chọn mẫu**:
  - Top-3 traces đầy đủ từng câu hỏi: [results/traces_A.json](../../results/traces_A.json), [results/traces_B.json](../../results/traces_B.json), [results/traces_C.json](../../results/traces_C.json), tổng hợp số liệu tại [results/summary.json](../../results/summary.json).
  - Gói mẫu & nhãn đánh giá thủ công: [results/audit_samples.json](../../results/audit_samples.json) và [results/manual_audit.json](../../results/manual_audit.json).
  - **Cách chọn 10 vị trí Chunk Coherence**: Cố định trước khi chạy truy vấn trong `COHERENCE_SAMPLE_POSITIONS` ([starter/src/evaluation.py](../../starter/src/evaluation.py)) tại 10 trang đại diện đều cả 3 chương và đa dạng cấu trúc (mục tiêu chương, định nghĩa, gạch đầu dòng, bảng số liệu, công thức): `pp. 17, 18, 22, 31, 38, 78, 87, 99, 180, 185`. Trên 10 vị trí này, A đạt `0/2` ở cả 10 trang vì cắt ngang từ/câu (`"fact`, `malpractic/e`, `how frequ`, `and t/e`, `2.1 Stem-and-Leaf Grap`, `1; 1; 2;/et`), còn B/C đạt `2/2` ở 6 trang (`17, 18, 31, 99, 180, 185`) và `1/2` ở 4 trang (`p.22` tách giữa bullet `• Qualitative` và `• Quantitative`; `p.38` gộp đuôi 1.2 với đầu 1.3; `p.78` để sót tiêu đề `2.1` ở cuối `para:000`; `p.87` mất công thức `RF = f/n` sau `"then:"`).
  - **Metadata (1 trường có ích & 1 hạn chế)**: Trường có ích là cặp `chapter` + `content_type` (giúp thu hẹp không gian tìm kiếm đúng chương/loại nội dung và tăng tín hiệu precision ở top-3). **Hạn chế metadata**: gán nhãn từ PDF outline ở **mức trang (page-level)** nên quá thô tại các trang chuyển mục giữa chừng — cụ thể ở câu test `q17` (Rank 3 của A, B, C đều trả về `p.110`), đoạn text thực chất thuộc cuối mục `2.4 Box Plots` (`TRY IT 2.24 / EXAMPLE 2.25 / Figure 2.15`) nhưng bị gắn `section = "2.5 Measures of the Center of the Data"` do mục 2.5 bắt đầu ở nửa dưới trang `p.110`.

---

## Phân tích và kết luận

- **So sánh A–B và B–C; ví dụ lỗi có ID câu và nguồn**:
  - **A -> B (tác động của chunking theo cấu trúc đoạn/tiêu đề)**: Chuyển từ `fixed_size(500, 50)` sang `by_paragraph(1000)` giảm số chunk từ `641` xuống `365` (`-43.1%`), cắt thời gian embed document từ `18.543s` xuống `13.510s` (`-27.1%`), đồng thời tăng vọt `dev Evidence Hit@3` từ `5/15 (33.3%)` lên `12/15 (80.0%)` (`dev Hit@1`: `26.7% -> 53.3%`) và `test Hit@1 / EvHit@3` từ `2/5 (40.0%)` lên `5/5 (100.0%)`. Lý do trực tiếp: cửa sổ cố định 500 ký tự băm nát các định nghĩa hai vế ngay giữa câu.
    - *Ví dụ lỗi 1 (`q18`, test, `gold_page=117`, Sec. 2.6)*: Ở Strategy A, Rank 1 (`openstax-intro-stats-2e:p0117:fixed:...`, cosine `0.732`) chứa đầy đủ quy tắc skewness left/right/symmetric nhưng bị cắt cụt ngay chữ `"It is not, however, true for every data se"` — đánh mất hoàn toàn mệnh đề cuối `"The most common exceptions occur in sets of discrete data."`, làm A trượt cả `Hit@1`/`EvHit@3` và Grounding giảm xuống `1/2` (tương tự ở `q20` `p.212`, Rank 1 của A dừng đúng chữ `"Then:"` trước cả 3 tiên đề Kolmogorov nên Grounding = `0/2`). Strategy B/C giữ trọn đoạn trong 1 chunk, đạt Rank 1 và Grounding `2/2`.
  - **B -> C (tác động cô lập của metadata filter trên cùng chunk & vector)**: Vì C dùng lại y nguyên 365 chunk và vector của B, mọi thay đổi đến 100% từ tiền lọc SQL `WHERE`. Trên dev, `Evidence Hit@3` tăng từ `12/15 (80.0%)` lên `13/15 (86.7%)`, và filter compliance đạt `7/7` (`21/21` hits).
    - *Ví dụ lỗi 2 (`q03`, dev, `gold_page=27`, `filter={"chapter": "chapter_1"}`)*: Câu hỏi cần điều kiện dùng `bar graph` thay cho `pie chart` trong Chapter 1. Ở Strategy B (không filter), Rank 1 (`p.29`, `0.758`) và Rank 2 (`p.26`, `0.673`) đều nói về pie/bar chart nhưng thiếu quy tắc >100%/<100%, còn Rank 3 (`0.6655`) bị một chunk định nghĩa `bar graph` ở **Chapter 2 (`p.84`)** chiếm mất chỗ! Khi Strategy C lọc `chapter = 'chapter_1'`, chunk `p.84` bị loại bỏ, đẩy chunk đúng ở `p.27` (`score=0.6645`) vào Rank 3 và cứu `q03` thành `Evidence Hit@3 = True`. Tương tự trên `q20` (test, `ch3 + review`), B để lọt `lesson` `p.180` và `ch1` `p.18` vào Rank 2–3, còn C giữ cả 3/3 hits trong `chapter_3 + review` (`p.212`).
  - **Các câu còn trượt ở C (`q07` và `q10`, dev)** giúp soi rõ giới hạn của `by_paragraph(1000)` + dense bi-encoder:
    - *Ví dụ lỗi 3 (`q07`, dev, `gold_page=87`, Sec. 2.2)*: Trên `p.87`, `by_paragraph` gộp đuôi `Table 2.12` (`415c`) với đoạn mở đầu `2.2` (`...100 values or more.`) vào `p0087:para:000`, rồi tràn ngưỡng `max_size=1000` nên tách câu tiếp theo (`A histogram consists of contiguous (adjoining) boxes.`) sang `p0087:para:001`. Kết quả hai vế gold bị rẽ làm hai chunk, không chunk đơn lẻ nào lọt top-3 chứa đủ cả hai mệnh đề (`Evidence Hit@3 = False`).
    - *Ví dụ lỗi 4 (`q10`, dev, `gold_page=110`, `alt=[112]`, Sec. 2.5)*: Đoạn nêu nguyên lý chọn median khi có outlier ở cuối `p.110` nằm chung chunk `p0110:para:001` (`866c`) với bài tập `Figure 2.15 / TRY IT 2.25` (danh sách số liệu box-plot), khiến vector ngữ nghĩa bị loãng; tương tự `p.112` bắt đầu bằng hướng dẫn bấm máy tính TI-83/84 và ví dụ lương `$30,000 / $5,000,000`, nên top-3 trả về `p.98` (định nghĩa median), `p.117` (skewness), và `p.132` (glossary).

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng**:
  - **Chọn Strategy C (`by_paragraph max_size=1000` + SQL metadata filter)** theo đúng tiêu chí đã chốt trước trên dev: đạt `dev Evidence Hit@3` cao nhất (`13/15 = 86.7%`), `Coherence` (`1.60/2`), `Grounding` (`2.00/2`), `100% filter compliance` (`7/7` filtered queries), và đạt `5/5 (100%)` cả `Hit@1` lẫn `Evidence Hit@3` trên tập `test` held-out.
  - **Đánh đổi**: So với A, B/C tạo ít chunk hơn (`365` vs `641`), giảm chi phí index và tránh xé câu, nhưng chunk dài gấp ~1.6× (`mean 725.7` vs `453.5`) có nguy cơ trộn hai đoạn liên tiếp trên cùng một trang (như `p.110` trộn `TRY IT 2.25` vào mở đầu `2.5`), làm loãng embedding khi truy vấn đặc thù. So với B, C chịu phụ thuộc vào độ chính xác của bộ định tuyến/trích xuất filter (`chapter`, `content_type`): nếu câu hỏi người dùng gán sai hoặc quá hẹp filter, SQL `WHERE` có rủi ro loại nhầm chunk đúng (zero recall ngoài filter).
  - **Điều kiện áp dụng**: Khuyến nghị dùng Strategy C cho tài liệu học thuật/kỹ thuật có cấu trúc chương-mục rõ ràng khi có giao diện hoặc bước parse scope đáng tin cậy; chuyển về cơ chế fallback không filter (hoặc hybrid BM25 + vector) với câu hỏi tổng hợp liên chương.

- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí**:
  - *Dữ liệu*: `pypdf` bỏ sót `11` trang công thức vector/SVG (`pp. 87, 99, 111, 180–182, 188–189, 197, 202–203`) và không đọc nội dung biểu đồ hình học, nên benchmark hiện tại chưa đánh giá khả năng truy xuất bài toán nhiều ký hiệu toán hoặc đọc biểu đồ.
  - *Tập test nhỏ*: `test` chỉ có `5` câu (`N = 5`), độ phân giải mỗi câu tới `20%` (`4/5` vs `5/5`), và cả `dev`/`test` đều trích từ cùng một sách của OpenStax nên chưa kiểm chứng khả năng tổng quát hóa sang nguồn/giọng văn khác.
  - *Đo thời gian & chi phí*: Kết quả đo thời gian (`32.30s` embed, `0.40–0.53s` cho 20 câu) mang tính tham chiếu một lần chạy trên CPU cục bộ và quy mô nhỏ (exact cosine scan trên 365–641 hàng không phản ánh độ trễ ở quy mô hàng triệu chunk cần HNSW index).

- **Nếu làm lại hoặc mở rộng, cải tiến gì?**:
  1. Sửa bug regex `_ORPHAN_HEADING_RE` trong [starter/src/chunking.py](../../starter/src/chunking.py) (`^\d+\.\d+\s+[A-Z]` hiện thiếu `.*` trước `$` nên tiêu đề kiểu `2.1 Stem-and-Leaf...` có thể bị tách khỏi thân bài như ở `p.78`) và **luôn ngắt chunk trước tiêu đề mục lớn** (`\d+\.\d+`, `EXAMPLE`, `TRY IT`) để tránh gộp bài tập cũ với lý thuyết mới như ở `p.87` (`q07`) và `p.110` (`q10`).
  2. Áp dụng **page-bridging normalization** trước khi chunk để nối tiếp đoạn văn bị gãy qua ranh giới trang PDF (ví dụ cuối `p.17` sang đầu `p.18`), đồng thời nâng cấp gán metadata `section` xuống mức từng khối/chunk thay vì page-level để khắc phục nhãn mục sai ở trang chuyển tiếp như `p.110`.
  3. Dùng PDF parser giữ được công thức/layout (`PyMuPDF` / OCR Toán học) cho các trang SVG, bổ sung **hybrid search (BM25 + dense vector)** hoặc cross-encoder reranker cho các câu hỏi định nghĩa ngắn, và mở rộng tập test lên ≥20 câu đa tài liệu.

---

## Ghi nhận sử dụng AI (AI Usage Disclosure — theo `RULES.md`)

- Công cụ AI trợ lý lập trình được sử dụng để rà soát yêu cầu đề bài, hỗ trợ viết mã pipeline trong `starter/src/`, thiết kế script kiểm chứng dữ liệu và chuẩn hóa cấu trúc báo cáo.
- Toàn bộ chỉ số truy xuất (`Hit@1`, `Evidence Hit@3`, `Chunk count`, latency) là kết quả thực thi thực tế từ PostgreSQL + pgvector và model `all-MiniLM-L6-v2` được lưu nguyên trạng trong [results/](../../results/); toàn bộ nhãn chấm thủ công (`Chunk Coherence`, `Metadata Usefulness`, `Grounding Quality`, và phân tích lỗi `q03`, `q07`, `q10`, `q16`, `q18`, `q20`) đã được đối chiếu trực tiếp từ từng đoạn chunk và trace đầu ra trong [results/audit_samples.json](../../results/audit_samples.json) và [results/traces_A.json](../../results/traces_A.json) / [results/traces_B.json](../../results/traces_B.json) / [results/traces_C.json](../../results/traces_C.json).
