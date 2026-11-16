# Wordless Heartbreak Formula (hoạt hình 3D thất tình, không lời)

Công thức reel hài **không thoại**, kể chuyện "tặng hết lòng rồi bị đá" bằng biểu cảm phóng đại.
Nguồn tham chiếu: reel của kênh 驢略略 trên Facebook (`facebook.com/watch/?v=2286612768853006`), đăng 14/11/2026,
**9,2 triệu view, 279 nghìn reaction** sau khoảng 2 ngày. Caption: "问世间情为何物，直教本驴生死相许 #沙雕动画 #失恋 #搞笑动画".
Clip dài 74 s, 27 shot, mỗi shot trung bình 2,7 s, chỉ có nhạc và SFX. Video ngang 16:9.

> Về số liệu: 9,2 triệu là con số FB hiển thị trên trang (có thể tính cả lượt phát lại). Cùng thời điểm, yt-dlp chỉ
> đọc được `view_count` khoảng 4,87 triệu. Khi so với video của mình, hãy so cùng một nguồn số liệu.

> Chỉ học **cấu trúc**. Không dựng lại con lừa đội lá sen, cáo trắng hay cặp hải ly của kênh gốc. Mỗi lần làm,
> tạo bộ nhân vật và món đồ nhận diện riêng.

## 1. Vì sao hiệu quả

1. **Không lời nên không có rào cản ngôn ngữ.** FB đẩy được sang nhiều nước. Đây là khác biệt lớn nhất so với reel có thoại.
2. **Nỗi đau ai cũng từng trải** (thất tình, bị bỏ rơi) khiến người xem tag bạn bè.
3. **Gag bằng hình phóng đại kiểu "sa điêu":** mắt lồi, há mồm khóc thấy hết răng, nước mắt phun như vòi, khóc ra cả rãnh nước.
4. **Đám bạn "giúp" mà càng tệ hơn:** chuốc bia, khóc theo, có đứa đánh đàn hát buồn như quay MV.
5. **Cú lật cuối:** vừa khóc xong đã gặp đối tượng mới là đi tán ngay. Người xem cười và dễ xem lại.
6. **Có linh vật kèm món đồ nhận diện** (lá sen trên đầu). Logo kênh chính là nhóm nhân vật, nên mỗi video là một tập.

## 2. Bộ nhân vật (điền slot)

| Slot | Vai | Yêu cầu tạo hình |
|---|---|---|
| `HERO` | Kẻ si tình | Thân tròn, mặt to, mắt to dễ lồi, có **1 món đồ nhận diện** trên đầu hoặc người |
| `CRUSH` | Đối tượng 1 | Thanh lịch, kiêu, màu sáng tương phản với HERO |
| `RIVAL` | Kẻ cướp người yêu | Cao, ngầu, dáng "soái" |
| `BUDDY1`, `BUDDY2` | Đám bạn nhậu | Nhỏ hơn HERO, đi thành cặp, biểu cảm hài |
| `BARD` | Kẻ đánh đàn | Ôm guitar, thổi kèn hoặc harmonica (có thể kiêm vai RIVAL) |
| `NEW` | Đối tượng 2 | Dễ thương, xuất hiện ở cuối clip |

Lưu nhóm này vào `characters/` để các tập giữ đúng tạo hình (xem `AGENT_GUIDE.md`, mục Characters).
Mỗi nhân vật cần một trường `identity`: đoạn mô tả ngoại hình bằng tiếng Anh (loài, màu lông, dáng, món đồ nhận diện).
Đoạn này được dán vào prompt thay cho tên slot.

## 3. Timeline 60–75 s (khoảng 25–30 shot, 2–3 s mỗi shot)

**Quy tắc 1–2 giây đầu:** shot đầu tiên luôn là **cận mặt HERO đang cầm hoặc đội món đồ nhận diện**, mặt si tình hoặc
háo hức. Không mở bằng toàn cảnh bối cảnh. Bản gốc mở bằng cận cảnh lừa ôm bó cúc. Dùng luôn khung hình này làm thumbnail.

