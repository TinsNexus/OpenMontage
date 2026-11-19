# Artifact Awakening Formula ("Khối vuông thức tỉnh")

> **Vẫn chạy qua pipeline.** Công thức này chỉ thay phần prompt. Vẫn phải `init_project` (có `pipeline_type`) rồi ghi checkpoint từng giai đoạn bằng `lib/checkpoint.py` (chạy bằng `.venv/bin/python`): `in_progress` → `awaiting_human` → `completed` kèm artifact chuẩn. Không viết `gen_clips.py` / `compose.sh` riêng.

Reel **12–13 s**, không thoại, chỉ nhạc. Một cô gái đi giữa thành phố đổ nát, tay giữ một **đạo cụ phát sáng**
(khối vuông hồng neon). Bóng tối nuốt lấy cô → **nổ sét biến hình** → cận môi cười → khoe đạo cụ, thả tim/nháy mắt
→ tung chiêu → đạo cụ phóng to thành **cổng khổng lồ phá thành phố** → **glitch RGB cắt cụt** (mồi xem lại).

Phân tích từ `facebook.com/reel/1141808094974691` (page "Quả Nhót Này Chua", caption "Cap trong màn hình #ai",
~77K lượt xem theo tiêu đề page; `view_count` lúc tải: 34,923). File gốc + khung hình:
`projects/_refs/fb-1141808094974691/` (`ref.mp4`, `contact.jpg`, `detail.jpg`, `cube*.jpg`).

**Khác gì [beauty-power-reveal-formula.md](beauty-power-reveal-formula.md):** không có kẻ địch, không đánh nhau,
không giấu mặt 16 s. Ngắn gấp đôi (12.5 s vs 29 s), mỗi beat ~1.5–2 s, nhạc to đều không có khoảng lặng.
Móc câu là **một đạo cụ lặp lại 3 lần** (ngón tay → trên đầu → cổng cuối), không phải câu chữ.

## 1. Phân tích video gốc

| Thông số | Giá trị |
|---|---|
| Thời lượng | 12.5 s, 30 fps, 1920×1080 (16:9) |
| Thoại | Không (whisper + VAD: 0 đoạn). Nhạc + SFX, mix to đều (mean −16 dB, peak −4 dB) |
| Nguồn hình | AI video, phong cách **semi-real 3D / game CG** (da mịn, mắt to kiểu anime-real). Toàn bộ là motion clip |
| Chữ trên hình | Không có. Watermark: không |
| Bảng màu | Xám bụi thành phố đổ nát + **đỏ len** (áo) + **hồng/đỏ neon** (sét, khối vuông). Tóc trắng bạch kim là điểm sáng |

**Dòng thời gian (điểm cắt đo bằng scene-detect):**

| Thời gian | Beat | Mô tả |
|---|---|---|
| 0.0–1.5 | **Hook đạo cụ** | Cận bàn tay trong tay áo len đỏ, khối vuông hồng neon xoay lơ lửng trên đầu ngón tay; vòng điện hồng quấn cổ tay. Nền thành phố đổ nát mờ |
| 1.5–3.4 | Bước đi | Góc thấp sát mặt đường nứt: bốt đen cao gót bước qua, tia lửa nhỏ ở gót. Không thấy mặt |
| 3.4–3.6 | Chuyển cảnh | Flash bokeh đỏ (2–3 frame) |
| 3.6–5.2 | Bóng tối nuốt | Toàn cảnh: cô bước đi, khói đen + sét hồng quấn quanh người, tóc đen bay |
| 5.2–7.0 | **Biến hình** | Nổ sét đỏ toả tia kín khung → tóc chuyển trắng dựng ngược, áo len đỏ, bốt đỏ; đi tiếp giữa sét và khói |
| 7.0–7.6 | Cận nhan sắc | ECU môi đỏ, cười nhếch nhẹ, tóc trắng lướt qua (slow) |
| 7.6–9.5 | **Khoe đạo cụ** | Khối vuông trên ngón tay → bay lên lơ lửng trên đầu; trung cảnh cô nhìn camera, nháy mắt, **thả tim bằng ngón tay** |
| 9.5–9.8 | Flash | 2–3 frame burst kiểu anime (đỏ-vàng), đúng phách nhạc |
| 9.8–10.8 | Tung chiêu | Cô vung tay, tường năng lượng hồng-trắng quét ngang khung |
| 10.8–12.0 | **Cổng khổng lồ** | Thành phố tương lai: khối vuông phóng to thành cổng phát sáng, đâm sập cầu/toà nhà |
| 12.0–12.5 | Glitch out | RGB-split + vệt nhiễu ngang, cắt cụt (kéo người xem xem lại / "phần 2") |

