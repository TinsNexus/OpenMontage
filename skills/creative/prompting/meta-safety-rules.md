# Quy tắc an toàn chính sách Meta (Facebook / Instagram Reels)

Áp dụng cho **mọi formula có cảnh đánh nhau, vũ khí, nhan sắc hoặc rượu bia** trước khi đăng lên Facebook hoặc Instagram.
Nguồn (đọc ngày 2026-11-17):
[Violent and Graphic Content](https://transparency.meta.com/policies/community-standards/violent-graphic-content/)
(changelog tới 28/8/2026) và
[About recommendations on Facebook](https://www.facebook.com/help/1257205004624246).
Policy có thể đổi, nên đọc lại 2 trang này mỗi quý.

## 1. Ba mức xử lý của Meta

| Mức | Hậu quả | Nội dung của mình dễ rơi vào |
|---|---|---|
| **Gỡ bài** | Bài bị xoá, page bị tính 1 vi phạm | Chú thích hoặc bình luận hả hê trước nỗi đau, sự bẽ mặt của người bị đánh |
| **Cảnh báo + 18+** | Bị che màn hình cảnh báo, chỉ người 18+ xem | Cái chết bạo lực hoặc tình huống nguy hiểm tính mạng (kể cả hư cấu), dao hoặc kim loại đâm vào da (photoreal), đánh người đang bị khống chế, răng gãy chảy máu |
| **18+ / không đề xuất** | Không lên gợi ý cho người chưa follow, hoặc không gợi ý cho người dưới 18 | "Physical fights between two or more people, except in a sports context"; nội dung gợi cảm (đồ xuyên thấu, zoom vào cơ thể); cảnh cổ vũ rượu bia |

Đề xuất mới là kênh tăng trưởng chính (Tisorr có 98% lượt xem từ người chưa follow). Nếu page **thường xuyên** đăng
nội dung ở mức 3 thì **cả page** có thể bị ngừng đề xuất. Ngày 2026-11-17, Tisorr đã bị giới hạn
"không đề xuất cho người dưới 18 tuổi".

## 2. Lằn ranh đỏ khi viết prompt (không bao giờ đưa vào)

- Máu, vết thương hở, xương, nội tạng, chặt chi, cháy người, cắt cổ.
- Dao, kiếm, vật nhọn **chạm hoặc đâm vào da**. Vũ khí chỉ được chém hụt, bị đỡ, bị đá văng hoặc rơi xuống sàn.
- Đánh, đạp hoặc dậm người **đã nằm** hoặc **đang bị giữ chặt**.
- Siết cổ, đánh vào cổ hoặc họng, bẻ gãy khớp có tiếng "rắc" rõ.
- Ngã từ trên cao, bị xe tông, hoặc bất kỳ cú nào trông như chết người. Kẻ thua phải **rõ là còn sống**:
  rên, lăn, chống tay ngồi dậy, bò đi.
- Nạn nhân là trẻ em, người già, hoặc động vật bị đánh.
- Người nổi tiếng hoặc mặt người thật.

## 3. Dòng NO-LIST bắt buộc cuối prompt video

Dán nguyên dòng này vào cuối mọi prompt có cảnh đánh (thay cho "No blood, no gore" cũ):

```
SAFETY: stylized action-film choreography. No blood, no wounds, no gore. Blades and weapons never touch skin; they miss, get blocked or knocked away. No strikes on anyone already down or held. No neck or throat attacks. Every defeated enemy is clearly alive and conscious: groaning, rolling, sitting up dazed or crawling away. All characters are adults.
```

## 4. Nhan sắc và trang phục

- Đẹp **ở mặt, tóc, ánh mắt**, không ở cơ thể. Không cổ khoét sâu, không đồ xuyên thấu hoặc bó sát kiểu nội y,
  không váy quá ngắn, không cận ngực, mông hoặc đùi, không camera lia dọc cơ thể.
- Thêm vào prompt nhân vật: `modest fitted combat outfit, fully covered torso`.
- **Ảnh đại diện, ảnh bìa và thumbnail** của page cũng bị xét. Dùng cận mặt hoặc dáng thế thủ, không dùng ảnh khoe dáng.

## 5. Rượu bia

- Không cận nhãn hiệu, không cảnh pha chế, không cổ vũ uống nhiều.
- Với page đã bị giới hạn tuổi, ưu tiên bản không bia (trà sữa, nước ngọt).

## 6. Khi đăng bài

1. **Bật nhãn "AI info"** cho mọi video photoreal. Meta bắt buộc nhãn này cho video AI trông như thật,
   và có thể xử lý nếu không gắn.
2. **Caption theo hướng anh hùng, tự vệ, bảo vệ người khác.** Ví dụ: "She protected him", "Wrong girl to mess with".
   Không dùng: "brutal", "destroyed", "he deserved it", emoji 😂 ở cảnh người bị đánh, chữ "kill".
3. Không hashtag kiểu #brutal #streetfight #knockout. Dùng #action #martialarts #aiart #fightscene.
4. Xoá hoặc ẩn bình luận hả hê dưới bài (bình luận sadistic có thể kéo bài vào diện gỡ).
5. Mỗi tuần mở **Professional Dashboard → Account status** để xem page có bị giới hạn đề xuất không.

## 7. Checklist trước khi duyệt batch

- [ ] Không máu, không vết thương, không vũ khí chạm da (xem từng frame slow-mo)
- [ ] Không ai bị đánh khi đã nằm hoặc bị giữ
- [ ] Kẻ thua cử động, rõ là còn sống ở frame cuối
- [ ] Trang phục kín đáo, không cận cơ thể
- [ ] Caption và hashtag theo mục 6
- [ ] Đã bật nhãn AI
