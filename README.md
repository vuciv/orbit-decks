# orbit-decks

Hosted deck catalog for the Orbit app (wire schema v2, sharded). The app
fetches these files from `raw.githubusercontent.com/vuciv/orbit-decks/main/`,
so pushing to `main` publishes: changes reach users within about 5 minutes
(raw CDN cache) the next time their app checks (on launch and on the
Decks/Library screens, throttled to once per 15 minutes).

## Layout

Source of truth (edit these):

- `decks/<key>.json` — one file per deck: metadata (`key`, `version`,
  `name`, `description`, `category`, `topics`, `coverImage`, `ttsLang`)
  plus the `notes` array.
- `collections.json` — curated shelves shown at the top of the app's
  Library screen: `{key, title, description, deckKeys}`. Order is display
  order.

Generated (never edit by hand; run `node scripts/build.mjs`):

- `catalog.json` — root index: category refs (with a content-hash `rev`
  per shard), collections, and the per-deck sync index.
- `categories/<key>.json` — browse summaries for one category. Category
  keys are slugs of the deck files' `category` display name.

## Editing rules

- Every note has a stable `key` (unique within its deck). The app matches
  installed notes by this key, so:
  - Editing a note's fields keeps users' review progress on it.
  - Removing a note deletes it (and its progress) from users' devices.
  - Never reuse a key for different content; add a new key instead.
- ANY change to a deck file must bump its `version` (positive integer).
  The version is what makes installed copies re-sync, and the rebuild is
  what refreshes the shard's `rev` so browsers refetch it.
- Adding a deck: create `decks/<key>.json` with `version: 1`, then run
  `node scripts/build.mjs`. Deck keys are lowercase letters/digits/hyphens.
- New categories order themselves via `CATEGORY_ORDER` in scripts/build.mjs.
- Do not change `schemaVersion`; apps in the field only accept `2`.

## Note models

`model` is one of `basic`, `basic_reversed`, `typed`, `cloze`, `sequence`,
`occlusion`, `vocab`. Required fields per model:

- basic / basic_reversed: `front`, `back` (optional `extra`, `frontImage` URL)
- typed: `front`, `answer` (optional `extra`)
- cloze: `text` containing `{{c1::...}}` markers (optional `extra`)
- sequence: `title`, `items` (string array), `contextWindow` (number)
- occlusion: `imageUri` (hosted URL), `imageWidth`, `imageHeight`, `mode`
  (`hideAll` or `hideOne`), `masks` (array of `{id, x, y, w, h}`)
- vocab: `term` (target-language script), `reading` (pinyin/romanization),
  `meaning` (optional `extra`, `recognitionOnly` boolean). Generates a
  recognition card (term -> meaning, reading behind a tap-to-reveal hint)
  plus a production card (meaning -> term) unless `recognitionOnly` is true.
  Use for any language whose script the learner cannot yet read.

Card text supports markdown-lite: **bold**, *italic*, `code`. Images must
be https URLs (the app prefetches them for offline study); prefer public
domain or CC-licensed sources that allow hotlinking (Wikimedia Commons via
`Special:FilePath`, flagcdn, PokeAPI sprites, NASA).

## Content quality bar

- Facts must be verifiably correct; no placeholders.
- Authored note order is the order learners meet new cards: put the most
  recognizable or most fundamental items first when there is no canonical
  order (dex number, atomic number) to follow.
- Use `extra` to add real value: disambiguation of confusables, mnemonics,
  one-line context.
- Verify every image URL responds before committing (curl each one; do not
  sample).
- No emojis anywhere.

## Validation

CI runs `node scripts/build.mjs --check` on every push and PR: it
validates every file and fails if `catalog.json`/`categories/` are out of
date. Run `node scripts/build.mjs` locally after any deck edit. To check a
single deck while authoring (safe concurrently):
`node scripts/build.mjs --deck decks/<key>.json`.

## Relationship to the app repo

The app bundles Flags of the World in `src/db/starter-decks.ts` as its
offline/first-run fallback; that deck exists both there and here
(`npx tsx scripts/export-catalog.ts` in the orbit repo regenerates its
deck payload). Every other deck lives only in this repo. The bundled
copy does not need to stay in lockstep.
