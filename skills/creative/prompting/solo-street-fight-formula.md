# Solo Street Fight Formula — "One vs Six, Daylight Alley"

> **Vẫn chạy qua pipeline.** Công thức này chỉ thay phần prompt. Vẫn phải `init_project` (có `pipeline_type`) rồi ghi checkpoint từng giai đoạn bằng `lib/checkpoint.py` (chạy bằng `.venv/bin/python`): `in_progress` → `awaiting_human` → `completed` kèm artifact chuẩn. Không viết `gen_clips.py` / `compose.sh` riêng. Thiếu checkpoint thì thanh giai đoạn trên Backlot luôn xám.

Công thức cho clip 10 s photoreal: một nữ chính tay không hạ 6 gã to con trong hẻm ban ngày,
mỗi đòn làm vỡ một món đồ, kết bằng cận mặt thế thủ và cắt cụt. Khác
[seedance-fight-formula.md](seedance-fight-formula.md) ở chỗ **không có người cần bảo vệ,
không thoại, không prop** — chỉ thuần hành động, 1 clip là xong.

Phân tích từ reel FB "LISA: Brutal Street Fight" (Dola AI, Seedance 2.0, 10 s, 7 cut):
`projects/_refs/fb_19y9U8JWA8/` (analysis.md + contact sheet). Ví dụ chạy thật:
`projects/nova-street-fight` (NOVA, $1.06).

Đọc `seedance-prompting.md` trước; file này chỉ thêm công thức riêng.

> **An toàn chính sách Meta:** đọc [meta-safety-rules.md](meta-safety-rules.md) trước khi viết prompt và trước khi đăng.
> Template dưới đã theo các quy tắc đó: dao chỉ chém hụt rồi bị đá văng, không đánh người đã ngã, kẻ thua còn cử động.
> Caption không dùng chữ "brutal" như tên reel tham chiếu.

## Vì sao kiểu video này ăn

1. **Nhân vật có một đặc điểm đọc được ở mọi khung** — tóc dài sáng màu bay theo mọi động tác,
   đồ đen tương phản nền xám. Chọn nhân vật có "silhouette hook" tương tự.
2. **Mỗi đòn = một vật thể vỡ** (khung sắt đổ, thùng gỗ nát, bàn gãy, bụi bốc). Lực được bán
   bằng môi trường, không bằng máu.
3. **Nhỏ vs to**: nữ chính mảnh, đối thủ to con hơn hẳn.
4. Vào trận ở giây 0, kết cận mặt ở giây 9–10, **không fade**.

## Production settings (PiAPI)

| Setting | Value | Ghi chú |
|---|---|---|
| Tool | `seedance_piapi`, `operation: "reference_to_video"` | |
| Model | `model_variant: "fast"`, `less_restriction: true` | $1.06/10 s, đủ dùng. Muốn nét hơn ở cảnh rộng: `"standard"` ($2.20). 2.5 bị chặn. |
| Length | 10 s, 1 clip | Đừng viết 8 beat/15 s như ref — Seedance nén lại; 6 beat/10 s là vừa |
| Output | `720p`, `16:9`, `generate_audio: true` | |
| Refs | `characters: ["<hero>"]`, `character_refs: "set"` | @image1 full body, @image2 face, @image3 back. Ảnh hẹp hơn 0.4 phải `pad_to_aspect()` trước |

Ngân sách prompt 4000 ký tự; identity_lock 1 nhân vật ~900 ký tự → thân prompt ≤ ~3000.

## Character sheet cho nhân vật mới

Dùng `piapi_image`, `nano-banana-pro`, 2K, 16:9, `n: 2` (~$0.21). Layout: trái 3 góc toàn thân
(trước / nghiêng / sau), phải 3 cận mặt (neutral / fierce / smirk), nền xám studio. Thêm **1–2 dấu
nhận diện riêng** (nốt ruồi, băng quấn tay…) và **không dùng mặt người nổi tiếng**. Cắt sheet
thành full_body / face / back rồi `lib.characters.add_image(...)`.

## Clip template