**5 khía cạnh (theo nhóm shot):**
- **Subject:** 1 cô gái trẻ (tóc trắng bạch kim ngang vai, mắt xanh xám, son đỏ, áo len đỏ oversize, bốt) + 1 đạo cụ
  (khối vuông rỗng viền hồng neon). Mặt *không lộ* tới 5.2 s; đạo cụ xuất hiện ở 0 s, 7.6 s, 10.8 s.
- **Subject motion:** đạo cụ xoay trên ngón tay → bước đi đều → bị khói nuốt → nổ biến hình → cười, nháy mắt, thả tim
  (cử chỉ dễ thương, đối lập sức mạnh) → vung tay một lần.
- **Scene:** thành phố đổ nát xám, mây bão, bụi; cuối chuyển sang thành phố tương lai. Overlay: N/A.
  Hiệu ứng: sét hồng/đỏ, khói đen, flash bokeh, burst anime, glitch RGB.
- **Spatial framing:** CU tay → ground-level bốt → WS toàn thân → ECU môi → MS ngang ngực → WS ngang → EWS cổng.
- **Camera:** tay/bốt: dolly theo sát, DoF nông; WS: tracking ngang; ECU: slow-mo; burst/glitch: hiệu ứng dựng,
  không phải camera. Không handheld rung.

**Vì sao hiệu quả:**
1. **Hook 0 s bằng vật lạ:** khối vuông xoay trên ngón tay đẹp + khó hiểu → dừng lướt. Đạo cụ quay lại 2 lần nên có "vòng" câu chuyện trong 12 s.
2. **Giấu mặt 5 s rồi biến hình bằng nổ sét** → nhan sắc lộ ra đúng lúc màn hình bùng đỏ.
3. **Tương phản dễ thương / huỷ diệt:** thả tim + nháy mắt ngay trước khi phá cả thành phố.
4. **Cực ngắn + glitch cắt cụt** → watch-time > 100 %, nhiều lượt xem lại.
5. Bảng màu 3 tông rất chặt (xám / đỏ / trắng) → nhìn thumbnail là nhận ra.

**Âm thanh:** nhạc điện tử/phonk to đều cả bài. Chỗ động duy nhất: hơi chùng ở ~9.0 s (−19 dB) rồi bật lên −14 dB ở 10 s
→ đặt flash burst + tung chiêu ngay chỗ bật này. Không có khoảng lặng dài kiểu beauty-power.

## 2. Công thức sản xuất

### Khung hình
**9:16 (720×1280)** theo luật đăng reel FB của mình — **không** copy 16:9 của bản gốc. Mọi prompt ghi rõ
`vertical 9:16`. Bố cục dọc: đạo cụ + mặt đặt ở 1/3 trên, chân/bốt ở 1/3 dưới.

### Cấu trúc 7 beat (~12 s)

