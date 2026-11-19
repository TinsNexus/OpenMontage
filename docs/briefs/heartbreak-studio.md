# Brief: "Xưởng Heartbreak" — build wordless-heartbreak reels from Backlot without Claude Code

> Hand this file to a coding agent (opencode, Codex…). Implement **one milestone per session**, in order.
> After each milestone: run the tests, start Backlot, check the page in a browser, then commit.
> Write all user-facing UI text in **Vietnamese**. Code, comments and commit messages in English.

## 0. Goal

The user makes "wordless heartbreak" reels: no-dialogue 3D-cartoon comedy, made from AI video clips (Seedance or Kling via
PiAPI) plus music and SFX. Today every episode needs a Claude Code session to write prompts, run the pipeline, review clips
and compose. Build a Backlot page **`/heartbreak`** that turns one episode into a sequence of buttons the user clicks
themselves:

1. fill the character slots plus a one-line idea →
2. AI writes the clip prompts →
3. price table, the user picks a model →
4. generate the clips, approve or regenerate each one →
5. compose the final 9:16 video with cold-open text, music on hit points and `.srt` →
6. caption.

Step 2 uses **PiAPI chat** (Claude Sonnet via PiAPI, pay-per-use), not Claude Code, so it keeps working when Claude Code
hits its usage limit.

## 1. Read first (do not skip)

| File | Why |
|---|---|
| `AGENTS.md`, `AGENT_GUIDE.md` | Repo rules. Every production goes through a pipeline with checkpoints. |
| `skills/creative/prompting/wordless-heartbreak-formula.md` | **The formula.** Beats, character slots, cold-open rule, prompt wording, music plan. This is the system prompt for step 2. |
| `skills/creative/prompting/formulas.json` | Entry `wordless-heartbreak`: specs, timeline, inputs. |
| `projects/heartbreak-ep2-hettien/` | A finished episode, produced by hand. Copy its layout: `artifacts/clip*.txt` prompts, `assets/video/*.mp4` + `.meta.json`, `assets/images/cast/`, `artifacts/edit_decisions.json`, `artifacts/music_plan.md`, `caption.md`, `checkpoint_*.json` (pipeline `cinematic`). |
| `lib/checkpoint.py` | `init_project(project_id, title=…, pipeline_type="cinematic")` and `write_checkpoint(pipeline_dir, project_id, stage, status, artifacts, …)`. Stages and artifact schemas are validated. Read `get_pipeline_stages("cinematic")` and `schemas/` before writing. |
| `lib/characters.py` | Character library (`characters/<id>/character.json` with `identity` text + reference images, `primary_image`). The slot pickers use it. |
| `tools/video/seedance_piapi.py`, `tools/video/kling_piapi.py` | Video tools. Use the tool classes (`SeedancePiAPI().execute({...})`, `estimate_cost(...)`); never call PiAPI by hand. Seedance supports `operation="reference_to_video"` with `reference_image_paths` (cast refs referenced as `@image1`, `@image2`…), `duration`, `aspect_ratio`, `resolution`, `model_variant` (`fast`/`standard`/`mini`), `less_restriction`. Pricing tables: `_PRICING` (seedance), `_PER_SECOND_PRICING`/`_PER_VIDEO_PRICING` (kling). |
| `backlot/social.py` | `_chat(messages, model, api_key)` (PiAPI chat) + `parse_copy`, and `generate_social(...)` for captions. Reuse `_chat`. |
| `backlot/tutien.py`, `backlot/ui/tutien.{html,js,css}`, `tests/backlot/test_tutien.py` | **The pattern to copy.** Plan JSON on disk, background jobs in threads with logs under `.jobs/`, `_require_action` header guard, polling UI, tests with a tmp project and a mocked `_chat`. |
| `backlot/server.py` | Where routes are registered (see the `/api/tutien` block and the `/tutien` page route). Every write route calls `_require_action(request, "<name>")`. |

## 2. User rules (hard requirements)

- **Compare models before any paid generation.** Show a table (model, price per second, resolution, clip length, total
  USD for this episode) and wait for the user to pick. Default selection: **Seedance 2 fast, 720p**. Never auto-generate.