```
Montage, multi-shot gritty live-action street-fight film, photorealistic, 16:9, harsh cold side sunlight, deep shadows, low-saturation faded grade, heavy 35mm film grain, motion blur on fast actions, aggressive handheld camera 0.1-0.3s late with overshoot, whip-pans and snap zooms, cuts alternate 12mm ultra-wide and 85mm close-up, no static framing. No 3D, no anime, no game look, real skin and fabric texture.
LOCATION: daytime <abandoned place>, dry dusty asphalt and gravel, hazy white sky. LEFT <breakable set piece 1>, CENTER open ground, RIGHT <breakable set piece 2 + table/chairs>, REAR <fence/wall>. Dry dust hangs in the air.
CAST: ONE <Hero> (@image1 full body, @image2 face, @image3 back): <silhouette hook>, <outfit 3 items>. SIX adult male thugs, all bigger than her: the <look A> leader in <top>; the <look B> thug in <top>; ... (one look each). No numbers or text on clothing. <Hero> fights barehanded: <3 styles>. No weapons except <one thug>'s knife. No clones, no outfit change.
0-2s (12mm wide, circling): surrounded. Drop low, block, slip, <strike 1>. Thug flies into LEFT <set piece 1>, it topples. RAMPS TO SLOW MOTION 0.2s on impact, SNAPS BACK TO REAL TIME.
2-4s (85mm close, tracking): <parry + 2-hit combo>. Thug crashes into RIGHT <set piece 2>, it bursts into splinters and dust.
4-5.5s (12mm low angle): two charge from both sides. <kick 1> sends one into the table, table snaps. Keep rotating, <kick 2>, the other slides across gravel.
5.5-7.5s (85mm, ground level): knife slash misses by a wide margin. Lean back, <acrobatic dodge>, kick the knife out of his hand, it clatters away far off-screen. Land, <throw> onto asphalt. RAMPS TO SLOW MOTION 0.2s on landing, dust and gravel burst, SNAPS BACK TO REAL TIME.
7.5-9s (12mm wide, whip-pan): leader rushes from behind. Slide under, jump, <leg-wrap takedown> into a dust cloud.
9-10s (85mm, snap zoom to her face): rises into a low fighting stance, hair settling, cold stare. All six on the ground among wreckage, groaning, rolling and too dazed to get up. Hard cut, no fade.
PHYSICS: foot plant, explosive push-off, real contact, recoil, enemies stumble or slide about 3 m and stay on the ground. Fast but heavy. No teleporting, no floating, no afterimages.
STATE: <who is down from when>. <Hero>'s face, hair and outfit never change.
AUDIO: tense low-frequency ambient drone, heavy synced impacts, metal clang, wood breaking, gravel scatter, deep bass hits. No dialogue, no text, no logos. No wet ground, no rain.
SAFETY: stylized action-film choreography. No blood, no wounds, no gore. Blades and weapons never touch skin; they miss, get blocked or knocked away. No strikes on anyone already down or held. No neck or throat attacks. Every defeated enemy is clearly alive and conscious: groaning, rolling, sitting up dazed or crawling away. All characters are adults.
```

Trang phục nữ chính: thêm `modest fitted combat outfit, fully covered torso` vào CAST. Không dùng áo khoét sâu hoặc crop top.

## Bài học từ lần chạy NOVA

1. **Gọi đối thủ theo ngoại hình, không đánh số.** Prompt dùng `#2…#6` → Seedance fast in số
   2/3/4/6 lên lưng áo. Template trên đã sửa ("the <look> thug" + "No numbers or text on clothing").
2. Seedance-fast giữ mặt tốt ở cận cảnh nhưng hơi mềm chi tiết ở 12mm wide — chấp nhận được cho reel.
3. Ảnh back cắt từ sheet ra 0.36 tỉ lệ → bị từ chối trước khi gửi (không tốn tiền). Pad lên ≥0.5.

## Biến thể dễ làm

- Đổi bối cảnh: bãi container, gara ngầm, chợ đêm đóng cửa — giữ "dry, dusty, daylight/harsh light".
- Đổi silhouette hook: tóc đỏ buộc cao, áo khoác trắng dài, mặt nạ… miễn tương phản với nền.
- Ghép 2 clip thành 20 s: dùng last-frame CONTINUATION như trong `seedance-fight-formula.md`.
