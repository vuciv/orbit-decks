/**
 * Builds and validates the hosted catalog (wire schema v2, sharded).
 *
 * Source of truth: decks/<key>.json (deck payload + category/topics/coverImage)
 * and collections.json. This script generates catalog.json (root index with
 * per-category content-hash revs) and categories/<key>.json (browse shards).
 *
 * Usage:
 *   node scripts/build.mjs            regenerate catalog.json + categories/
 *   node scripts/build.mjs --check    validate only; fail if generated files
 *                                     are out of date (CI mode)
 *   node scripts/build.mjs --deck decks/<key>.json
 *                                     validate a single deck file in isolation
 *                                     (safe to run concurrently; writes nothing)
 *
 * Mirrors the app's parser (src/db/catalog-format.ts in the orbit repo); the
 * app also validates, so this is the first line of defense, not the only one.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const errors = [];
const fail = (msg) => errors.push(msg);

const MODELS = ['basic', 'basic_reversed', 'cloze', 'typed', 'sequence', 'occlusion', 'chess', 'globe', 'vocab'];
const COUNTRY_RE = /^[A-Z]{2}$/;
const UCI_RE = /^[a-h][1-8][a-h][1-8][qrbn]?$/;
const KEY_RE = /^[a-z0-9][a-z0-9-]*$/;
// Root order is UI display order; unknown categories append alphabetically.
const CATEGORY_ORDER = [
  'Language',
  'Geography',
  'Pop Culture',
  'Space',
  'Nature',
  'Art',
  'Music',
  'Cinema',
  'Chess',
  'Mathematics',
  'Science',
  'Mathematics',
  'Anatomy',
  'History',
  'Codes & Signals',
  'Programming',
  'Professional Exams',
];

const isStr = (v) => typeof v === 'string' && v.trim().length > 0;
const optStr = (v) => v === undefined || typeof v === 'string';
const isPosInt = (v) => Number.isInteger(v) && v > 0;

// Must match the app's categoryKey() slug exactly.
function categoryKey(name) {
  const slug = name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug.length > 0 ? slug : 'other';
}

function clozeOrds(text) {
  const set = new Set();
  for (const m of text.matchAll(/\{\{c(\d+)::/g)) set.add(Number(m[1]));
  return [...set];
}

function cardCountForNote(note) {
  switch (note.model) {
    case 'basic':
    case 'typed':
      return 1;
    case 'basic_reversed':
      return 2;
    case 'cloze':
      return clozeOrds(note.fields.text).length;
    case 'sequence':
      return note.fields.items.length;
    case 'occlusion':
      return note.fields.masks.length;
    case 'chess':
    case 'globe':
      return 1;
    case 'vocab':
      return (
        (note.fields.recognitionOnly === true ? 1 : 2) +
        (note.fields.listening === true ? 1 : 0) +
        (note.fields.writing === true ? 1 : 0)
      );
    default:
      return 0;
  }
}

function validateFields(where, model, f) {
  if (typeof f !== 'object' || f === null || Array.isArray(f)) {
    return fail(`${where}: fields must be an object`);
  }
  switch (model) {
    case 'basic':
    case 'basic_reversed':
      if (!isStr(f.front) || !isStr(f.back)) fail(`${where}: needs front and back`);
      if (!optStr(f.extra) || !optStr(f.frontImage)) fail(`${where}: bad extra/frontImage`);
      if (f.frontImage !== undefined && !f.frontImage.startsWith('https://')) {
        fail(`${where}: frontImage must be an https URL`);
      }
      break;
    case 'typed':
      if (!isStr(f.front) || !isStr(f.answer)) fail(`${where}: needs front and answer`);
      if (!optStr(f.extra)) fail(`${where}: bad extra`);
      break;
    case 'cloze':
      if (!isStr(f.text)) fail(`${where}: needs text`);
      else if (clozeOrds(f.text).length === 0) fail(`${where}: text has no {{cN::...}} cloze`);
      break;
    case 'sequence':
      if (!isStr(f.title)) fail(`${where}: needs title`);
      if (!Array.isArray(f.items) || f.items.length === 0 || !f.items.every(isStr)) {
        fail(`${where}: items must be a non-empty string array`);
      }
      if (typeof f.contextWindow !== 'number' || f.contextWindow < 0) {
        fail(`${where}: contextWindow must be a number >= 0`);
      }
      break;
    case 'chess': {
      const fenBoard = typeof f.fen === 'string' ? f.fen.trim().split(/\s+/)[0] : '';
      if (!fenBoard || fenBoard.split('/').length !== 8) fail(`${where}: bad fen`);
      if (!isStr(f.answer)) fail(`${where}: needs answer (SAN)`);
      if (typeof f.answerUci !== 'string' || !UCI_RE.test(f.answerUci)) {
        fail(`${where}: answerUci must be UCI like c1f4`);
      }
      if (f.orientation !== 'white' && f.orientation !== 'black') {
        fail(`${where}: orientation must be white or black`);
      }
      if (f.lastMove !== undefined && (typeof f.lastMove !== 'string' || !UCI_RE.test(f.lastMove))) {
        fail(`${where}: bad lastMove`);
      }
      if (!optStr(f.prompt) || !optStr(f.extra)) fail(`${where}: bad prompt/extra`);
      break;
    }
    case 'globe':
      // Resolvability against the app's bundled world atlas is checked by
      // orbit's scripts/check-packs.ts; shape only here.
      if (typeof f.country !== 'string' || !COUNTRY_RE.test(f.country)) {
        fail(`${where}: country must be an uppercase ISO 3166-1 alpha-2 code`);
      }
      if (!isStr(f.answer)) fail(`${where}: needs answer`);
      if (!optStr(f.prompt) || !optStr(f.extra)) fail(`${where}: bad prompt/extra`);
      break;
    case 'vocab':
      if (!isStr(f.term) || !isStr(f.reading) || !isStr(f.meaning)) {
        fail(`${where}: needs term, reading, and meaning`);
      }
      if (!optStr(f.extra)) fail(`${where}: bad extra`);
      if (f.recognitionOnly !== undefined && typeof f.recognitionOnly !== 'boolean') {
        fail(`${where}: recognitionOnly must be a boolean`);
      }
      if (f.listening !== undefined && typeof f.listening !== 'boolean') {
        fail(`${where}: listening must be a boolean`);
      }
      if (f.writing !== undefined && typeof f.writing !== 'boolean') {
        fail(`${where}: writing must be a boolean`);
      }
      break;
    case 'occlusion':
      if (!isStr(f.imageUri) || !f.imageUri.startsWith('https://')) {
        fail(`${where}: imageUri must be an https URL`);
      }
      if (typeof f.imageWidth !== 'number' || typeof f.imageHeight !== 'number') {
        fail(`${where}: needs imageWidth/imageHeight`);
      }
      if (f.mode !== 'hideAll' && f.mode !== 'hideOne') fail(`${where}: bad mode`);
      if (!Array.isArray(f.masks) || f.masks.length === 0) {
        fail(`${where}: masks must be non-empty`);
      } else {
        for (const m of f.masks) {
          if (!m || !isStr(m.id) || [m.x, m.y, m.w, m.h].some((n) => typeof n !== 'number')) {
            fail(`${where}: bad mask entry`);
          }
        }
      }
      break;
  }
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(join(root, path), 'utf8'));
  } catch (e) {
    fail(`${path}: ${e.message}`);
    return null;
  }
}

function validateDeck(path, deck) {
  if (!deck) return null;
  const where = path;
  if (!isStr(deck.key) || !KEY_RE.test(deck.key)) fail(`${where}: bad key`);
  if (!path.endsWith(`${deck.key}.json`)) fail(`${where}: filename must be <key>.json`);
  if (!isPosInt(deck.version)) fail(`${where}: version must be a positive integer`);
  if (!isStr(deck.name)) fail(`${where}: needs name`);
  if (typeof deck.description !== 'string' || deck.description.length === 0) {
    fail(`${where}: needs description`);
  }
  if (!isStr(deck.category)) fail(`${where}: needs category`);
  if (!Array.isArray(deck.topics) || deck.topics.length === 0 || !deck.topics.every(isStr)) {
    fail(`${where}: topics must be a non-empty string array`);
  } else if (!deck.topics.every((t) => KEY_RE.test(t))) {
    fail(`${where}: topics must be lowercase slugs`);
  }
  if (deck.coverImage !== null && (!isStr(deck.coverImage) || !deck.coverImage.startsWith('https://'))) {
    fail(`${where}: coverImage must be an https URL or null`);
  }
  if (deck.ttsLang !== null && typeof deck.ttsLang !== 'string') fail(`${where}: bad ttsLang`);
  if (!Array.isArray(deck.notes) || deck.notes.length === 0) {
    fail(`${where}: notes must be a non-empty array`);
    return null;
  }
  const noteKeys = new Set();
  let cardCount = 0;
  for (const [i, note] of deck.notes.entries()) {
    const nwhere = `${where} note[${i}] (${note?.key ?? 'no key'})`;
    if (!note || !isStr(note.key)) {
      fail(`${nwhere}: needs a stable key`);
      continue;
    }
    if (noteKeys.has(note.key)) fail(`${nwhere}: duplicate note key`);
    noteKeys.add(note.key);
    if (!MODELS.includes(note.model)) {
      fail(`${nwhere}: unknown model "${note.model}"`);
      continue;
    }
    if (note.tags !== undefined && (!Array.isArray(note.tags) || !note.tags.every(isStr))) {
      fail(`${nwhere}: tags must be an array of strings`);
    }
    validateFields(nwhere, note.model, note.fields ?? null);
    if (note.fields) cardCount += cardCountForNote(note);
  }
  return cardCount;
}

function finish() {
  if (errors.length > 0) {
    console.error(`FAILED: ${errors.length} problem(s)\n`);
    for (const e of errors) console.error(`  - ${e}`);
    process.exit(1);
  }
}

// --deck <path>: single-file validation, safe to run concurrently.
const deckFlag = process.argv.indexOf('--deck');
if (deckFlag !== -1) {
  const path = process.argv[deckFlag + 1];
  if (!path) {
    console.error('usage: node scripts/build.mjs --deck decks/<key>.json');
    process.exit(1);
  }
  const cardCount = validateDeck(path, readJson(path));
  finish();
  console.log(`${path} is valid (${cardCount} cards)`);
  process.exit(0);
}

const checkOnly = process.argv.includes('--check');

const deckFiles = readdirSync(join(root, 'decks'))
  .filter((f) => f.endsWith('.json'))
  .sort();
const decks = [];
const deckKeys = new Set();
for (const file of deckFiles) {
  const path = `decks/${file}`;
  const deck = readJson(path);
  const cardCount = validateDeck(path, deck);
  if (!deck || cardCount === null) continue;
  if (deckKeys.has(deck.key)) fail(`${path}: duplicate deck key across files`);
  deckKeys.add(deck.key);
  decks.push({ deck, cardCount, file: path });
}

// Collections are curation, not integrity: a shelf may reference decks that
// have not landed yet, so unknown keys are filtered from the OUTPUT with a
// warning instead of failing the build. A typo therefore shows up as a
// persistent warning, not a red build; read the warnings.
const rawCollections = readJson('collections.json') ?? [];
const collections = [];
if (!Array.isArray(rawCollections)) {
  fail('collections.json: must be an array');
} else {
  const seen = new Set();
  for (const c of rawCollections) {
    const where = `collections.json "${c?.key ?? '?'}"`;
    if (!c || !isStr(c.key) || !KEY_RE.test(c.key)) {
      fail(`${where}: bad key`);
      continue;
    }
    if (seen.has(c.key)) fail(`${where}: duplicate key`);
    seen.add(c.key);
    if (!isStr(c.title)) fail(`${where}: needs title`);
    if (typeof c.description !== 'string') fail(`${where}: needs description`);
    if (!Array.isArray(c.deckKeys) || c.deckKeys.length === 0 || !c.deckKeys.every(isStr)) {
      fail(`${where}: deckKeys must be a non-empty string array`);
      continue;
    }
    const known = c.deckKeys.filter((key) => deckKeys.has(key));
    for (const key of c.deckKeys) {
      if (!deckKeys.has(key)) {
        console.warn(`warning: ${where} references missing deck "${key}" (filtered from output)`);
      }
    }
    if (known.length === 0) {
      console.warn(`warning: ${where} has no existing decks yet (omitted from output)`);
      continue;
    }
    collections.push({ key: c.key, title: c.title, description: c.description, deckKeys: known });
  }
}

finish();

// Group into category shards. Same display name must be used consistently.
const byCategory = new Map();
for (const { deck, cardCount } of decks) {
  const key = categoryKey(deck.category);
  const entry = byCategory.get(key) ?? { name: deck.category, entries: [] };
  if (entry.name !== deck.category) {
    fail(`category "${key}": used as both "${entry.name}" and "${deck.category}"`);
  }
  entry.entries.push({ deck, cardCount });
  byCategory.set(key, entry);
}
finish();

const orderOf = (name) => {
  const i = CATEGORY_ORDER.indexOf(name);
  return i === -1 ? CATEGORY_ORDER.length : i;
};
const sortedCategories = [...byCategory.entries()].sort(([, a], [, b]) => {
  const byOrder = orderOf(a.name) - orderOf(b.name);
  return byOrder !== 0 ? byOrder : a.name.localeCompare(b.name);
});

const outputs = new Map();
const categoryRefs = [];
for (const [key, { name, entries }] of sortedCategories) {
  entries.sort((a, b) => a.deck.name.localeCompare(b.deck.name));
  const shard = {
    schemaVersion: 2,
    key,
    name,
    decks: entries.map(({ deck, cardCount }) => ({
      key: deck.key,
      name: deck.name,
      description: deck.description,
      cardCount,
      topics: deck.topics,
      coverImage: deck.coverImage,
    })),
  };
  const json = JSON.stringify(shard, null, 2) + '\n';
  outputs.set(`categories/${key}.json`, json);
  categoryRefs.push({
    key,
    name,
    deckCount: entries.length,
    rev: createHash('sha256').update(json).digest('hex').slice(0, 12),
    file: `categories/${key}.json`,
  });
}

const catalog = {
  schemaVersion: 2,
  categories: categoryRefs,
  collections,
  syncIndex: decks
    .map(({ deck, file }) => ({ key: deck.key, version: deck.version, file }))
    .sort((a, b) => a.key.localeCompare(b.key)),
};
outputs.set('catalog.json', JSON.stringify(catalog, null, 2) + '\n');

if (checkOnly) {
  const staleShards = existsSync(join(root, 'categories'))
    ? readdirSync(join(root, 'categories')).filter(
        (f) => f.endsWith('.json') && !outputs.has(`categories/${f}`)
      )
    : [];
  for (const f of staleShards) fail(`categories/${f}: stale; run node scripts/build.mjs`);
  for (const [path, json] of outputs) {
    let current = null;
    try {
      current = readFileSync(join(root, path), 'utf8');
    } catch {
      // Missing file reads as out of date below.
    }
    if (current !== json) fail(`${path}: out of date; run node scripts/build.mjs`);
  }
  finish();
  console.log(`catalog is valid and up to date (${decks.length} decks, ${categoryRefs.length} categories)`);
} else {
  rmSync(join(root, 'categories'), { recursive: true, force: true });
  mkdirSync(join(root, 'categories'), { recursive: true });
  for (const [path, json] of outputs) writeFileSync(join(root, path), json);
  console.log(`built catalog.json + ${categoryRefs.length} category shard(s) from ${decks.length} deck(s)`);
}