| # | Thời lượng | Beat | Ghi chú |
|---|---|---|---|
| B1 | 0–1.5 s | Hook đạo cụ trên ngón tay | Cận tay, DoF nông, nền đổ nát mờ |
| B2 | 1.5–3.5 s | Bước đi góc thấp | Chỉ thấy giày + mặt đường, tia lửa ở gót |
| B3 | 3.5–5 s | Bóng tối nuốt người | Toàn thân, khói đen + năng lượng `<POWER_COLOR>` |
| B4 | 5–7 s | **Nổ biến hình** | Burst toả tia kín khung → lộ ngoại hình mới |
| B5 | 7–7.5 s | ECU môi / mắt cười | Slow-mo |
| B6 | 7.5–9.5 s | Đạo cụ lên đầu, nháy mắt, thả tim | MS nhìn thẳng camera |
| B7 | 9.5–12 s | Flash → tung chiêu → đạo cụ hoá cổng khổng lồ | Kết glitch RGB 0.3–0.5 s (làm ở bước dựng) |

### Slot

```
<HEROINE>        tóc + màu, màu mắt, trang phục (KÍN: len oversize, áo khoác, váy dài/quần), giày
<ARTIFACT>       đạo cụ hình học phát sáng: khối vuông / nhẫn / quả cầu / lá bài / bông hoa pha lê…
<POWER_COLOR>    màu năng lượng = màu đạo cụ (hồng neon, xanh băng, vàng kim, tím…)
<CITY_A>         bối cảnh đầu (đổ nát, mưa đêm, sa mạc…)
<CITY_B>         bối cảnh cuối nơi cổng xuất hiện (thành phố tương lai, biển, bầu trời…)
<CUTE_GESTURE>   thả tim ngón tay / nháy mắt / chu môi / vẫy tay
```
Dùng thư viện `characters/` nếu nhân vật đã có (ảnh chính diện + toàn thân). Nhân vật mới: tạo 1 ảnh ref bằng `piapi_image` trước.

### Đường tạo A — 1 clip Seedance 2 fast, multi-shot (rẻ nhất, giữ mặt tốt)
`seedance_piapi`, `reference_to_video`, `characters: ["<id>"]`, duration 12 s, 9:16, 720p, tắt audio (nhạc làm ở bước dựng).

```
Vertical 9:16 cinematic AI short, semi-realistic 3D game-CG look, soft skin, film grain. Muted grey ruined city,
the only saturated colours are her outfit and <POWER_COLOR> energy. No text on screen. Multi-shot:
[0-1.5s] Close-up of @image1's hand in a <SLEEVE> sleeve, a glowing hollow <ARTIFACT> rimmed in <POWER_COLOR> neon
spins slowly, hovering above her fingertip; a thin ring of <POWER_COLOR> electricity crackles around her wrist.
Shallow depth of field, blurred <CITY_A> behind.
[1.5-3.5s] Ground-level shot on cracked asphalt with rubble: her <SHOES> step past the camera, small sparks at the
heel. Her face is not visible. Camera tracks low beside her.
[3.5-5s] Wide shot: she walks through <CITY_A> as black smoke and <POWER_COLOR> lightning swirl up around her body,
hair whipping.
[5-7s] A burst of <POWER_COLOR> lightning radiates across the whole frame; when it clears she is transformed:
<HEROINE TRANSFORMED LOOK>, hair flaring upward, lightning arcs around her as she keeps walking.
[7-7.5s] Slow-motion extreme close-up of her red lips forming a small confident smile, white hair strands drifting.
[7.5-9.5s] Medium shot facing camera: the <ARTIFACT> lifts off her finger and floats spinning above her head; she
looks into the lens, winks and makes a <CUTE_GESTURE>.
[9.5-12s] She flicks her hand; a wall of <POWER_COLOR>-white energy sweeps across frame. Cut to <CITY_B>: a giant
version of the glowing <ARTIFACT> rises like a portal and smashes through a bridge and towers, debris and light.
All characters are adults. Modest outfit, no cleavage focus, no body pan.
```

### Đường tạo B — Kling i2v 3 clip × 5 s (mặc định cũ, khi không cần multi-shot)
Clip 1 = B1–B3, clip 2 = B4–B6, clip 3 = B7. Mỗi clip 1 ảnh keyframe (JPG ~1080 px) + prompt tương ứng ở trên
(bỏ mốc thời gian, giữ dòng style chung). Cắt bớt còn tổng ~12 s ở bước dựng.