- **Budget-sensitive.** Every paid action shows its cost on the button ("Tạo 3 clip — ~0,86 USD"). Regenerating a clip
  asks for confirmation with the cost. Show a running total per episode.
- **Output is 9:16** (Facebook penalizes 16:9), with an `.srt` file next to the video.
- **Default length 25–45 s (2–4 clips).** The 70–85 s version is only an option.
- **Cold open (formula §3).** The first 1.5–2 s is the strongest or most curious moment of the episode, plus one short
  hook text (≤ 8 words, burned in at compose, never drawn by the AI) and one hit sound.
- **Music enters and cuts on beats**, not as a constant bed: happy theme → hard cut to silence on the DUMP → sad piano →
  … (see `music_plan.md` in ep2).
- **Meta/Facebook safety + AI label.** Captions say the video is AI-made.
- **Pipeline + checkpoints for every stage.** `init_project(..., pipeline_type="cinematic")`, then
  `write_checkpoint(...)` per stage (`in_progress` → `awaiting_human` → `completed`) with the canonical artifacts.
  No standalone `gen_clips.py` / `compose.sh`. Without checkpoints the Backlot board's stage bar stays grey.
- **Invent new characters every series.** Never recreate the reference channel's donkey, fox or beavers.
- Run Python with `.venv/bin/python`.

## 3. Data model

Each episode is a normal project `projects/heartbreak-<slug>/` with an extra `studio.json`:

```json
{
  "title": "Hết tiền cuối tháng",
  "idea": "Bụp tiêu hết lương rồi bị CRUSH bỏ theo RIVAL giàu",
  "length": "short",                       // short = 2–4 clips (25–45 s), long = 70–85 s
  "slots": {"HERO": "bup", "CRUSH": "dao", "RIVAL": "bang", "BUDDY1": "cut-cut", "BUDDY2": null, "BARD": null, "NEW": null},
  "model": {"tool": "seedance_piapi", "model_variant": "fast", "resolution": "720p"},
  "cold_open": {"text": "Ví còn đúng… một con bướm", "from_clip": "B", "at": 3.2},
  "clips": [
    {"id": "A", "beats": ["WOO", "DUMP"], "duration": 12, "prompt": "…", "status": "approved",
     "versions": [{"file": "assets/video/clipA_v1.mp4", "cost": 1.15, "created_at": 0}], "chosen": 0}
  ],
  "music_plan": [{"at": 0, "cue": "happy", "action": "in"}, {"at": 8.9, "cue": null, "action": "cut"}],
  "spent_usd": 2.31,
  "stage": "assets"
}
```

## 4. Milestones

### M1 — Backend module + plan writing (no paid video yet)

- `backlot/heartbreak.py`:
  - `list_episodes()`, `create_episode(title, idea, slots, length)`: makes `projects/heartbreak-<slug>/`, runs
    `init_project`, writes `studio.json` and the `proposal` checkpoint.
  - `write_prompts(slug, notes="")` calls PiAPI chat via `social._chat` with:
    - system prompt = the formula file (trimmed to its prompt-writing sections);
    - user message = the slots' `identity` text, idea, length, and the reference-image mapping (`@image1` = HERO…).
    - It returns JSON `{clips: [{id, beats, duration, prompt}], cold_open: {text, from_clip, at}, music_plan: [...], caption_hint}`.
    - Validate: 2–4 clips for `short`, each `duration` within the tool's allowed range, prompt mentions only `@imageN`
      that exist, cold-open text ≤ 8 words.
    - Save into `studio.json` + `artifacts/clip<ID>.txt` and write the `script` and `scene_plan` checkpoints.
  - `save_prompt(slug, clip_id, prompt)`: manual edits.
  - `price_table(slug)`: for each candidate (seedance fast/standard/mini at 480p/720p, kling 3.0 std/pro), compute the
    cost using the tools' `estimate_cost` for the episode's clip durations.
- Routes `/api/heartbreak…` in `server.py` (copy the `tutien` block style, `_require_action(request, "heartbreak")`;
  paid routes use `"heartbreak-paid"`).
- Tests `tests/backlot/test_heartbreak.py`: tmp `PROJECTS_DIR`, mocked `_chat`, checkpoint files written, validation errors.

