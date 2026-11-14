# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.

---

## Triển khai & tái lập kết quả (Reproducibility)

### Cấu trúc tệp đã hoàn thiện

- **Dữ liệu & manifest**: [data/manifest.json](data/manifest.json) (130 trang nội dung từ Chapters 1–3 của `OpenStax Introductory Statistics 2e`; bản trích đoạn 130 trang kèm theo tại `starter/data/introductory-statistics-2e_chapters-1-3_selected-130p.pdf` [pp. 1–40 = gốc 17–56, pp. 41–96 = gốc 77–132, pp. 97–130 = gốc 179–212], còn file PDF đầy đủ `847` trang `starter/data/introductory-statistics-2e_-_WEB.pdf` được ignore khỏi Git — tải theo hướng dẫn trong `manifest.json` nếu cần chạy lại `src.run` khớp đúng số trang gốc).
- **Bộ benchmark**: [benchmark/questions.json](benchmark/questions.json) (20 câu: `15 dev` + `5 test`, tách rời theo section và trang vàng; 7 câu có metadata filter gồm 4 dev + 3 test).
- **Pipeline (`starter/src/`)**:
  - [starter/src/ingestion.py](starter/src/ingestion.py): đọc PDF bằng `pypdf`, chuẩn hóa NFKC, loại running footer, tái tạo đoạn văn, gán metadata (`chapter`, `content_type`, `section`, `book_page`) và ghi log chẩn đoán (`low_text_density`, `omitted_inline_formula_glyphs`).
  - [starter/src/chunking.py](starter/src/chunking.py): `fixed_size(size=500, overlap=50)` (Strategy A) và `by_paragraph(max_size=1000)` (Strategy B/C).
  - [starter/src/embeddings.py](starter/src/embeddings.py): `MyEmbedder` dùng local CPU `sentence-transformers/all-MiniLM-L6-v2` (384 chiều, chuẩn hóa L2, không fallback mock).
  - [starter/src/store.py](starter/src/store.py): `PgVectorStore` kết nối PostgreSQL 16.16 + pgvector 0.8.7, tìm kiếm cosine chính xác (`<=>`), lọc SQL theo whitelist (`ALLOWED_FILTER_KEYS`), upsert idempotent và xóa chunk lỗi thời.
  - [starter/src/evaluation.py](starter/src/evaluation.py) & [starter/src/run.py](starter/src/run.py): tính `Hit@1`, `Evidence Hit@3` (single-chunk), tách riêng lỗi chia cắt chunk (`split_evidence_union_top3`), kiểm tra tuân thủ filter, xuất trace & gói mẫu kiểm định.
- **Kết quả & báo cáo**:
  - [artifacts/experiment_log.csv](artifacts/experiment_log.csv)
  - [results/summary.json](results/summary.json), [results/traces_A.json](results/traces_A.json), [results/traces_B.json](results/traces_B.json), [results/traces_C.json](results/traces_C.json)
  - [results/ingestion_errors.json](results/ingestion_errors.json), [results/audit_samples.json](results/audit_samples.json), [results/manual_audit.json](results/manual_audit.json)
  - [report/individual/2A202603446_NguyenThanhTung.md](report/individual/2A202603446_NguyenThanhTung.md)

### Lệnh chạy tái lập từ gốc repo

1. Khởi động PostgreSQL + pgvector và tạo cấu hình cục bộ trong `starter/`:

```powershell
cd starter
Copy-Item .env.example .env   # điền EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
docker compose -p day6_student_starter up -d --wait
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\check_setup.py
```

2. Chạy toàn bộ pipeline ingestion, embedding, kiểm tra idempotency và benchmark A/B/C:

```powershell
cd starter
.\.venv\Scripts\python.exe -m src.run
```