### Dựng (FFmpeg / Remotion)
1. Cắt mỗi beat đúng thời lượng bảng trên; giữ nhịp 1.5–2 s/beat, không kéo dài.
2. Flash bokeh 2–3 frame giữa B2→B3; burst kiểu anime 3 frame (đỏ-vàng hoặc tông `<POWER_COLOR>`) ở đầu B7, **khớp phách bật lại của nhạc**.
3. Speed ramp: B5 chạy 0.5× nếu model chưa slow-mo.
4. Kết (0.75 s cuối, 18 frame @24fps) theo đúng chuỗi của bản gốc: frame đen → cháy sáng → nhoè ngang 2 frame →
   lặp lại 2 frame cũ (stutter) → chớp trắng → RGB-split + xé dải ngang tăng dần → 3 frame sọc màu ngang → cắt.
   Không fade. Script dựng sẵn: [assets/artifact_awakening_glitch_tail.py](assets/artifact_awakening_glitch_tail.py)
   (`python -I <script> <clip.mp4> 11.25 tail.mp4`, rồi concat với đoạn 0–11.25 s). SFX: glitch-2 0.75 s + glitch-1 ở 11.7 s.
5. Nhạc: phonk / EDM to đều, chọn đoạn có một nhịp "hụt hơi" ~9 s rồi bật lại. Reel ≤90 s nên có thể thêm nhạc thư viện FB ngay trong composer khi đăng. SFX: điện xẹt (B1), bước gót (B2), nổ sét (B4), whoosh (B6→B7), sập toà nhà (B7), glitch (cuối).
6. Xuất `.srt` (để trống / 1 dòng tiêu đề) theo luật caption FB.

### 3 biến thể concept (không copy nguyên bản)
| Concept | `<ARTIFACT>` / `<POWER_COLOR>` | `<CITY_A>` → `<CITY_B>` | Ghi chú |
|---|---|---|---|
| **Băng giá** | quả cầu pha lê / xanh băng | thị trấn tuyết đêm → biển băng, cổng băng trồi lên | Áo khoác lông trắng, tóc đen → xanh bạc |
| **Hoàng kim** | lá bài vàng / vàng kim | chợ cổ phố đêm mưa → bầu trời, lá bài khổng lồ mở cổng | Áo dài cách tân kín cổ, hợp khán giả VN |
| **Hoa anh đào** | bông hoa pha lê / hồng phấn | ga tàu bỏ hoang → thành phố tương lai, hoa nở thành cổng | Nhẹ nhàng hơn, cute gesture: vẫy tay |

### Chi phí ước tính (tham khảo, phải đưa bảng so sánh model và chờ chọn trước khi tạo)
- A: Seedance 2 fast 12 s ≈ **$1.3** (theo giá 10 s ≈ $1.06) + 1 ảnh ref.
- B: Kling 3.0 std 720p 3 × 5 s ≈ **$1.5** + 3 ảnh keyframe.

## 3. Lưu ý
- **Chính sách Meta:** theo [meta-safety-rules.md](meta-safety-rules.md). Không có người bị hại → rủi ro bạo lực thấp; toà nhà sập
  phải **trống người**. Nhan sắc chỉ ở mặt/môi/tóc; không lia dọc cơ thể, không váy ngắn cận chân (bản gốc có váy ngắn — bỏ).
  Bật nhãn AI.
- Không tải lại / dùng lại cảnh gốc. Giữ cấu trúc, nhịp, bảng màu 3 tông và móc đạo cụ; nhân vật, đạo cụ, bối cảnh là của mình.
- Đạo cụ phải **cùng hình dáng ở cả 3 lần xuất hiện** — ghi mô tả đạo cụ y hệt nhau trong mọi prompt/shot.
- Seedance 2.5 hay bị chặn → dùng `seedance-2-less-restriction` nếu bị moderation.