| Beat | Thời gian | Nội dung | Gợi ý shot |
|---|---|---|---|
| WOO | 0–10 s | HERO tán CRUSH bằng 3 kiểu (hoa, che ô dưới mưa, giỏ quà), mỗi kiểu ở một bối cảnh hoặc giờ khác nhau | MS hai nhân vật, cắt nhanh, đổi ánh sáng ngày/đêm/hoàng hôn |
| DUMP | 10–18 s | CRUSH bỏ đi với RIVAL, có thể giẫm lên HERO | CU mặt HERO đứng hình, mắt lồi, hoa rơi |
| DRINK | 18–36 s | BUDDY kéo HERO đi nhậu. HERO tu bia, sặc bọt, gào khóc, lăn ra cỏ | Ba nhân vật trong một khung, phun bia, low angle khi tu |
| SONG | 36–55 s | BARD đánh đàn buồn. HERO úp mặt khóc, nước mắt chảy thành rãnh, BUDDY ôm nhau khóc theo | Xen kẽ BARD (CU đàn) với HERO (khóc to dần); có một gag "vật lý hoá" nước mắt |
| PEAK | 55–65 s | Khóc đỉnh điểm: ECU miệng há thấy răng, rồi BUDDY phản ứng hoảng | ECU, có thể shake nhẹ |
| TWIST | 65–74 s | NEW xuất hiện, HERO lập tức tỉnh và cầm hoa đi tán. BUDDY ôm nhau, mặt cạn lời | WS HERO chạy tới NEW, kết bằng CU BUDDY |
| HOOK (tuỳ chọn) | 1 shot cuối | NEW hoặc RIVAL liếc nhìn ống kính, hoặc CRUSH quay lại nhìn HERO, để gợi "còn tiếp" | CU, giữ 1–1,5 s rồi cắt đen |

## 4. Khung hình

Chọn tỉ lệ **trước khi tạo ảnh**, vì đổi sau là phải tạo lại toàn bộ ảnh và clip.

| Nền tảng chính | Tỉ lệ | Ghi chú |
|---|---|---|
| Facebook (video thường, feed) | 16:9 | Giống bản gốc. Bố cục rộng, đủ chỗ cho 3 nhân vật đứng cạnh nhau |
| TikTok, YouTube Shorts, Reels | 9:16 | Dùng nhiều cận cảnh hơn. Đặt BUDDY phía trên và phía dưới HERO thay vì hai bên |

Nếu cần cả hai, ưu tiên làm 9:16 rồi làm bản 16:9 riêng, không crop từ bản kia.

## 5. Phong cách hình

- **3D cartoon kiểu phim hoạt hình chiếu rạp:** lông mềm, mắt to bóng, tỉ lệ đầu to.
- **Bối cảnh chính** là một bãi cỏ trong rừng, nắng ấm, DoF nông. Chỉ beat WOO mới đổi bối cảnh và ánh sáng.
- Mỗi shot chỉ có **1 hành động + 1 biểu cảm phóng đại**, không nhồi.
- Logo kênh đặt ở góc trên phải suốt video.

### An toàn nội dung

Hoạt hình động vật dễ bị xếp vào nhóm "dành cho trẻ em" (đặc biệt trên YouTube), nên cảnh rượu bia có thể bị hạn chế
kiếm tiền hoặc giảm phân phối.
- **Bản an toàn (khuyên dùng cho YouTube):** thay bia bằng trà sữa, nước ngọt hoặc lẩu. Gag sặc, phun và tu ừng ực vẫn giữ nguyên.
- **Bản bia:** chỉ dùng cho FB, khi kênh đã nhắm khán giả người lớn.
- Tránh cảnh đánh đập hay doạ trẻ em. Dùng dép, chổi lông gà hoặc cái nhìn trừng mắt để gây hài.

## 6. Âm thanh

- **Không thoại.** Nhạc buồn guitar acoustic chiếm phần lớn video. **Đổi sang nhạc vui đúng khung hình NEW xuất hiện**
  (đầu beat TWIST), không đổi sớm hay muộn.
- Trong beat SONG, cắt shot khớp nhịp đàn: mỗi cú cắt rơi vào một phách mạnh.
- SFX: tim vỡ, sặc, gào khóc, nấc, nước phun, "ding" khi gặp NEW.
- Nhạc royalty-free hoặc tự tạo bằng ACE-Step. Đừng dùng bài hát có bản quyền.
- **Không bật `enable_audio` của Kling.** Âm thanh gốc có thể tự sinh tiếng nói, mỗi clip lại sinh một kiểu nên nhạc
  bị đứt khi ghép, và giá tăng 1,5–3 lần. Toàn bộ nhạc và SFX ghép lúc dựng.

## 7. Sản xuất

### Bước 1: Nhân vật
`piapi_image` tạo character sheet cho từng vai (mặt trước, nghiêng, sau), dùng chung một style prompt. Lưu vào `characters/`.

