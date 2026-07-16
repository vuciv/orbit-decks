---
name: flashcards
description: Author or review spaced-repetition flashcards to best practices (minimum information principle, atomic cards, one fact per card). Use when creating a new deck, adding cards, rewriting an existing deck, or critiquing card quality in this repo. Trigger phrases: "make a deck", "add cards", "these cards are too dense", "review this deck", "split these cards".
user-invocable: true
---

# Flashcards

Author cards that are easy to grade and cheap to review. The failure mode this skill exists to prevent: cards that embed several facts at once, so the learner re-fails the whole card over the one part they forgot.

Grounding: Wozniak's Twenty Rules of Formulating Knowledge (supermemo.com/en/blog/twenty-rules-of-formulating-knowledge) and Matuschak's prompt-writing guide (andymatuschak.org/prompts). Do not re-research these; the operative rules are below.

## The quality bar

Every card must be:

1. **Focused**: asks for exactly one piece of information. One fact, one number, one distinction, one step.
2. **Precise**: the question admits exactly one correct answer. If two readers could answer differently and both be right, tighten the wording.
3. **Consistent**: produces the same answer on every review. No "it depends" backs.
4. **Tractable**: answerable in a few seconds once known. If answering requires a derivation, split the derivation into steps or card the conclusion.
5. **Effortful**: the answer must not be inferable from the question's wording. No echo questions.

The minimum information principle governs everything: many simple cards beat one complex card, because each fact gets its own review schedule. Total review time goes DOWN as card count goes up, when the split is real.

## Detecting a compound card

Split any card whose front contains:

- "and": "What is X and why is Y?" is two cards.
- "or asks for a definition plus a formula": definition card + cloze formula card.
- A statement plus a caveat/exception: statement card + caveat card.
- A set or enumeration as the answer ("What are the three ...?"). Sets are near-impossible to memorize (Wozniak rule 9). Either card each element with its own distinguishing anchor, or keep the set as a single chunk ONLY if it is culturally learned as one chunk (e.g. "0.2 / 0.5 / 0.8" for Cohen's d, "68-95-99.7").
- A back longer than one sentence. The back is the answer, not the lesson.

## Authoring rules

- **Back = one short answer.** Everything else (implications, mnemonics, worked examples, disambiguation, context) goes in `extra`, which the learner reads after answering and never has to recall.
- **Front carries context cues.** Anchor the domain in the question ("In a normal distribution, ...", "For independent random variables, ...") so the card is unambiguous without being longer.
- **Prefer cloze for formulas and numbers** embedded in a statement. One deletion per atomic fact. Multiple `{{cN::...}}` markers in one note are fine: each ordinal becomes its own card.
- **Prefer typed for short exact answers** (a number, a symbol, `sqrt(n)`), only when the expected input is unambiguous. Never typed when synonyms are acceptable.
- **Avoid bare yes/no questions.** Reframe to "why" or "what". Exception: misconception-busters where the point is the trap ("CIs overlap. Can you conclude no difference?" -> "No, because ...").
- **Misconception cards are high value.** Card the wrong belief explicitly: "X is NOT the probability of what?", "'95% chance the true value is in this interval' describes which kind of interval?".
- **Scenario cards for applied judgment.** A concrete vignette front ("Model A scores 72%, B 74% on 500 questions. Is B better?") with a single-verdict back. Vivid specifics resist interference and personalize (Wozniak rules 14-16).
- **Combat interference.** When splitting creates sibling cards that look alike (Type I vs Type II, IQR vs MAD), give each a distinct anchor in the front and a discriminating hook in `extra` (mnemonics help: "Type I cries wolf").
- **Redundancy from different angles is welcome** (Wozniak rule 17). A formula cloze plus a words-only definition of the same concept is good; two near-identical phrasings of the same ask is bad.
- **Order matters.** Authored note order is the order learners meet cards: fundamentals first, then rules built on them, then applications. A card may assume knowledge from earlier cards (Wozniak rule 13), never from later ones.

## Splitting procedure for an existing deck

1. Read the whole deck first; list which cards are compound and what atomic facts each contains.
2. For each compound card, decide the ONE core ask that keeps the original note key (an edit preserves the learner's review progress). Split-off facts get new keys.
3. Never reuse a key for semantically different content; delete the key instead (this wipes progress on it, so only do it when the old card was structurally broken).
4. Trim every surviving back to one sentence; demote the rest to `extra`.
5. Re-check sibling cards for interference and ordering.

## Repo mechanics (orbit-packs)

- One file per deck: `decks/<key>.json`. Models: `basic`, `basic_reversed`, `typed`, `cloze`, `sequence`, `occlusion` (fields per model in README.md).
- ANY edit to a deck file requires bumping its integer `version`.
- After editing: `node scripts/build.mjs` (regenerates catalog + shards), then `node scripts/build.mjs --check` must pass. Single-deck check while authoring: `node scripts/build.mjs --deck decks/<key>.json`.
- Facts must be verifiably correct; no emojis anywhere; verify every image URL with curl before committing.
- Do not commit or push unless asked: pushing to main publishes to users within minutes.

## Worked example

Bad (three facts, ungradeable):

    front: "What is standard deviation and why is it preferred over variance for reporting?"
    back:  "The square root of variance. It is in the same units as the data, so it reads as the typical distance of a value from the mean."

Good (two atomic cards):

    front: "How is standard deviation defined in terms of variance?"
    back:  "It is the square root of variance."
    extra: "sigma = sqrt(Var(X))."

    front: "Why is standard deviation preferred over variance for reporting?"
    back:  "It is in the same units as the data, so it reads as the typical distance from the mean."
    extra: "'Accuracy 74 plus or minus 3' only means something because the 3 shares units with the 74."

## Final checklist before finishing

- [ ] No front contains "and" joining two asks
- [ ] No back longer than one sentence (elaboration lives in `extra`)
- [ ] No set/enumeration answers except culturally-chunked ones
- [ ] Formulas are clozes; exact short answers are typed; nothing typed has acceptable synonyms
- [ ] Sibling cards have distinct anchors (interference check)
- [ ] Fundamentals precede applications in note order
- [ ] Keys: edits preserved, new facts got new keys, no key reused for different content
- [ ] `version` bumped, `node scripts/build.mjs --check` passes
