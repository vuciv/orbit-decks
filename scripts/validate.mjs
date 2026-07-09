/**
 * Validates catalog.json and every deck file so a bad edit cannot ship to
 * the app. Mirrors the app's parser (src/db/catalog-format.ts in the orbit
 * repo); the app also validates, so this is the first line of defense, not
 * the only one.
 *
 * Usage: node scripts/validate.mjs
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const errors = [];
const fail = (msg) => errors.push(msg);

const MODELS = ['basic', 'basic_reversed', 'cloze', 'typed', 'sequence', 'occlusion'];
const DECK_KEY_RE = /^[a-z0-9][a-z0-9-]*$/;

const isStr = (v) => typeof v === 'string' && v.trim().length > 0;
const optStr = (v) => v === undefined || typeof v === 'string';
const isPosInt = (v) => Number.isInteger(v) && v > 0;

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
      break;
    case 'typed':
      if (!isStr(f.front) || !isStr(f.answer)) fail(`${where}: needs front and answer`);
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
    case 'occlusion':
      if (!isStr(f.imageUri) || !f.imageUri.startsWith('http')) {
        fail(`${where}: imageUri must be a hosted URL`);
      }
      if (typeof f.imageWidth !== 'number' || typeof f.imageHeight !== 'number') {
        fail(`${where}: needs imageWidth/imageHeight`);
      }
      if (f.mode !== 'hideAll' && f.mode !== 'hideOne') fail(`${where}: bad mode`);
      if (!Array.isArray(f.masks) || f.masks.length === 0) {
        fail(`${where}: masks must be non-empty`);
      } else {
        for (const m of f.masks) {
          if (
            !m || !isStr(m.id) ||
            [m.x, m.y, m.w, m.h].some((n) => typeof n !== 'number')
          ) {
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

const catalog = readJson('catalog.json');
if (catalog) {
  if (catalog.schemaVersion !== 1) fail('catalog.json: schemaVersion must be 1');
  if (!Array.isArray(catalog.decks) || catalog.decks.length === 0) {
    fail('catalog.json: decks must be a non-empty array');
  } else {
    const keys = new Set();
    for (const entry of catalog.decks) {
      const where = `catalog.json deck "${entry.key}"`;
      if (!isStr(entry.key) || !DECK_KEY_RE.test(entry.key)) fail(`${where}: bad key`);
      if (keys.has(entry.key)) fail(`${where}: duplicate key`);
      keys.add(entry.key);
      if (!isPosInt(entry.version)) fail(`${where}: version must be a positive integer`);
      if (!isStr(entry.name) || !isStr(entry.category)) fail(`${where}: needs name and category`);
      if (typeof entry.description !== 'string') fail(`${where}: needs description`);
      if (!isStr(entry.file)) {
        fail(`${where}: needs file`);
        continue;
      }

      const deck = readJson(entry.file);
      if (!deck) continue;
      const dwhere = entry.file;
      if (deck.key !== entry.key) fail(`${dwhere}: key does not match catalog entry`);
      if (deck.version !== entry.version) {
        fail(`${dwhere}: version ${deck.version} does not match catalog version ${entry.version} (bump both)`);
      }
      if (deck.name !== entry.name) fail(`${dwhere}: name does not match catalog entry`);
      if (deck.ttsLang !== null && typeof deck.ttsLang !== 'string') fail(`${dwhere}: bad ttsLang`);
      if (!Array.isArray(deck.notes) || deck.notes.length === 0) {
        fail(`${dwhere}: notes must be a non-empty array`);
        continue;
      }
      const noteKeys = new Set();
      let cardCount = 0;
      for (const [i, note] of deck.notes.entries()) {
        const nwhere = `${dwhere} note[${i}] (${note.key ?? 'no key'})`;
        if (!isStr(note.key)) fail(`${nwhere}: needs a stable key`);
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
        if (errors.length === 0 || note.fields) cardCount += cardCountForNote(note) ?? 0;
      }
      if (errors.length === 0 && entry.cardCount !== cardCount) {
        fail(`catalog.json deck "${entry.key}": cardCount ${entry.cardCount} but deck generates ${cardCount}`);
      }
    }
  }
}

if (errors.length > 0) {
  console.error(`FAILED: ${errors.length} problem(s)\n`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log('catalog and all deck files are valid');
