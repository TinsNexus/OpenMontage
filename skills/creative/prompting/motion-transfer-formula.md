# Motion Transfer Formula (thay nhân vật + bối cảnh vào video động tác)

> **Vẫn chạy qua pipeline.** Công thức này chỉ thay phần prompt. Vẫn phải `init_project` (có `pipeline_type`) rồi ghi checkpoint từng giai đoạn bằng `lib/checkpoint.py` (chạy bằng `.venv/bin/python`): `in_progress` → `awaiting_human` → `completed` kèm artifact chuẩn. Không viết `gen_clips.py` / `compose.sh` riêng. Thiếu checkpoint thì thanh giai đoạn trên Backlot luôn xám.

Công thức "remix" một video có sẵn: giữ nguyên **động tác, nhịp, chuyển động máy và thứ tự cắt cảnh** của
video tham chiếu, nhưng thay người bằng **nhân vật của mình** và đặt vào **bối cảnh của mình**.
Nguồn: prompt của 0xMomo trên X (`x.com/0xmomonifty/status/2121960262177792437`), bản gốc tiếng Trung.
Đầu vào trong demo của tác giả: 1 ảnh nhân vật, 3 ảnh bối cảnh và 1 video động tác.

## 1. Ý tưởng cốt lõi

Mỗi tư liệu giữ **một vai trò riêng**, và prompt nói rõ vai trò đó để model không trộn lẫn:

| Tư liệu | Quyết định cái gì |
|---|---|
| Video động tác (`@video1`) | Cỡ cảnh, bố cục, chuyển động máy, vị trí nhân vật, thời gian động tác, thứ tự cắt |
| Ảnh nhân vật (`@image1`) | Mặt, dáng, tóc, trang phục, giày, phụ kiện (đồng nhất ở mặt trước, mặt nghiêng, mặt sau) |
| Ảnh bối cảnh (`@image2…`) | Hướng máy, cấu trúc không gian, chất liệu, ánh sáng, tông màu. **Shot N ↔ ảnh bối cảnh N** |
| Đạo cụ (ảnh riêng hoặc lấy theo video) | Hình dáng, kích thước, chất liệu, giữ nguyên suốt video |

Vì sao hiệu quả:
1. **Chuyển động "mượn" từ video thật**, nên vật lý, nhịp và cắt cảnh tự nhiên hơn hẳn text-to-video.
2. **Ảnh bối cảnh đánh số theo shot** giúp mỗi góc máy có tiền cảnh, hậu cảnh và điểm tụ riêng, mà vẫn chung một không gian.
3. **Quy tắc tiếp xúc** (tay ôm đạo cụ, hiệu ứng chỉ sinh ra ở điểm va chạm, bóng đổ, nước bắn) sửa được các lỗi AI hay gặp nhất.

## 2. Công thức sản xuất

### Chuẩn bị tư liệu
- **Video động tác:** 4–15 s (Seedance 2), mp4/mov, ≤ 10 MB. Cắt đúng đoạn cần dùng trước khi upload.
- **Ảnh nhân vật:** tốt nhất là character sheet có mặt trước, nghiêng và sau. Có thể dùng thư viện nhân vật (`character_refs`).
- **Ảnh bối cảnh:** mỗi shot của video gốc 1 ảnh, chụp đúng hướng máy của shot đó, cùng một địa điểm.
- **Ảnh "白模" (white model, khung dựng trắng) nếu có:** tác giả nhắc là quên đưa vào. Đó là ảnh/clip dựng hình trắng
  dùng để chốt bố cục; không bắt buộc.

### Gọi tool
`seedance_piapi`, `operation: "reference_to_video"` (PiAPI `omni_reference`):
- `reference_video_paths`: [video động tác] (tối đa 3)
- `reference_image_paths`: [ảnh nhân vật, bối cảnh 1, bối cảnh 2, bối cảnh 3, (đạo cụ)] (tối đa 9)
- `duration`: bằng độ dài video gốc (4–15 s), `resolution: "720p"`
- Cảnh đánh nhau hoặc người thật: dùng `less_restriction: true` (Seedance 2 less-restriction).

