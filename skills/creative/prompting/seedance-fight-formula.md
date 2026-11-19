# Seedance Fight Formula — "Protect the Partner" Hypervelocity Combat

> **Still runs through the pipeline.** This formula only replaces the prompts. Call `init_project` (with `pipeline_type`) and write a checkpoint per stage via `lib/checkpoint.py` (run with `.venv/bin/python`): `in_progress` → `awaiting_human` → `completed` with the canonical artifact. No ad-hoc `gen_clips.py` / `compose.sh`. Without checkpoints the Backlot stage rail stays grey.

Reusable prompt recipe for short photoreal martial-arts videos: a library character
protects a noncombatant partner from a gang, nonstop combinations, two micro slow-mos,
gentle reunion. Proven on `projects/mia-arcade-fight` (Mia × Kenta, retro arcade, 20s).

For a solo hero vs a gang with no partner, no dialogue and one 10 s clip, use
`solo-street-fight-formula.md` instead.

Read `seedance-prompting.md` and `.agents/skills/seedance-2-0/SKILL.md` first; this file
only adds the fight-specific formula and what we learned running it on PiAPI.

> **Meta policy safety:** read [meta-safety-rules.md](meta-safety-rules.md) before writing prompts and before posting.
> Every clip ends with that file's `SAFETY:` line (already in the templates below). The insult line must not be a slur
> or a threat to kill, and captions frame the hero as protecting the partner, never gloating.

This recipe is packaged as the style playbook `styles/hypervelocity-combat.yaml` (offered
by the `cinematic` pipeline). Select that playbook at proposal; it carries the look, motion,
audio and quality rules, and points back here for the clip-by-clip prompt template.

## Production settings (PiAPI)

| Setting | Value | Why |
|---|---|---|
| Tool | `seedance_piapi`, `operation: "reference_to_video"` | Character library refs as `@imageN` |
| Model | `model_variant: "standard"`, `less_restriction: true` | Seedance 2.5 gets moderation-blocked on photoreal fights |
| Length | 4–15 s per clip → **20 s = 2 clips × 10 s** | less-restriction max is 15 s |
| Resolution | `720p`, `16:9`, `generate_audio: true` | ~$0.22/s → ~$2.20 per 10 s clip |
| Refs | `characters: ["<hero>", "<partner>"]`, `character_refs: "set"` | Hero = @image1–3 (full body, face, back), partner = @image4 |
| Clip 2 extra ref | last frame of clip 1 → `@image5` | Keeps location, positions, enemy states |

Prompt budget is 4000 characters and the tool prepends the library `[identity_lock]`
block (~1500 chars for two characters), so keep each clip body under ~2400 characters.

## Clip template

Fill the `<...>` slots. Clip 1 covers 00–10 s, clip 2 covers 10–20 s.

```
Montage, multi-shot <Japanese|Korean|Hong Kong> live-action action film, photorealistic, 35mm film grain, motion blur on fast actions, reactive handheld camera 0.1-0.3s late with overshoot and whip-pans, no 3D, no cartoon, no VFX aesthetic, real skin and fabric texture.
LOCATION: <time of day> <place>, <2-3 colour lighting>. LEFT <set piece>, CENTER open aisle, RIGHT <set piece>, REAR <set piece>. Three civilians back away.
CAST: ONE <Hero>, ONE <Partner> (noncombatant), FIVE adult male gangsters: #1 leader <hair>, <top>; #2 <hair>, <top>; #3 <hair>, <top>; #4 <build>, <top>; #5 <build>, <top>. <Hero> fights barehanded: <3-5 styles>. No clones, no outfit changes.
0-2s (<lens> <angle>): <inciting beat: partner wins/holds <PROP>>. <Partner> says: "<line ≤6 words>" <Hero> smiles. #1 snatches the <PROP> and shoves <Partner>. Snap-pan.
2-4s (<lens> <angle>): <Hero> catches <Partner>. #1 sneers: "<insult>" <Hero>, cold: "<warning>" #1 punches; <Hero> <defence>, <combo>. #1 staggers, drops <PROP> on the floor. <Partner> hides behind the LEFT <set piece>.
4-6s: #2 and #3 attack together. <combo> → #2 down. #3 swings → <counter>, #3 staggers.
6-8s: #4 charges. <combo> → <SIGNATURE MOVE 1>. RAMPS TO SLOW MOTION 0.25s on impact, camera jolt, SNAPS BACK TO REAL TIME. #4 falls.
8-10s: #5 rushes at <Partner>. <Hero> bursts across, <redirect>, <combo> → #5 down, <Partner> safe.
PHYSICS: foot plant, compression, explosive push-off, real contact, recoil, replant. Superhuman speed, real weight. No teleporting, no floating, no afterimages.
STATE: #2 down from 5s, #4 down from 8s, #5 down from 10s, they stay down. <Partner> stays LEFT. <PROP> stays on the floor.
AUDIO: natural <language> dialogue, impacts, footsteps, <ambient>. No music.
SAFETY: stylized action-film choreography. No blood, no wounds, no gore. Blades and weapons never touch skin; they miss, get blocked or knocked away. No strikes on anyone already down or held. No neck or throat attacks. Every defeated enemy is clearly alive and conscious: groaning, rolling, sitting up dazed or crawling away. All characters are adults.
```