### Bước 2: Ảnh khởi đầu cho từng shot (bắt buộc)
Kling i2v chỉ nhận **1 ảnh khung đầu** (`image_path`), không nhận bộ ảnh tham chiếu nhân vật. Vì vậy mỗi shot cần một
ảnh khởi đầu riêng, đã có đúng nhân vật, bối cảnh, tư thế và tỉ lệ khung hình:
- `piapi_image` với `characters: ["<id HERO>", "<id BUDDY1>", ...]` cùng prompt mô tả đúng shot đó. Khoảng 25–30 ảnh.
- Xem lại cả bộ ảnh trước khi tạo video: HERO có giữ đúng mặt và món đồ nhận diện không, ánh sáng có đồng nhất không.
  Sửa ở bước ảnh rẻ hơn nhiều so với bước video.
- Bỏ qua bước này thì HERO sẽ đổi mặt giữa các shot, và cái "linh vật" mất tác dụng.

### Bước 3: Video (i2v)
Mặc định `kling_piapi`, 720p, mode std. So sánh giá và model với người dùng trước khi tạo.

| Phương án | Độ dài clip | Giá mỗi clip | Ước tính 27 shot | Ghi chú |
|---|---|---|---|---|
| Kling 2.6 std | 5 s (chỉ nhận 5 hoặc 10 s) | ~0,20 USD | ~5,4 USD | Rẻ nhất, tự cắt còn 2–3 s khi dựng |
| Kling 3.0 std | 3 s (nhận 3–15 s) | ~0,30 USD | ~8,1 USD | Không phải cắt, chuyển động gọn hơn |
| Kling 4.0-flash | 3 s (nhận 3–20 s) | ~0,30 USD | ~8,1 USD | Không nhận ảnh khung cuối |

Cộng thêm 30–50% cho các shot phải tạo lại. Giá lấy từ bảng giá trong `tools/video/kling_piapi.py`; kiểm tra lại
bằng `estimate_cost` trước khi chạy.

### Bước 4: Dựng
Ghép các clip, đặt cú cắt theo nhạc, thêm SFX và logo. Kiểm tra lại toàn bộ video ở chế độ tắt tiếng: tắt tiếng mà vẫn hiểu chuyện thì đạt.

### Prompt mẫu (i2v)

Thay `<HERO identity>` bằng trường `identity` trong `character.json`. Model không hiểu tên slot.
Đổi "beer cans" thành "bubble tea cups" nếu làm bản an toàn.

**PEAK: khóc đỉnh điểm**
```
3D animated feature-film style, soft fur, big glossy eyes. <HERO identity> sits on a sunny forest meadow,
mouth wide open in an exaggerated wail showing big front teeth, tears spraying sideways like a fountain.
<BUDDY1 identity> and <BUDDY2 identity> hug his arms, staring up in shock, holding beer cans.
Shallow depth of field, warm afternoon light, static camera, medium close-up. No text, no speech.
```

**DUMP: đứng hình**
```
3D animated feature-film style. Close-up of <HERO identity> frozen in place, eyes bulging wide, jaw dropped,
a bouquet of daisies slipping from his hands and falling petal by petal. In the soft-focus background,
<CRUSH identity> walks away beside <RIVAL identity>. Slow push-in on his face, warm light. No text, no speech.
```

**TWIST: lật kèo**
```
3D animated feature-film style. Wide shot on a sunny meadow: <HERO identity> suddenly wipes his tears,
fluffs his hair and dashes toward <NEW identity>, holding out a fresh bouquet with a huge grin.
Camera tracks sideways with him, bright cheerful light. No text, no speech.
```

## 8. Biến thể chủ đề (giữ khung WOO → DUMP → DRINK → SONG → PEAK → TWIST)

Nguyên tắc chung khi đổi chủ đề:
- **DRINK → SONG → PEAK gần như giữ nguyên.** Thứ thay đổi là WOO (HERO hy vọng điều gì), DUMP (nỗi đau là gì) và TWIST (cái gì làm HERO hồi sinh ngay lập tức).
- **Mọi câu thoại ngầm phải biến thành hình.** Ví dụ "bao giờ cưới?" thành họ hàng chỉ tay và giơ ảnh cưới. Nếu một gag cần lời mới hiểu thì bỏ gag đó.
- **TWIST phải ngắn và vô liêm sỉ:** HERO hồi sinh trong 1–2 shot, còn BUDDY là người cạn lời.
- Đổi bối cảnh, màu và nhạc theo chủ đề, nhưng giữ nguyên bộ nhân vật để các tập liền mạch như một series.