### Prompt template (điền phần `<...>`)

```
[EDIT GOAL]
Replace the person in @video1 with the character from @image1, and move the action into the environment
shown in the scene references. Reproduce @video1's blocking, action rhythm, prop trajectory and cut order.

[REFERENCES]
@video1 sets every shot's framing, composition, camera movement, character position and action timing.
@image1 sets the character's face, body, hair, outfit, shoes and accessories; the same look from front, side and back.
Scene references map to shots by number: shot 1 = @image2, shot 2 = @image3, shot 3 = @image4. Each sets that
shot's camera direction, spatial layout, materials, lighting and color.
The prop follows <@image5 / @video1>; its size, shape and material stay the same throughout.

[ACTION & CAMERA]
Follow the original order: <starting pose> → <key action> → <finishing pose>. Keep the original direction,
speed changes and pauses. <Camera beat to stress, e.g. "as he turns, the camera tracks left and pulls back slightly;
at the peak of the move it tightens a little">.
When the prop is held, the fingers truly wrap the grip and the prop moves with the wrist. Once released, it follows
@video1's trajectory. <Splash / dust / sparks> appear only from the actual contact point, with a matching reaction.
If the original skips the catch with a cut, keep that edit.

[SCENE INTEGRATION]
Different angles of the same place show a clear change of facing: place foreground, background and vanishing
point per each shot's scene reference. All angles share the same architecture materials, weather and grade.
The face, clothes and prop take the ambient light of the current angle. Feet cast contact shadows; on wet ground
there are reflections and splashes that change with each step. <Rain / mist / debris> pass in front of and behind
the character in correct depth order, matching the scene's materials.

[ENDING & SOUND]
End like @video1 on <final pose and framing>, holding it until <end time>. Ambient and action sounds sync to visible
contact points. No on-screen text.
```

Ghi chú: Seedance giới hạn prompt 4000 ký tự. Template trên khoảng 2000 ký tự, nên còn chỗ cho phần mô tả.

### Dựng
- Nếu dùng nhạc riêng: tắt `generate_audio` hoặc giữ lại tiếng động môi trường, rồi ghép nhạc khi dựng.
  Nhạc giữ nguyên tốc độ, đoạn cuối kết bằng âm thanh môi trường.
- Chữ hoặc phụ đề thêm khi dựng (Remotion/FFmpeg), không để model vẽ chữ.

### Chi phí ước tính (720p)
| Model | $/giây | Clip 10 s |
|---|---|---|
| Seedance 2 standard | 0.20 | ~$2.00 |
| Seedance 2 less-restriction | 0.22 | ~$2.20 |
| Seedance 2 fast | 0.096 | ~$0.96 |

## 3. Lưu ý
- **Chính sách Meta:** nếu video động tác là cảnh đánh nhau, thêm dòng `SAFETY:` trong
  [meta-safety-rules.md](meta-safety-rules.md) vào cuối `[ENDING & SOUND]`. Nếu video gốc có cảnh đánh người đã ngã,
  vũ khí chạm người hoặc máu, cắt bỏ đoạn đó **trước khi upload**, vì model sẽ chép đúng động tác.
  Nhân vật mặc đồ kín đáo, và bật nhãn AI khi đăng bản photoreal.
- **Bản quyền:** video động tác nên là clip bạn có quyền dùng, hoặc chỉ dùng để mượn chuyển động. Không đăng lại nhân vật hay cảnh quay gốc.
- Video gốc cắt nhiều shot thì cần đủ ảnh bối cảnh tương ứng. Thiếu ảnh thì model sẽ tự đoán cảnh cho các shot còn lại.
- Đừng dùng nhãn kiểu `#1`, `#2` để gọi người trong prompt, vì nhãn có thể bị in lên quần áo (xem `seedance-fight-formula.md`).
- Chưa chạy thử trong OpenMontage. Hãy chạy 1 lần với bản `fast` để kiểm tra trước khi dùng `standard`.
