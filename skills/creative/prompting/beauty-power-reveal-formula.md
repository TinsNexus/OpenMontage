# Beauty → Power Reveal Formula ("Her beauty is the warning")

> **Vẫn chạy qua pipeline.** Công thức này chỉ thay phần prompt. Vẫn phải `init_project` (có `pipeline_type`) rồi ghi checkpoint từng giai đoạn bằng `lib/checkpoint.py` (chạy bằng `.venv/bin/python`): `in_progress` → `awaiting_human` → `completed` kèm artifact chuẩn. Không viết `gen_clips.py` / `compose.sh` riêng. Thiếu checkpoint thì thanh giai đoạn trên Backlot luôn xám.

Công thức cho reel 25–30 s kiểu game-cinematic: hỗn chiến tối → kẻ địch bị tước vũ khí →
**slow-mo khoe nhan sắc** nữ chính → địch khựng lại → **bùng sức mạnh** kết thúc.
Phân tích từ reel tham chiếu `facebook.com/reel/1607920723884191` (Secro, 29 s,
"WHEN HER BEAUTY IS MORE DANGEROUS THAN HER POWER"). File gốc + contact sheet:
`projects/_refs/fb_1607920723884191/`.

## 1. Phân tích video gốc

| Thông số | Giá trị |
|---|---|
| Thời lượng | 29.0 s, 30 fps |
| Khung | 1080×1270 (~4:5). Dải chữ trên ~150 px · video 16:9 ở giữa · nền mờ (blur) phía dưới |
| Thoại | Không có. Chỉ nhạc + SFX, mix rất to (mean −15.5 dB, peak 0 dB) |
| Nguồn hình | CG game 3D kiểu Unreal (võ hiệp/fantasy), tất cả là **motion clip**, không phải ảnh tĩnh |
| Chữ | 2 dòng cố định suốt video, chữ trắng in đậm nghiêng có viền đen: `HER **BEAUTY** IS THE WARNING` (BEAUTY màu hồng tím #E040FB) / `HER POWER IS THE **CONSEQUENCE**` (màu đỏ #E0001B) |
| Watermark | Logo tròn mờ ở giữa đáy khung video |

**Dòng thời gian (điểm cắt đo bằng scene-detect):**

| Thời gian | Beat | Mô tả |
|---|---|---|
| 0.0–1.2 | Hook | Toàn cảnh nhà kho tối, tia sáng xuyên mái; một gã cầm vũ khí lửa lao vào |
| 1.2–6.2 | Hỗn chiến | Bóng áo trắng nhào lộn, nhảy vọt cầm kiếm, nhóm địch đứng trong cột sáng, cận nắm đấm/xích. Camera rung, motion blur mạnh — **không thấy rõ mặt nữ chính** |
| 6.2–16.2 | Tước vũ khí | Tiếp hỗn chiến mờ → góc thấp sát sàn: chân bốt, cây liềm cong xoay trên không rồi rơi xuống sàn |
| 16.2–20.5 | **Reveal nhan sắc** | Slow-mo: sau gáy tóc bạch kim dài + trâm cài → quay đầu → cận mặt → macro mắt xanh. Màu chuyển từ vàng-đen sang xanh lạnh |
| 20.5–21.7 | Phản ứng | Cắt về địch đang quỳ/khựng lại |
| 21.7–25.0 | Bình thản | Trung cảnh nữ chính đứng yên, ánh sáng xanh tụ quanh người |
| 25.0–25.1 | Flash | 3 frame chớp trắng-xanh (nhịp drop nhạc) |
| 25.1–29.0 | Hậu quả | Tia năng lượng xanh bắn ngang khung, tay địch bị năng lượng quấn; kết ở cảnh cô đứng giữa, tia sáng xanh lướt qua |

**5 khía cạnh (theo nhóm shot):**
- **Subject:** 1 nữ chính (tóc bạch kim thẳng dài, trâm vàng, mắt xanh, áo trắng-bạc ôm người phong cách võ hiệp) + 4–6 địch nam mặc giáp tối. Nữ chính *ẩn* ở phần đầu, *lộ ra* ở 16 s.
- **Subject motion:** đầu nhanh và hỗn loạn (nhào lộn, chém, đấm) → giữa gần như đứng yên (quay đầu, chớp mắt) → cuối ra một chiêu duy nhất.
- **Scene:** nhà kho/đấu trường gỗ, tia sáng thể tích, bụi bay. Overlay: dải chữ 2 dòng + watermark. Không có overlay nào khác.
- **Spatial framing:** WS → MS/CU lộn xộn → ECU sàn nhà → ECU mắt → MS cân giữa.
- **Camera:** handheld rung + whip-pan ở phần đánh; slow-mo + dolly-in mượt ở phần reveal; một cú hard-flash ở drop.

**Vì sao hiệu quả:**
1. **Câu chữ = toàn bộ kịch bản.** Dòng 1 (BEAUTY) khớp với đoạn reveal, dòng 2 (CONSEQUENCE) khớp với đoạn bùng sức mạnh. Người xem đọc trước, rồi chờ hình "trả lời".
2. **Giấu mặt 16 giây.** Hỗn chiến mờ nhòe làm tò mò; khoảnh khắc mặt rõ nét đầu tiên đúng lúc nhạc chùng xuống → tương phản cực mạnh.
3. **Đảo nhịp:** nhanh → chậm → nổ. Phần đẹp nhất là phần *chậm nhất*.
4. Màu chuyển ấm-tối → lạnh-sáng đánh dấu "nhân vật chính xuất hiện".

## 2. Công thức sản xuất

### Cấu trúc 6 shot (~28 s)

| # | Thời lượng | Beat | Ghi chú |
|---|---|---|---|
| S1 | 5 s | Hook + hỗn chiến | Địch xông vào; nữ chính chỉ là bóng áo trắng mờ |
| S2 | 5 s | Hỗn chiến 2 → tước vũ khí | Vũ khí địch bị đánh văng, xoay, rơi xuống sàn (góc thấp) |
| S3 | 5 s | Reveal sau gáy → quay đầu | **Slow-mo**, đổi tông sang xanh lạnh |
| S4 | 4 s | Cận mặt → macro mắt | Slow-mo, chớp mắt chậm |
| S5 | 4 s | Địch khựng / quỳ + nữ chính tụ năng lượng | Có thể ghép 2 shot 2 s |
| S6 | 5 s | Bùng năng lượng | Flash 3 frame ở đầu shot rồi tia năng lượng quét ngang |

Cắt dựng: cắt S1–S2 thành nhiều đoạn 0.5–1.5 s cho dồn dập; S3–S4 để nguyên dài.
Đặt **drop nhạc** đúng đầu S6.

### Nhân vật (slot)
`<HEROINE>`: <màu + kiểu tóc>, <phụ kiện tóc>, <màu mắt>, <trang phục>, <màu năng lượng>.
`<ENEMIES>`: <số lượng>, <giáp/trang phục>, <vũ khí đặc trưng sẽ bị tước>.
`<ARENA>`: <địa điểm>, <nguồn sáng>.
`<POWER>`: <băng | sét | lửa xanh | gió...> — quyết định màu của S5–S6.

Dùng thư viện `characters/` nếu nhân vật đã có; nếu không, tạo 1 ảnh keyframe cho mỗi shot
(nano-banana / `piapi_image`) rồi image-to-video từng shot.

### Prompt template (Kling i2v, mỗi shot 1 clip)

Dòng style chung (đặt đầu mọi prompt):
```
High-end 3D game cinematic, Unreal Engine 5 render quality, volumetric god rays through a dark wooden roof, floating dust, film grain, 16:9.
```

```
S1: Dark <ARENA>, shafts of light through the roof. An armored brute with a <WEAPON> charges toward camera; a blurred figure in white robes flips past in the foreground. Reactive handheld camera, whip-pan, heavy motion blur. The woman's face is never visible.
S2: Low angle at floor level, boots and planks in foreground. A <WEAPON> spins through the air in slow arc and clatters onto the empty wooden floor. A disarmed enemy scrambles backward away from it. Dust kicks up. Camera locked low, slight push-in.
S3: Slow motion. From behind: a woman with long straight <HAIR> and a gold hairpin, in modest high-collared robes, stands still in a cold blue light beam. She slowly turns her head over her shoulder. Hair strands drift. Slow dolly-in. Colour shifts from warm amber to cold blue.
S4: Slow motion extreme close-up of her face, then racks focus to her <EYE COLOUR> eye. She blinks once, calm, unimpressed. Shallow depth of field, soft rim light, hair crossing frame.
S5: Medium shot, two kneeling armored enemies freeze and look up in fear. Cut feel: then the woman stands centered and calm as <POWER COLOUR> energy gathers around her hand and robes ripple.
S6: Blinding <POWER COLOUR> flash, then a beam of <POWER> energy sweeps horizontally across frame, wrapping an enemy's armored arm and pushing him back. The woman stands motionless in the center, eyes half-closed. Camera shake on impact, then settles; the enemies stagger back, alive, shielding their eyes.
```
Mọi shot có địch: thêm dòng `SAFETY:` trong [meta-safety-rules.md](meta-safety-rules.md) vào cuối prompt.
Tia năng lượng chỉ đẩy lùi hoặc trói tay địch, không xuyên người, không đốt cháy người.

**Nhan sắc chỉ ở mặt, tóc, ánh mắt.** S3–S4 quay sau gáy và cận mặt, không lia dọc cơ thể.
Trang phục kín (cổ cao, tay dài). Không cổ khoét sâu, xẻ tà cao hoặc vải xuyên thấu, vì nội dung gợi cảm
cũng khiến page bị giới hạn đề xuất cho người dưới 18 tuổi.
Không có thoại, không cần audio từ model (`enable_audio: false`) — âm thanh làm ở bước dựng.

### Dựng (FFmpeg / Remotion)
1. Canvas **1080×1270**. Video 16:9 scale 1080 rộng, đặt ở y ≈ 150.
2. Nền: chính video đó phóng to + `gblur` mạnh + tối 40%, lấp đầy phần trên/dưới.
3. Dải chữ trên: 2 dòng, font đậm nghiêng (Montserrat ExtraBold Italic / Anton), cỡ ~44 px,
   chữ trắng viền đen 3 px. Từ khóa dòng 1 màu `#E040FB`, từ khóa dòng 2 màu `#E0001B`.
   Giữ nguyên suốt video.
4. Speed ramp: S3–S4 chạy 0.5× nếu model không tự slow-mo.
5. Flash 3 frame trắng-xanh (100 ms) ở đầu S6, khớp drop.
6. Âm thanh: nhạc phonk / epic trailer có **break yên lặng ở S3** và **drop ở S6**;
   SFX whoosh/chém ở S1–S2, tiếng kim loại rơi ở S2, tiếng ngân (shimmer) ở S3–S4,
   tiếng nổ năng lượng ở S6. Loudness ~ −10 LUFS (mix to giống gốc).

### Biến thể câu chữ (giữ cấu trúc "A là lời cảnh báo / B là hậu quả")
- HER **SILENCE** IS THE WARNING / HER **SWORD** IS THE ANSWER
- HIS **SMILE** IS THE WARNING / HIS **FIST** IS THE CONSEQUENCE
- SHE **LOOKS** FRAGILE / THEY **LEARNED** TOO LATE

### Chi phí ước tính (Kling 3.0 std, 720p, không audio)
6 clip × ~4.7 s ≈ 28 s × $0.10/s ≈ **$2.80** + 6 ảnh keyframe. Pro: ×1.5 (≈ $4.20).
Trước khi tạo, vẫn trình bày bảng so sánh model và chờ chọn.

## 3. Lưu ý
- **Chính sách Meta:** làm theo [meta-safety-rules.md](meta-safety-rules.md). Kiểu CG game fantasy ít rủi ro hơn
  photoreal, nhưng vẫn cần bật nhãn AI nếu chọn bản photoreal. Câu chữ trên video giữ giọng "cảnh báo / hậu quả",
  không dùng chữ "kill", "die", "blood".
- Video gốc là cảnh cắt từ CG game có bản quyền; **không tải lại / dùng lại cảnh gốc**.
  Công thức này chỉ giữ cấu trúc, nhịp và kiểu chữ — nhân vật, bối cảnh, năng lượng phải là của mình.
- Kling i2v một shot/lần (multi_shots hay lỗi). Ảnh ref nén JPG ~1080 px.
- Nếu Kling không giữ được mặt nhân vật giữa S3–S6, chuyển sang `seedance_piapi`
  `reference_to_video` với character refs và nói rõ lý do.
