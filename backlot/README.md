# Backlot — the living storyboard

A read-only local board that shows a production happening: pipeline stages
lighting up, the script as a screenplay page, the scene plan as a filmstrip
that fills in as assets generate, decisions, spend, and activity — all
derived from what the pipeline already writes to `projects/<id>/`.

```bash
python -m backlot open <project-id>   # start server if needed + open browser
python -m backlot open                # library view (all projects)
python -m backlot serve --port 4750   # run the server in the foreground
python -m backlot restart             # restart the background server after updating Backlot
```

The server does not reload code on its own. `/api/health` reports
`"stale": true` once Backlot's Python files on disk differ from what the
process loaded; every page then shows a banner, and `backlot open` restarts
the server by itself.

## How it stays live

No agent involvement. A `watchfiles` watcher on `projects/` publishes change
notifications over SSE; the browser refetches board state. State sources:

| Board element | Disk source |
|---|---|
| identity / rail order | `project.json` + `pipeline_defs/<type>.yaml` |
| stage states, gates, versions | `checkpoint_<stage>.json` + `history/` |
| script card / modal | `artifacts/script.json` |
| filmstrip cards | `scene_plan × script × asset_manifest` join |
| generating shimmer, activity | `events.jsonl` (written by `BaseTool` instrumentation) |
| cost meter | checkpoint `cost_snapshot` |
| renders | `renders/*.mp4` (+ root-level mp4 heuristic) |

Projects without checkpoints degrade gracefully to a "what the watcher
found" view — media, snapshots, renders.

**Replay**: a completed run can be scrubbed end-to-end (▶ REPLAY RUN on the
board) — reconstructed from checkpoint history and event timestamps.

Try it without a real production:

```bash
python scripts/backlot_simulate_run.py          # live demo run (~1 min)
python -m backlot open backlot-demo-run
```

Design doc: `internal/design/LIVING_STORYBOARD.md`.

## Insights (`/insights`)

Facebook Page analytics, outside `projects/`. "Lấy số liệu mới" runs the
`facebook_page_insights` tool (needs `FACEBOOK_PAGE_ACCESS_TOKEN`, plus
`FACEBOOK_PAGE_ID` with a User token) and saves a snapshot to
`insights/facebook/<page_id>/<YYYY-MM-DD_HHMMSS>/` (gitignored). The tab shows
KPIs with deltas vs the previous snapshot, followers per day, reel length vs
retention, plays per character, and reels linked to the project whose Gallery
caption matches. "Nhận định" are fixed rules (`backlot/insights.py`, no
network); "Phân tích bằng AI" is a paid PiAPI chat call (model from
`BACKLOT_INSIGHTS_MODEL`, else `BACKLOT_COPY_MODEL`) saved as `advice.json`,
and its video ideas can be added to the Backlog in one click.

## Series wiki (`/series`)

One folder per series under `series/<id>/` (gitignored; see `lib/series.py`):
`series.json` holds the logline, status, cast (character library ids) and
episodes; `pages/*.md` are wiki pages. A new series starts with four
template pages (Tổng quan, Thế giới, Nhân vật, Bối cảnh). Pages link to each
other with `[[Page]]` or `[[Page|label]]`; a link to a missing page is shown
in red and creates it on click. Each episode can link a Backlog item (one
click creates it) and a project; when the project's reel is in the latest
Insights snapshot, the episode shows its plays, retention and new follows.
Deleting a series or page moves it to `series/_trash/`.

## Image captions (`/images`)

Each image has a "Viết caption" button. The dialog sends a downscaled copy of
the image (plus its generation prompt, when there is one) to the PiAPI chat
model and returns three caption options, hashtags and alt text for Facebook,
Instagram, TikTok or Threads. If the gateway refuses image input it falls back
to the prompt and notes. Results are saved to
`projects/<id>/artifacts/social/<path>.json` with the previous versions kept
as history.

## Products (`/products`)

A library of products you promote, for example with Shopee affiliate links. Each product lives in
`products/<id>/` (gitignored, set `OPENMONTAGE_PRODUCTS_DIR` to move it) with `product.json` (name, price,
affiliate link, description, optional English "look" text for prompts) and its photos (`ref_01.jpg`, …,
with roles: front, label/logo, back, packaging, …). See `lib/products.py`.

- **AI images with the product.** The page (or the Images page "Sản phẩm" chips) calls `piapi_image` with
  `products: ["<id>"]`. The product photos go in as reference images after any characters', and a
  `[product_lock]` line tells the model to keep shape, colours, logo and label text unchanged. The image
  sidecar records `products`, and the project it is saved in is attached to the product.
- **Product in a video.** Kling image-to-video takes one first frame, so a product video is two steps:
  generate a 9:16 scene image with the product ("Khung hình video" preset), then ask the agent for an
  image-to-video clip from that file.
- **Cart link in captions.** A project lists its products in `project.json["products"]` (attach on the
  Products page). Gallery and Images caption forms preselect those products. The model is told what is
  being sold but is never asked to write a URL; the server appends the link verbatim as `cart`
  (`🛒 Mua <name> (<price>): <link>`). On Instagram and TikTok, where caption links are not clickable, it
  says the link is in the bio / first comment instead.
