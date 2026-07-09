# orbit-decks

Hosted deck catalog for the Orbit app. The app fetches these files from
`raw.githubusercontent.com/vuciv/orbit-decks/main/`, so pushing to `main`
publishes: changes reach users within about 5 minutes (raw CDN cache) the
next time their app checks (on launch and on the Decks tab, throttled to
once per 15 minutes).

## Layout

- `catalog.json` lists every deck: key, version, name, description,
  category, cardCount, and the path to its deck file.
- `decks/<key>.json` holds the full deck: metadata plus a `notes` array.

## Editing rules

- Every note has a stable `key` (unique within its deck). The app matches
  installed notes by this key, so:
  - Editing a note's fields keeps users' review progress on it.
  - Removing a note deletes it (and its progress) from users' devices.
  - Never reuse a key for different content; add a new key instead.
- To publish a content change, bump `version` (a positive integer) in BOTH
  the deck file and its `catalog.json` entry. The app only re-syncs an
  installed deck when the version is higher than what it has.
- Adding a deck: create `decks/<key>.json`, add its entry to
  `catalog.json` with `version: 1`. Deck keys are lowercase
  letters/digits/hyphens.
- Do not change `schemaVersion`; apps in the field only accept `1`.

## Note models

`model` is one of `basic`, `basic_reversed`, `typed`, `cloze`, `sequence`,
`occlusion`. Required fields per model:

- basic / basic_reversed: `front`, `back` (optional `extra`, `frontImage` URL)
- typed: `front`, `answer` (optional `extra`)
- cloze: `text` containing `{{c1::...}}` markers (optional `extra`)
- sequence: `title`, `items` (string array), `contextWindow` (number)
- occlusion: `imageUri` (hosted URL), `imageWidth`, `imageHeight`, `mode`
  (`hideAll` or `hideOne`), `masks` (array of `{id, x, y, w, h}`)

Card text supports markdown-lite: **bold**, *italic*, `code`. Images must
be hosted URLs (the app prefetches them for offline study).

## Validation

CI runs `node scripts/validate.mjs` on every push and PR; run it locally
before pushing. It checks JSON shape, note keys, version consistency
between catalog and deck files, and card counts.

## Bootstrapping from the app repo

The initial content was exported from the app's bundled starter decks with
`npx tsx scripts/export-catalog.ts ../orbit-decks` (script lives in the
orbit repo). The bundled copy in the app is the offline/first-run fallback
and does not need to stay in lockstep with this repo.
