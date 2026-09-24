-- 007_loop_contract.sql — lock the LOOP, not the layout (Shaan's anti-finality principle).
-- Registers units with tier + provenance + challenge_hook, and an explicit LOOP allowlist
-- (the only near-immutable set). The layout itself is tier=capability. Bumps schema_version to 7.

-- Every governed unit (skill, agent, doc, brick) declares its tier + why-it-exists + how-to-kill-it.
CREATE TABLE IF NOT EXISTS units (
    id           TEXT PRIMARY KEY,        -- path or logical id, e.g. 'skills/implement'
    kind         TEXT,                    -- skill | agent | doc | brick | adapter
    tier         TEXT DEFAULT 'capability', -- contract | core | capability | disposable
    provenance   TEXT,                    -- why it's shaped this way
    challenge_hook TEXT,                   -- what would prove it wrong / what would beat it
    rating       INTEGER,                 -- /100, reigning-champion score (null = unrated)
    clean_uses   INTEGER DEFAULT 0,       -- for auto-promotion of capability units
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_units_tier ON units(tier);

-- THE LOOP ALLOWLIST: the only things that are tier=contract. Touching these = T3 (always human-gated).
-- This is what we lock — NOT the layout. The layout is a versioned hypothesis (tier=capability).
INSERT OR IGNORE INTO units(id, kind, tier, provenance, challenge_hook) VALUES
 ('loop/brain-identity','contract','contract','spine DB exists, single-writer on the Mini, schema-migration discipline','a better durable-state model that keeps single-source-of-truth + cross-machine + restart-proof'),
 ('loop/boot-manifest-exists','contract','contract','every CLI reads ONE self-describing entry; its EXISTENCE is fixed, its CONTENTS are versioned','a discovery mechanism that needs no manifest yet stays cold-boot legible'),
 ('loop/improvement-loop','contract','contract','intake->grade->challenge->promote-or-log-why + the gate + the adversary sweep — the process IS the contract','a self-improvement process that converges faster without these stages');

-- The canonical layout itself is explicitly tier=capability — revisable, must keep winning.
INSERT OR IGNORE INTO units(id, kind, tier, provenance, challenge_hook, rating) VALUES
 ('docs/CANONICAL-LAYOUT','doc','capability','flat-noun retrieval + tier-as-metadata + brain-enforced; converged via adversarial debate 2026-06-01','a year-4 god-frame layout that beats flat-noun+metadata on legibility-of-what-is-safe-to-mutate at 40-model scale', 85);

-- Challenges: the self-gaslight ledger. A scheduled sweep files rated challengers vs the reigning champion.
CREATE TABLE IF NOT EXISTS challenges (
    id          TEXT PRIMARY KEY,
    target      TEXT NOT NULL,            -- units.id being challenged
    challenger  TEXT,                     -- who/what raised it (adversary sweep | research | agent)
    argument    TEXT NOT NULL,            -- why the current design might be wrong / what would beat it
    rating      INTEGER,                  -- /100 of the challenger vs champion
    verdict     TEXT DEFAULT 'open',      -- open | promoted | logged-why-not
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version(version, note)
    VALUES (7, 'lock-the-loop: units(tier+provenance+challenge_hook) + loop allowlist + challenges ledger');