Clip 2 swaps the LOCATION/CAST lines for a CONTINUATION block, then finishes the fight:

```
CONTINUATION: @image5 is the exact last frame of the previous shot. Continue directly from it: same <place>, same positions. <Describe who is STANDING and who is DOWN exactly as the frame shows.> <PROP> lies on the floor.
... remaining enemies, one beat each ...
6-8s: <SIGNATURE MOVE 2, e.g. spinning hook kick> into #1's raised forearm guard. RAMPS TO SLOW MOTION 0.2s, camera jolt, SNAPS BACK TO REAL TIME. #1 stumbles back and sits down hard, dazed. All five defeated, groaning on the floor.
8-10s (35mm medium close-up): <Hero> picks up the SAME <PROP> and gently hands it to <Partner>. <Hero> says softly: "<reassurance ≤4 words>" Gentle smile. In the background the five gangsters crawl away.
SAFETY: (same line as clip 1)
```

## Rules that made it work

1. **Give every enemy one distinctive look** (hair + top colour). Without it clip 2 cannot keep "who is down" straight.
2. **Write clip 2 only after watching clip 1's last frame.** Seedance does not obey every STATE line: in the Mia run, #2 and #4 were standing at 10 s although the prompt had them down. Rewrite clip 2's CONTINUATION and first beats to match the frame instead of regenerating clip 1.
3. **Exactly two slow-mos**, one per clip, written as `RAMPS TO SLOW MOTION` / `SNAPS BACK TO REAL TIME`.
4. **Dialogue ≤ 6 words per line** and use the hero's real name in the lines (e.g. 「ミア、取れたよ！」).
5. **One prop** (plush, phone, bouquet) that drops in clip 1 and is handed back in clip 2: it gives the ending its payoff.
6. **`#N` labels can leak onto clothing.** In the Nova street-fight run, seedance-2-fast printed 2/3/4/6 on the thugs' backs. Add "no numbers or text on clothing" to the CAST line, or refer to enemies by look ("the bearded thug").
7. **Adults only** in identities ("22-year-old adult ..."), no blood, no gore, and the `SAFETY:` line from
   [meta-safety-rules.md](meta-safety-rules.md) on every clip. Aim finishing moves at the guard, chest or shoulder,
   not the head or neck, and end on defeated enemies who are visibly moving.

## Assembly

- Grab the last frame: `ffmpeg -ss 10.0 -i clip1.mp4 -frames:v 1 clip1_last.png`.
- Concat with re-encode, trimming the duplicated first frame of clip 2: `-ss 0.08` on clip 2, `concat=n=2:v=1:a=1`, `aresample=48000`.
- Subtitles: transcribe the final audio with faster-whisper (`language="ja"`, `word_timestamps=True`), check any lone segment by re-transcribing that window (whisper invented one line in the Mia run), then burn PNG overlays (the local ffmpeg has no `subtitles`/`drawtext` filter) and keep an `.srt` next to the assets.

## Worked example

`projects/mia-arcade-fight/artifacts/prompt_clip1.txt` and `prompt_clip2.txt` (Mia, Kenta, retro arcade, pink bunny plush). Total cost: $4.40 video + $0.20 images.
