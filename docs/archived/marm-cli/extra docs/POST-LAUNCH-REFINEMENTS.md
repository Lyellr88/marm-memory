# MARM CLI - Post-Launch Refinements & Testing Backlog

**Status:** Deferred for real-world validation
**Created:** 2025-01-28
**Purpose:** Track improvements that require user feedback and testing before implementation

---

## Testing & Validation Needed

### 1. Context Bridge - Similarity Threshold Tuning

**Current State:**
- Hardcoded `similarity < 0.3` threshold for topic shift detection
- Location: `src/marm/automation.py` line ~233

**Issue:**
- Magic number based on intuition, not validated with real usage
- May be too sensitive (false positives) or too loose (missed shifts)

**Action Required:**
1. **Test Phase:** Use MARM CLI for 1-2 weeks in real development workflows
2. **Collect Data:** Log when context shifts are detected vs. when they should have been
3. **Tune Threshold:** Adjust based on false positive/negative rate
4. **Make Configurable:** Move to `config/settings.json` once optimal value is validated

**Configuration Target:**
```json
{
  "marm": {
    "context_detection": {
      "similarity_threshold": 0.3,
      "enable_topic_shift": true,
      "enable_file_shift": true,
      "enable_domain_shift": true,
      "enable_intent_shift": true
    }
  }
}
```

**Priority:** Medium
**Effort:** Low (5 minutes to implement after validation)
**Blocker:** Need real-world usage data first

---

### 2. Domain & Intent Keywords Expansion

**Current State:**
- 6 technical domains tracked (docker, database, frontend, backend, cli, ai)
- 5 intent types (learning, debugging, building, reviewing, general)
- Location: `src/marm/automation.py` lines 181-188, 277-290

**Issue:**
- Limited keyword coverage may miss valid context shifts
- No testing on diverse real-world conversations

**Action Required:**
1. **Test Phase:** Monitor domain/intent detection accuracy
2. **Expand Keywords:** Add missing domains (testing, deployment, networking, etc.)
3. **Refine Patterns:** Improve intent detection based on actual user language

**Priority:** Low
**Effort:** Low (incremental additions)
**Blocker:** Need usage patterns to identify gaps

---

### 3. File Path Extraction Edge Cases

**Current State:**
- Regex patterns for common file types (.py, .js, .ts, .json, .md, etc.)
- Location: `src/marm/automation.py` lines 292-313

**Issue:**
- May not handle all edge cases (paths with spaces, multiple paths, quoted paths)
- Unvalidated with real conversation patterns

**Action Required:**
1. **Test Phase:** Collect examples of how users mention files in natural language
2. **Identify Gaps:** Find patterns that aren't captured
3. **Refine Regex:** Add patterns for edge cases if needed

**Priority:** Low
**Effort:** Low (add patterns as needed)
**Blocker:** Need real conversations to identify edge cases

---

## Testing Infrastructure Needed

### 4. Comprehensive Test Suite

**Current State:**
- Basic smoke tests in `src/main.py test` command
- Tests database, semantic search, protocol, tool registration
- No automation behavior tests

**Missing Coverage:**
1. **Automation Tests:**
   - Auto-logging phrase detection (all 8 patterns)
   - Context shift detection (explicit + 4 implicit signals)
   - Refresh timer triggers (30min, 50msg, 10min idle)

2. **Integration Tests:**
   - Full chat session simulation
   - Tool invocation from LLM
   - Multi-turn conversations with context tracking

3. **Database Tests:**
   - Session validation edge cases
   - Embedding storage/retrieval
   - Concurrent access (WAL mode validation)

4. **Performance Tests:**
   - Semantic search latency
   - Database query performance
   - Memory usage over long sessions

**Action Required:**
1. Create `tests/` directory structure
2. Use pytest framework
3. Add CI/CD testing in GitHub Actions (future)

**Priority:** High (needed before Phase 4 completion)
**Effort:** High (2-3 days to build comprehensive suite)
**Blocker:** None - can start immediately after Phase 3b validation

**Proposed Structure:**
```
marm-cli/
├── tests/
│   ├── __init__.py
│   ├── test_automation.py      # Auto-logging, context detection, refresh
│   ├── test_database.py        # CRUD, validation, embeddings
│   ├── test_tools.py           # All 14 manual MARM tools
│   ├── test_protocol.py        # Protocol injection, system prompt
│   ├── test_integration.py     # End-to-end chat sessions
│   └── test_performance.py     # Latency, memory, load testing
└── pytest.ini
```

