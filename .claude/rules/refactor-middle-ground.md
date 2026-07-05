# Refactor Middle Ground

**Preserve behavior first**  
**Reduce complexity with the smallest clean extraction that helps**

Refactor in layers, not by explosion.

---

## Base Concept

### Do's

**Start with the easiest low-risk extractions first**

- Pull out sections that are already self-contained
- Prefer light edits and import rewiring over reshaping behavior

**Keep orchestration close to the current owner until a real boundary appears**

- Preserve the main shell/controller file when it still owns the workflow clearly
- Extract real subflows, not arbitrary chunks

**Explore medium/harder splits only when the easy wins are already taken**

- Move deeper only when the next boundary is concrete
- Stop before fragmentation starts costing clarity

**Prefer preservation over abstraction**

- Verbatim extraction is better than inventing a new pattern without pressure for it
- Do not introduce a new architecture just to make the refactor feel more complete
- Facelift not brain surgery: all features must behave as they did

### Don'ts

**Do not split everything just because a file is long**

- Length alone is not enough
- Avoid tiny components/modules with no real boundary

---

## Shared Models And Config

### Do's

**Keep file-local models local until reuse or drift appears**

**If a Pydantic model is copied into a second file, promote it to `core/models.py`**

**Do not create future-proof global model files too early**

**Move shared config/data only when another consumer appears or duplication starts**

### Don'ts

**Do not create future-proof global model files too early**

---

## Current Backend Application

### Do's

**Split endpoint logic by ownership and workflow surface, not by line count alone**

**When logic follows extracted module boundaries, keep shared helpers in the core file and move surface-specific logic only**

**Preserve parent orchestration modules**

**Extract real workflow/service boundaries only**

**Move shared domain types/config only when a second consumer appears or drift starts**

**Refactors: match existing behavior but preserve all functionality (session state, embeddings, rate limiting)**

**Simplify internals: cut redundant layers, keep the happy path obvious**

### Don'ts

**Do not explode endpoints into tiny modules without a strong boundary**