**Done when:** an episode can be created and its prompts written and edited via the API; tests pass; no paid call is made
in tests.

### M2 — Page `/heartbreak`

- `backlot/ui/heartbreak.{html,js,css}`, styled like `tutien` (same nav header; add "Heartbreak" to every page's nav, right
  after "Tu Tiên").
- Left: episode list + "+ Tập mới" (title, idea, length, slot pickers with character thumbnails from `/api/series` or
  `/api/characters`).
- Right, for the selected episode, stepper **1 Ý tưởng → 2 Prompt → 3 Chọn model → 4 Clip → 5 Ghép → 6 Caption**:
  - **Prompt:** one editable card per clip (beats, duration, prompt). Buttons: "Viết bằng AI (~0,01 USD)", "Lưu".
  - **Chọn model:** the price table with a radio per row and a "Tổng" column. The default row is highlighted.

**Done when:** steps 1–3 work end to end in the browser and nothing paid is triggered by page load or refresh.

### M3 — Clip generation jobs

- `generate_clip(slug, clip_id)` runs in a background thread (job + log like `tutien`):
  - uses the chosen tool with `operation="reference_to_video"`, the slots' primary images as `reference_image_paths`,
    `aspect_ratio="9:16"`, the chosen variant and resolution;
  - saves to `assets/video/clip<ID>_v<N>.mp4` (the tool writes a `.meta.json` sidecar);
  - adds the cost to `spent_usd`.
- "Tạo tất cả clip" button shows the total cost and needs a confirm dialog. The per-clip "Tạo lại" button needs a confirm
  dialog with the cost.
- Each clip card shows all versions with a player; "Chọn bản này" sets `chosen` and `status="approved"`.
- Write the `assets` checkpoint: `awaiting_human` while clips are pending, `completed` when all are approved, with an
  `asset_manifest`.
- If a job fails with a moderation error, show the formula's advice: retry with `less_restriction` (Seedance), costs
  slightly more, needs confirm.

**Done when:** a real 1-clip test episode at 480p (cheapest) generates, shows, and can be re-picked. Ask the user before
running it.

### M4 — Compose (free, local)

- `compose(slug)` builds the final reel with **ffmpeg** (or HyperFrames like ep2: `edit_decisions.render_runtime =
  "hyperframes"`; pick ffmpeg if simpler):
  - cold open: `from_clip` at `at` for 1.8 s + hook text (Be Vietnam Pro, white with black outline, safe zone y
    288–1248) + a hit sound from `.agents/skills/hyperframes-media/assets/sfx/`;
  - then the chosen clips in order, scaled/cropped to 1080×1920;
  - music per `music_plan` (in, cut, swap) using files in `assets/audio/` or the user's uploaded tracks, ducked under clip
    SFX;
  - `.srt` containing the hook text (wordless film: only the hook and any on-screen text);
  - outputs `renders/final.mp4` + `final.srt` + a light copy (`-crf 24`).
- Write `edit_decisions.json`, then the `edit` and `compose` checkpoints (`render_report`).
- UI: "Ghép video" button, progress, and a player for the result.

**Done when:** composing the M3 test episode gives a 9:16 mp4 that plays, has the cold-open text in the first 2 s, and the
music cuts where the plan says.

### M5 — Caption + publish checkpoint

- Reuse `social.generate_social(project_dir, "renders/final.mp4", platform="facebook_reels", …)` (it already adds an AI
  note). Show it with "Sao chép" like `tutien`.
- Write the `publish` checkpoint (`publish_log`) when the user marks the reel as posted.

## 5. Do not

- Do not call any paid API (PiAPI video, PiAPI chat, ElevenLabs) in tests or on page load.
- Do not bypass the tools' classes, and do not hard-code API keys (they come from env / `.env`).
- Do not change `backlot/tutien.py` behaviour or the existing pages beyond adding the nav link.
- Do not leave a job "running" forever: on server restart, mark orphaned jobs "interrupted" (see `tutien.list_jobs`).

## 6. How to check each milestone

```bash
.venv/bin/python -m pytest tests/backlot -q
.venv/bin/python -m backlot restart          # then open http://127.0.0.1:4750/heartbreak
git add -A backlot tests docs && git commit -m "Heartbreak studio: <milestone>"
```