---

### 5. User Acceptance Testing (UAT) Plan

**Goal:** Validate MARM CLI works for real development workflows

**Test Scenarios:**
1. **Daily Development Session**
   - 50+ message conversation
   - Multiple file discussions
   - Context switches between debugging → building → reviewing
   - Verify auto-logging captures key moments

2. **Multi-Day Session Continuity**
   - Save/load sessions across days
   - Test smart recall across sessions
   - Verify protocol refresh doesn't break context

3. **Notebook Workflow**
   - Save reusable instructions
   - Activate notebook entries mid-conversation
   - Verify LLM follows activated instructions

4. **Memory Recall Accuracy**
   - Test semantic search across 100+ conversations
   - Verify relevant context is retrieved
   - Measure recall precision/accuracy

**Action Required:**
1. Recruit 2-3 beta testers (internal first)
2. Provide testing checklist
3. Collect feedback on automation behavior
4. Identify pain points and false positives

**Priority:** High (needed before public release)
**Effort:** Medium (1 week of testing + feedback iteration)
**Blocker:** Phase 3b must pass Gemini validation first

---

## Configuration System Improvements

### 6. Advanced Settings Exposure

**Current State:**
- Basic settings in `config/settings.json`
- No advanced automation tuning

**Future Additions:**
```json
{
  "marm": {
    "auto_log_patterns": {
      "accomplishments": ["fixed", "solved", "completed"],
      "setups": ["configured", "installed", "deployed"],
      "decisions": ["decided to", "going with", "chose"],
      "enable_custom_patterns": false
    },
    "refresh_triggers": {
      "time_minutes": 30,
      "message_count": 50,
      "idle_minutes": 10
    },
    "context_detection": {
      "similarity_threshold": 0.3,
      "signal_weights": {
        "topic_embedding": 1.0,
        "file_context": 0.8,
        "domain_shift": 0.6,
        "intent_shift": 0.4
      }
    }
  }
}
```

**Priority:** Low (Phase 5+)
**Effort:** Medium
**Blocker:** Need validated defaults first

---

## UI/UX Polish

### 8. True Screen Clear with Rich Live/Layout

**Current State:**
- `Ctrl+L` uses `os.system('cls'/'clear')` to clear screen
- This only clears the visible viewport by pushing content up with blank lines
- Users can scroll up to see old conversation history
- Location: `src/chat.py` lines ~99, 185

**Issue:**
- Not a true "clear" - old content remains in terminal scrollback buffer
- Professional TUIs (vim, htop, etc.) truly erase the display buffer
- Current behavior is cosmetic-only clear

**Gemini's Recommendation:**
- Use Rich's `Live` or `Layout` management for proper display control
- Manage entire chat interface as a Rich application
- True clear would reset the application's visual state entirely

**User Impact:**
- **Low** - Most users won't scroll up after clearing
- Works fine for 99% of use cases
- Only noticeable to power users who actively try to scroll back

**Action Required:**
1. **Refactor chat rendering** to use Rich `Live` object for all output
2. **Maintain chat history** in memory for context, but control display separately
3. **Clear operation** would re-render the `Live` display with empty history

**Priority:** Low (cosmetic improvement, minimal user impact)
**Effort:** Medium (requires refactoring chat display architecture)
**Blocker:** Current behavior is acceptable - defer until user feedback requests it

**Decision:** Keep current behavior. Re-evaluate after launch if users report issues or request true clear functionality.

---

## Documentation Improvements

### 7. User Guide for Automation Features

**Needed:**
- Explain how auto-logging works (with examples)
- Show when context bridges are created
- Teach users how to leverage automation
- Troubleshooting guide for false positives/negatives

**Priority:** Medium
**Effort:** Low (after UAT feedback)

---

## Review Schedule

- **Phase 4 Completion:** Review testing backlog
- **After 1 Week of Usage:** Analyze auto-logging patterns
- **After 1 Month:** Tune thresholds and add to settings
- **Before Public Release:** Complete test suite and UAT

---

**Last Updated:** 2025-01-28
**Owner:** Lyell (with Claude/Gemini validation)