### 8.1 Ế Tết

Đăng từ giữa tháng 1 đến trước Tết (Tết 2027 rơi vào khoảng 6/2). Khán giả chính là Việt Nam, Trung Quốc và Đông Nam Á.

| Beat | Nội dung |
|---|---|
| WOO | HERO háo hức sắm Tết: mua cành đào, diện áo mới, soi gương chải chuốt |
| DUMP | Ở chợ hoa đâu đâu cũng là các cặp đôi chụp ảnh, nắm tay. Về nhà, mâm cỗ toàn cặp đôi, ghế bên cạnh HERO bỏ trống |
| DRINK | Hai BUDDY cũng ế kéo HERO đi nhậu, bánh chưng làm mồi, tu bia, sặc |
| SONG | BARD gảy giai điệu Tết chậm và buồn, pháo hoa nổ phía xa, HERO khóc chảy nước mắt thành rãnh |
| PEAK | Cả đàn họ hàng kéo tới chỉ trỏ, giơ ảnh cưới của người khác ra, HERO gào lên |
| TWIST | Bao lì xì rơi trúng đầu, hoặc gặp NEW cũng đứng một mình ở chợ hoa. HERO chải tóc và mang cành đào tới. BUDDY cạn lời |

Hình ảnh: hoa đào, hoa mai, câu đối đỏ, bánh chưng, pháo hoa. Màu đỏ và vàng ấm, đặt cạnh lông xám của HERO.
Nhạc: giai điệu Tết chơi bằng guitar chậm, sang TWIST thì chuyển sang nhạc Tết vui.

### 8.2 Ế Valentine (14/2)

| Beat | Nội dung |
|---|---|
| WOO | HERO chuẩn bị hoa hồng và hộp sô-cô-la hình trái tim, tập dượt tỏ tình trước gương |
| DUMP | Tới nơi thì thấy CRUSH đã nhận hoa của RIVAL. Bó hồng của HERO héo rũ ngay trong tay |
| DRINK | BUDDY mời HERO ăn hết hộp sô-cô-la cho đỡ buồn, mặt dính đầy sô-cô-la, sặc |
| SONG | Phố đầy bóng bay trái tim, BARD hát dưới đèn đường, HERO khóc |
| PEAK | Một bóng bay trái tim bay qua rồi nổ "bụp" ngay trước mặt HERO |
| TWIST | Ngày 15/2 hoa và sô-cô-la giảm giá 70%, HERO ôm cả đống đi tặng NEW |

Hình ảnh: màu hồng và đỏ, đèn đường buổi tối, bóng bay trái tim.

### 8.3 Hết tiền cuối tháng

Đăng vào khoảng ngày 25–30 hằng tháng, có thể làm thành loạt định kỳ.

| Beat | Nội dung |
|---|---|
| WOO | Đầu tháng HERO tiêu như đại gia: trà sữa, quần áo, đồ ăn, hộp giao hàng chất thành núi |
| DUMP | Cuối tháng mở ví chỉ thấy một con bướm bay ra, tủ lạnh trống trơn |
| DRINK | BUDDY cũng nghèo, cả ba chia nhau một gói mì, uống nước lọc thay bia |
| SONG | BARD đánh đàn bằng cây đàn thiếu dây, HERO khóc nhìn tờ lịch |
| PEAK | Shipper giao tới hóa đơn trả góp dài như cuộn giấy, HERO gào |
| TWIST | Điện thoại "ting" báo có lương, HERO hồi sinh và lập tức chạy đi mua sắm. BUDDY cạn lời |

Gag bằng hình: ví mở ra có con bướm bay, tờ lịch lật thật chậm, số tài khoản giảm dần. Chữ số trên màn hình điện thoại là được, không cần thoại.

### 8.4 Bị sếp mắng / trượt deadline

| Beat | Nội dung |
|---|---|
| WOO | HERO thức trắng làm việc, dâng bản báo cáo lên đầy tự hào |
| DUMP | Sếp (RIVAL đóng vai) gạch đỏ kín trang, xé đôi tờ giấy |
| DRINK | BUDDY đồng nghiệp kéo đi nhậu sau giờ làm, cả ba nằm gục trên bàn |
| SONG | Văn phòng tối om, BARD đánh đàn, HERO khóc lên bàn phím |
| PEAK | Sếp gửi thêm một chồng việc cao đến trần nhà |
| TWIST | Thông báo thưởng cuối năm hiện ra, HERO ôm sếp hôn chùn chụt. BUDDY cạn lời |

### 8.5 Bị cắm sừng

| Beat | Nội dung |
|---|---|
| WOO | HERO và CRUSH là một cặp hạnh phúc: đạp xe đôi, chia nhau cốc trà sữa |
| DUMP | Bắt gặp CRUSH đi cùng RIVAL. HERO mọc sừng thật trên đầu (biến ẩn dụ thành gag hình) |
| DRINK | BUDDY treo khăn lên sừng của HERO làm chỗ phơi, vừa nhậu vừa dỗ |
| SONG | Sừng cứ dài thêm theo mỗi lần HERO nấc |
| PEAK | Sừng to đến mức kẹt cửa, HERO gào |
| TWIST | Ăn xong một bát phở là sừng rụng, HERO đi tán NEW ngay |

### 8.6 Mùa thi / trượt điểm

Đăng vào khoảng tháng 6–7 khi có điểm thi.

| Beat | Nội dung |
|---|---|
| WOO | HERO ôn thi đến thâm quầng mắt, chồng sách cao ngất |
| DUMP | Xem điểm thấy toàn 0 tròn, hình số 0 biến thành quả trứng |
| DRINK | BUDDY rủ đi ăn lẩu xả stress |
| SONG | BARD đánh đàn dưới gốc phượng, hoa phượng rơi, HERO khóc |
| PEAK | Phụ huynh (một vai mới) cầm chiếc dép, trừng mắt nhìn từ cửa |
| TWIST | Phát hiện đó là bảng điểm của đứa khác, HERO đỗ thật và nhảy múa. BUDDY cạn lời |

### 8.7 Ăn kiêng thất bại

Hợp đăng cuối tháng 2 (sau cả Tết và Valentine) hoặc trước mùa hè.

| Beat | Nội dung |
|---|---|
| WOO | HERO hăng hái tập gym, chỉ ăn rau, dán ảnh "body mẫu" lên tủ lạnh |
| DUMP | Đứng lên cân thấy kim nhảy vọt lên, cân vỡ tan |
| DRINK | BUDDY "an ủi" bằng gà rán và trà sữa |
| SONG | HERO vừa khóc vừa ăn liên tục, BARD hát |
| PEAK | Áo căng quá, cúc áo bắn ra trúng mặt BUDDY |
| TWIST | Thấy NEW thích kiểu "tròn trịa", HERO tự tin ưỡn bụng đi tán |

### Lịch đăng gợi ý

| Thời điểm | Biến thể |
|---|---|
| Giữa tháng 1 → trước Tết | 8.1 Ế Tết |
| 10–14/2 | 8.2 Ế Valentine (ưu tiên hơn ăn kiêng khi Tết và Valentine sát nhau, như năm 2027: Tết khoảng 6/2) |
| Cuối tháng 2 | 8.7 Ăn kiêng thất bại |
| Ngày 25–30 hằng tháng | 8.3 Hết tiền cuối tháng (tránh trùng tuần đăng các bản theo mùa) |
| Tháng 6–7 | 8.6 Mùa thi |
| Cuối năm (trước thưởng Tết) | 8.4 Bị sếp mắng |
| Bất kỳ lúc nào | Bản gốc thất tình, 8.5 Bị cắm sừng |

Kiểm tra lại ngày Tết của từng năm trước khi lên lịch.

## 9. Caption

Nhại một câu thơ hoặc câu nói nổi tiếng về tình yêu, kèm hashtag hài và thất tình.
Ví dụ: "Yêu là chết ở trong lòng một ít… nhưng gặp đứa mới là sống lại liền" #thattinh #hoathinhhai

## 10. Đo kết quả

Sau mỗi lần đăng, ghi lại số liệu vào `insights/` để biết biến thể nào ăn khách mà làm tiếp:
- Biến thể, nền tảng, tỉ lệ khung hình, bản an toàn hay bản bia, ngày giờ đăng.
- View, reaction, share và comment sau 24 giờ và sau 7 ngày. Luôn lấy cùng một nguồn số liệu (xem ghi chú ở đầu file).
- Tỉ lệ xem hết và thời lượng xem trung bình, nếu nền tảng có cung cấp.
- Thời điểm người xem bỏ đi nhiều nhất. Nếu rơi vào beat DRINK hoặc SONG thì cắt ngắn beat đó ở tập sau.

Biến thể nào có share và view cao gấp đôi mức trung bình của kênh thì làm tập tiếp theo cùng chủ đề, giữ nguyên móc HOOK.
