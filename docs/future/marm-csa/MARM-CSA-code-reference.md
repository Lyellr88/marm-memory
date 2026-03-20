# MARM Customer Support Accountability - Code Reference

**Purpose:** This document catalogs all code snippets and technical patterns from the Claude Opus 4.1 product discovery conversations. Each section includes line references, implementation guidance, and architectural context.

**Source:** cp dump.md analysis (859 lines of technical discussion)

**How to Use This Document:**
- Reference during implementation to see proven patterns
- Compare different architectural approaches for the same problem
- Understand when to use each pattern based on your constraints
- Copy/adapt code snippets as starting points (not production-ready)

---

## Table of Contents
1. [Core Class Structures](#core-class-structures)
2. [Database Schema Patterns](#database-schema-patterns)
3. [Processing Architectures](#processing-architectures)
4. [Integration Patterns](#integration-patterns)
5. [Complete UI Implementation](#complete-ui-implementation)
6. [Promise Queue System](#promise-queue-system)
7. [Advanced Features](#advanced-features)

---

## Core Class Structures

### MARMCustomerSupport Class (Lines 82-93)

**What it does:** Basic structure for the customer support memory system with core methods for logging interactions, retrieving context, tracking promises, and detecting patterns.

**When to use:** Starting architecture for MARM-CSA backend. This is your foundation class.

**Code:**
```python
class MARMCustomerSupport:
    def log_interaction(self, customer_id, agent_id, issue, resolution_promised):
        # Log with full context and reasoning

    def get_customer_context(self, customer_id):
        # Returns complete history, patterns, unresolved issues

    def track_promise(self, promise_id, due_date, responsible_agent):
        # Accountability tracking

    def detect_patterns(self, issue_type):
        # Find similar issues across customers
```

**Architectural Context:**
- This is the high-level interface that all features build on
- Each method represents a major feature area (logging, context retrieval, promises, patterns)
- Production implementation should add error handling, async support, and detailed docstrings
- Consider making this an abstract base class with concrete implementations for different data backends

**Next Steps:**
- Implement `log_interaction` first (simplest, enables everything else)
- `get_customer_context` is the core value prop - prioritize rich bullet-point formatting
- `track_promise` is the stickiness feature - see Promise Queue section for full implementation
- `detect_patterns` requires data volume - build last

---

## Database Schema Patterns

### Option 1: Separate Tables Per User (Lines 124-140)

**What it does:** Creates completely isolated table sets for each customer (user_12345_sessions, user_12345_memories, etc.)

**When to use:** NEVER for production. Only mentioned as anti-pattern.

**Code:**
```sql
-- For each new user, create their own set of tables
CREATE TABLE user_12345_sessions (...);
CREATE TABLE user_12345_memories (...);
CREATE TABLE user_12345_interactions (...);
```

**Why it's bad:**
- Nightmare to maintain at scale (10,000 users = 30,000 tables)
- Schema updates require updating EVERY user's tables
- Most databases have table limits
- Terrible query performance across users

**Pros (why it was mentioned):**
- Complete data isolation
- Easy to delete all user data (GDPR compliance)
- No cross-user query accidents

**Verdict:** Don't use this approach.

---

### Option 2: Separate Schemas Per User (Lines 141-146)

**What it does:** PostgreSQL-specific approach using schemas as namespaces for user data.

**When to use:** Only if you have extreme regulatory requirements (healthcare, financial) requiring physical data separation.

**Code:**
```sql
-- PostgreSQL example
CREATE SCHEMA user_12345;
CREATE TABLE user_12345.sessions (...);
CREATE TABLE user_12345.memories (...);
```

**Pros:**
- Better than separate tables (schemas are cleaner)
- Some PostgreSQL performance optimizations available
- Easier data export/deletion per user

**Cons:**
- Still has scaling issues (thousands of schemas)
- PostgreSQL-specific (not portable)
- Complex query logic

**Verdict:** Consider only for highly regulated industries.

---

### Option 3: Shared Tables with User ID - RECOMMENDED (Lines 148-162)

**What it does:** Standard multi-tenant database pattern using user_id columns with proper indexing.

**When to use:** THIS IS THE DEFAULT. Use for MARM-CSA unless you have specific reasons not to.

**Code:**
```sql
CREATE TABLE sessions (
    id PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    session_data TEXT,
    created_at TIMESTAMP,
    INDEX idx_user_id (user_id)
);

CREATE TABLE memories (
    id PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    memory_content TEXT,
    INDEX idx_user_id (user_id)
);
```

**Why this is recommended:**
- How 99% of production apps work
- Scalable to millions of users
- Every query just includes WHERE user_id = ?
- Easy schema updates (one ALTER TABLE)
- Cross-user analytics possible
- Standard practices apply (ORMs work)

**Critical Implementation Details:**
- ALWAYS index user_id columns
- ALWAYS include user_id in WHERE clauses (prevent data leaks)
- Consider composite indexes: (user_id, created_at) for time-based queries
- Use database-level row-level security if available (PostgreSQL RLS)

---

### Option 4: Hybrid with Partitioning (Lines 164-193)

**What it does:** Combines shared tables with performance partitioning based on user_id hash.

**When to use:** When you have >100,000 customers and query performance degrades. Not needed for MVP.

**Code:**
```python
class MARMUserDatabase:
    def __init__(self):
        # Shared tables for metadata
        self.users_table = "users"
        self.accounts_table = "accounts"

    def get_user_partition(self, user_id):
        # Partition by user_id for performance
        partition_id = hash(user_id) % 10
        return f"memories_partition_{partition_id}"
```

**SQL for OnePay/Customer Support:**
```sql
-- Company-level separation
CREATE SCHEMA onepay;

-- Shared structure, partitioned by customer
CREATE TABLE onepay.support_sessions (
    id BIGSERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255),
    session_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    -- Partition by customer_id for performance
) PARTITION BY HASH (customer_id);

-- Auto-create partitions
CREATE TABLE onepay.support_sessions_0 PARTITION OF onepay.support_sessions
    FOR VALUES WITH (modulus 100, remainder 0);
-- ... create 100 partitions
```

**When to implement:**
- After 100K+ customers when queries slow down
- When single table >100GB
- When you have dedicated DBA resources

**Complexity tradeoffs:**
- Adds operational complexity
- Requires PostgreSQL 10+ (or equivalent partitioning in other DBs)
- Query planner must understand partitioning for performance

---

### Recommended Schema for MARM-CSA MVP

**Use Option 3 (Shared Tables) with this specific schema:**

```sql
-- Customer table
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) UNIQUE NOT NULL,
    external_id VARCHAR(255),  -- OnePay's customer ID
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    INDEX idx_customer_id (customer_id),
    INDEX idx_external_id (external_id)
);

-- Support interactions
CREATE TABLE interactions (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255),
    interaction_type VARCHAR(50),  -- call, email, chat, ticket
    transcript TEXT,
    summary TEXT,  -- LLM-generated bullet points
    sentiment VARCHAR(50),  -- angry, frustrated, satisfied
    resolution_status VARCHAR(50),  -- resolved, escalated, pending
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_customer_id (customer_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_created_at (created_at),
    INDEX idx_composite (customer_id, created_at)
);

-- Promise tracking
CREATE TABLE promises (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    interaction_id INT REFERENCES interactions(id),
    promise_text TEXT NOT NULL,
    due_date TIMESTAMP NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, completed, overdue, cancelled
    completed_at TIMESTAMP,
    escalated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_customer_id (customer_id),
    INDEX idx_status (status),
    INDEX idx_due_date (due_date),
    INDEX idx_composite (status, due_date)  -- For callback dashboard queries
);

-- Pattern detection (simplified)
CREATE TABLE issue_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(255),
    issue_type VARCHAR(100),
    customer_count INT DEFAULT 1,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    severity VARCHAR(50),  -- low, medium, high, critical
    INDEX idx_issue_type (issue_type)
);

-- Pattern-to-customer mapping
CREATE TABLE pattern_customers (
    pattern_id INT REFERENCES issue_patterns(id),
    customer_id VARCHAR(255) NOT NULL,
    interaction_id INT REFERENCES interactions(id),
    detected_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (pattern_id, customer_id)
);
```

---

## Processing Architectures

**Context:** Three different approaches for processing support conversations, from lines 198-270.

### Option 1: Real-Time Processing (Lines 198-219)

**What it does:** Processes conversations as they happen, providing live context to agents during active calls.

**When to use:** Premium tier feature, when milliseconds matter, when you have budget for real-time infrastructure.

**Code:**
```python
class MARMRealTimeProcessor:
    def __init__(self):
        self.transcription_service = "Deepgram/AssemblyAI"  # Real-time transcription
        self.llm = "Claude/GPT-4"

    async def process_live_call(self, audio_stream):
        # Step 1: Real-time transcription
        transcript = await self.transcribe_stream(audio_stream)

        # Step 2: Chunk processing (every 30 seconds or speaker turn)
        for chunk in transcript:
            # Step 3: Extract key information in real-time
            extracted = await self.llm.extract({
                "issue_type": "fraud|account_locked|payment_failed",
                "customer_emotion": "angry|frustrated|satisfied",
                "promises_made": ["refund by Friday", "callback tomorrow"],
                "resolution_status": "resolved|escalated|pending"
            })

            # Step 4: Update MARM database immediately
            self.update_customer_context(customer_id, extracted)
```

**Infrastructure Requirements:**
- WebSocket connections for audio streaming
- Deepgram/AssemblyAI real-time API (~$0.006/minute)
- Fast LLM API (Claude Haiku for cost efficiency)
- Redis for real-time state management
- Low-latency database (sub-100ms writes)

**Cost Estimate:**
- Transcription: $0.006/minute
- LLM processing: $0.01/call (using cheap models)
- For 1000 calls/day: ~$150/day = $4,500/month

**Pros:**
- Agent gets context during call (can interrupt with "I see you called 3 times")
- Can detect promises as they're made
- Highest value to agents

**Cons:**
- Most expensive option
- Complex infrastructure
- Latency-sensitive (harder to debug)

---

### Option 2: Post-Call Batch Processing - RECOMMENDED FOR MVP (Lines 220-240)

**What it does:** Processes completed call transcripts after the fact, updates database for next interaction.

**When to use:** MVP and Growth tier. Simpler, cheaper, 90% of the value.

**Code:**
```python
class MARMBatchProcessor:
    async def process_support_transcript(self, transcript, customer_id):
        # Send to LLM for analysis
        prompt = f"""
        Analyze this support transcript and extract:
        1. Main issue(s) discussed
        2. Promises made by agent
        3. Resolution status
        4. Follow-up actions needed
        5. Customer sentiment
        6. Any fraud indicators mentioned

        Transcript: {transcript}

        Return as JSON.
        """

        analysis = await self.llm.complete(prompt)

        # Store in MARM database
        self.store_interaction(customer_id, analysis)

        # Check for patterns across customers
        if "fraud" in analysis["issues"]:
            self.check_fraud_pattern(analysis["fraud_details"])
```

**Infrastructure Requirements:**
- Job queue (Celery, RabbitMQ, or simple cron)
- Batch LLM API calls (can queue and process)
- Standard database (PostgreSQL, MySQL)

**Cost Estimate:**
- LLM processing only: $0.01/call
- For 1000 calls/day: ~$10/day = $300/month (15x cheaper than real-time)

**Pros:**
- Much simpler infrastructure
- 90% cheaper than real-time
- Can use smarter/slower LLMs (better quality)
- Easier to debug and iterate

**Cons:**
- Context not available during first call (only subsequent calls)
- Promises detected after call ends (can't alert agent mid-call)

**Why this is recommended for MVP:**
- OnePay's problem is "agent on call #4 has no context from calls #1-3"
- Batch processing solves this 100%
- Real-time is overkill for the core pain point

---

### Option 3: Hybrid Processing (Lines 246-270)

**What it does:** Real-time alerts for critical issues, batch processing for full analysis.

**When to use:** After MVP is validated, when you want premium tier differentiation.

**Code:**
```python
class MARMAgentAssist:
    def __init__(self):
        self.real_time_alerts = True
        self.auto_categorization = True

    async def monitor_conversation(self, call_id):
        # Listen to live conversation
        while call_active:
            transcript_chunk = await self.get_latest_transcript(call_id)

            # Real-time processing for specific triggers
            if "previous agent told me" in transcript_chunk:
                # Alert current agent with context
                previous_context = self.get_previous_interactions(customer_id)
                self.alert_agent(previous_context)

            # Auto-detect promises
            if "I will" in transcript_chunk or "we can" in transcript_chunk:
                promise = self.extract_promise(transcript_chunk)
                self.log_promise(promise, agent_id, timestamp)

            # Pattern detection
            if self.detect_fraud_pattern(transcript_chunk):
                similar_cases = self.find_similar_fraud_cases()
                self.alert_fraud_team(similar_cases)
```

**What runs real-time:**
- Trigger phrase detection ("previous agent told me", "I will call you back")
- Fraud keyword alerts
- Escalation triggers

**What runs batch:**
- Full transcript summarization
- Deep pattern analysis
- Sentiment analysis

**Best of both worlds:**
- Cheap simple rules for real-time alerts
- Expensive LLM analysis happens post-call
- Agents get critical info during call, full context after

---

## Integration Patterns

### Webhook Integration for Existing Support Systems (Lines 272-292)

**What it does:** Receives webhooks from existing support platforms (Zendesk, Freshdesk) when calls complete, automatically processes transcripts.

**When to use:** Enterprise Integration Layer (Build 5). Essential for "add-on not replacement" positioning.

**Code:**
```javascript
// Webhook from their phone system
app.post('/call-completed', async (req, res) => {
    const { call_id, recording_url, transcript } = req.body;

    // Send to MARM for processing
    const analysis = await marmProcessor.analyzeCall({
        transcript: transcript,
        customer_id: req.body.customer_id,
        agent_id: req.body.agent_id
    });

    // Auto-create tickets for unresolved issues
    if (analysis.needs_followup) {
        await createTicket({
            customer_id: analysis.customer_id,
            issue: analysis.unresolved_issues,
            promised_resolution: analysis.promises_made,
            due_date: analysis.promised_timeline
        });
    }
});
```

**Webhook URL Structure:**
```
POST https://marm-api.example.com/webhooks/zendesk/call-completed
POST https://marm-api.example.com/webhooks/freshdesk/ticket-updated
POST https://marm-api.example.com/webhooks/intercom/conversation-closed
```

**Security Requirements:**
- Webhook signature verification (HMAC)
- IP whitelist for known platforms
- Rate limiting per client
- Idempotency keys (prevent duplicate processing)

**Error Handling:**
```javascript
app.post('/call-completed', async (req, res) => {
    try {
        // Verify webhook signature
        if (!verifyWebhookSignature(req)) {
            return res.status(401).json({ error: 'Invalid signature' });
        }

        // Quick response (don't make webhook wait)
        res.status(202).json({ status: 'accepted', call_id: req.body.call_id });

        // Process asynchronously
        await queue.add('process-call', {
            call_id: req.body.call_id,
            transcript: req.body.transcript,
            customer_id: req.body.customer_id,
            agent_id: req.body.agent_id
        });

    } catch (error) {
        console.error('Webhook processing error:', error);
        res.status(500).json({ error: 'Processing failed' });
    }
});
```

**Testing Webhooks:**
```bash
# Use ngrok for local testing
ngrok http 3000

# Send test webhook
curl -X POST https://your-ngrok-url.ngrok.io/call-completed \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Signature: test-signature" \
  -d '{
    "call_id": "test-123",
    "customer_id": "cust-456",
    "agent_id": "agent-789",
    "transcript": "Customer: I was promised a callback...",
    "recording_url": "https://example.com/recording.mp3"
  }'
```

---

## Complete UI Implementation

### Flask Backend + HTML/CSS/JS UI (Lines 334-492)

**What it does:** Complete production-ready MARM Companion interface with backend API and frontend UI.

**When to use:** This is your MVP UI. Start here.

**Backend (Flask):**
```python
# Simple Flask backend
from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)

class MARMCompanion:
    def __init__(self):
        self.db = sqlite3.connect('customer_context.db')

    def get_customer_summary(self, customer_id):
        """Returns bullet points of customer history"""
        history = self.fetch_customer_history(customer_id)

        # AI summarizes into bullet points
        summary = {
            "key_issues": [
                "• Account frozen on Oct 15 - unresolved",
                "• Reported fraud 3 times, no refund yet",
                "• Promised callback Oct 18 - never received"
            ],
            "customer_status": "ESCALATED - High frustration",
            "previous_agents": ["Agent Mike - Oct 15", "Agent Sarah - Oct 17"],
            "promises_made": [
                "❗ Refund within 48 hours (OVERDUE)",
                "✓ New card sent (completed)"
            ],
            "similar_cases": "47 other customers with identical fraud pattern"
        }
        return summary

@app.route('/api/customer/<customer_id>')
def get_context(customer_id):
    companion = MARMCompanion()
    return jsonify(companion.get_customer_summary(customer_id))

@app.route('/api/log', methods=['POST'])
def log_interaction():
    # Auto-logs from main support system
    data = request.json
    # Process and store interaction
    return jsonify({"status": "logged"})
```

**Frontend (HTML/CSS/JS):**
```html
<!DOCTYPE html>
<html>
<head>
    <title>MARM Companion</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .context-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .customer-id {
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin-bottom: 20px;
        }
        .section {
            margin-bottom: 15px;
        }
        .section-title {
            font-weight: 600;
            color: #666;
            margin-bottom: 5px;
            text-transform: uppercase;
            font-size: 12px;
        }
        .bullet-point {
            margin: 5px 0;
            padding: 5px;
            background: #f9f9f9;
            border-radius: 4px;
        }
        .alert {
            background: #ff4444;
            color: white;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 10px;
        }
        .chat-input {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-top: 10px;
        }
        .status-escalated {
            color: #ff4444;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="context-card">
        <div class="customer-id">Customer #48573</div>

        <div class="alert">
            ⚠️ HIGH PRIORITY - Multiple unresolved issues
        </div>

        <div class="section">
            <div class="section-title">Key Issues</div>
            <div class="bullet-point">• Account frozen Oct 15 - UNRESOLVED</div>
            <div class="bullet-point">• Fraud reported 3 times - no refund</div>
            <div class="bullet-point">• Promised callback never received</div>
        </div>

        <div class="section">
            <div class="section-title">Promises Made (Track Record)</div>
            <div class="bullet-point" style="background: #ffeeee;">
                ❗ Refund within 48 hours - OVERDUE (Oct 17)
            </div>
            <div class="bullet-point" style="background: #eeffee;">
                ✓ New card sent - Completed
            </div>
        </div>

        <div class="section">
            <div class="section-title">Pattern Alert</div>
            <div class="bullet-point" style="background: #fff3cd;">
                🔍 47 other customers with identical fraud pattern - possible security breach
            </div>
        </div>

        <div class="section">
            <div class="section-title">Quick Ask MARM</div>
            <input type="text" class="chat-input" placeholder="What did previous agents promise?" />
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setInterval(() => {
            fetch(`/api/customer/${customerId}`)
                .then(r => r.json())
                .then(data => updateUI(data));
        }, 30000);

        // Listen for updates from main support system
        const ws = new WebSocket('ws://localhost:8001/updates');
        ws.onmessage = (event) => {
            const update = JSON.parse(event.data);
            addNewContext(update);
        };
    </script>
</body>
</html>
```

**Key UI Design Patterns:**
- **Color coding for urgency:**
  - Red background (#ffeeee) = overdue/critical
  - Green background (#eeffee) = completed/success
  - Yellow background (#fff3cd) = warning/alert
- **Consistent spacing:** 20px padding, 15px section margins, 5px bullet margins
- **Visual hierarchy:** 24px customer ID, 12px section titles, 14px (default) content
- **Emoji signals:** ⚠️ alerts, ❗ overdue, ✓ completed, 🔍 patterns

**Accessibility Considerations:**
- Use semantic HTML (section, header tags not shown in snippet but should be added)
- Ensure color contrast ratios meet WCAG 2.1 AA standards
- Add aria-labels for screen readers
- Keyboard navigation for input fields

---

## Promise Queue System

### MARMPromiseTracker Class (Lines 765-789)

**What it does:** Complete promise detection and callback routing system with auto-detection from conversations.

**When to use:** Build 2 (Promise Queue System). This is the stickiness feature.

**Code:**
```python
class MARMPromiseTracker:
    def __init__(self):
        self.promise_queue = []
        self.callback_team_dashboard = {}

    def auto_detect_promise(self, conversation):
        # AI detects promises in real-time
        if "I'll call you back" in conversation or "we'll resolve this by" in conversation:
            promise = {
                "customer_id": customer_id,
                "promise_made": "Callback by Friday 3pm",
                "agent_who_promised": "Mike S.",
                "due": "2025-01-10 15:00",
                "status": "PENDING",
                "context": full_conversation_summary
            }
            self.route_to_callback_team(promise)

    def callback_team_dashboard(self):
        # Separate UI showing only callbacks needed
        return {
            "overdue": [...],  # RED - These are on fire
            "due_today": [...], # YELLOW - Need attention
            "upcoming": [...]   # GREEN - Plan ahead
        }
```

**Enhanced Promise Detection with LLM:**
```python
async def detect_promises_with_llm(self, transcript, customer_id, agent_id):
    """
    Uses LLM to detect promises with high accuracy
    """
    prompt = f"""
    Analyze this support transcript and extract any promises made by the agent.

    Look for:
    - Callbacks ("I'll call you back", "We'll reach out tomorrow")
    - Timebound commitments ("We'll resolve this by Friday", "You'll receive refund in 48 hours")
    - Action commitments ("I will escalate this", "We can send you a new card")

    For each promise, extract:
    1. Promise text (what was promised)
    2. Due date/time (when it should happen)
    3. Promise type (callback, refund, escalation, etc.)
    4. Confidence level (high/medium/low)

    Transcript:
    {transcript}

    Return as JSON array.
    """

    response = await self.llm.complete(prompt)
    promises = json.loads(response)

    for promise_data in promises:
        if promise_data['confidence'] in ['high', 'medium']:
            promise = {
                'customer_id': customer_id,
                'agent_id': agent_id,
                'promise_text': promise_data['text'],
                'promise_type': promise_data['type'],
                'due_date': self.parse_due_date(promise_data['due']),
                'status': 'pending',
                'created_at': datetime.now()
            }
            self.save_promise(promise)
            self.route_to_callback_team(promise)
```

**Parsing Due Dates from Natural Language:**
```python
def parse_due_date(self, due_text):
    """
    Convert "Friday 3pm", "in 48 hours", "tomorrow" to datetime
    """
    from dateutil import parser
    import parsedatetime as pdt

    cal = pdt.Calendar()
    time_struct, parse_status = cal.parse(due_text)

    if parse_status:
        return datetime(*time_struct[:6])
    else:
        # Fallback: ask LLM to convert to ISO format
        return self.llm_parse_date(due_text)
```

---

### Auto-Escalation Logic (Lines 817-821)

**What it does:** Automatically escalates overdue promises to supervisors and triggers customer outreach.

**When to use:** After Promise Queue MVP is working. This prevents promises from falling through cracks.

**Code:**
```python
if promise.is_overdue_by(hours=24):
    escalate_to_supervisor()
    send_apology_email_to_customer()
    flag_for_executive_review()
```

**Production Implementation:**
```python
class PromiseEscalationEngine:
    def __init__(self):
        self.escalation_rules = {
            'tier_1': {'hours_overdue': 4, 'action': 'notify_agent'},
            'tier_2': {'hours_overdue': 24, 'action': 'escalate_supervisor'},
            'tier_3': {'hours_overdue': 48, 'action': 'executive_review'}
        }

    async def check_overdue_promises(self):
        """
        Runs every hour via cron
        """
        overdue_promises = self.db.query("""
            SELECT * FROM promises
            WHERE status = 'pending'
            AND due_date < NOW()
        """)

        for promise in overdue_promises:
            hours_overdue = (datetime.now() - promise.due_date).total_seconds() / 3600

            # Determine escalation tier
            if hours_overdue >= 48:
                await self.executive_review(promise)
            elif hours_overdue >= 24:
                await self.escalate_to_supervisor(promise)
            elif hours_overdue >= 4:
                await self.notify_agent(promise)

    async def notify_agent(self, promise):
        """Tier 1: Gentle reminder to original agent"""
        await self.email_service.send(
            to=promise.agent_email,
            subject=f"Reminder: Callback due for {promise.customer_id}",
            body=f"You promised to call back {promise.customer_id} by {promise.due_date}. Please complete this callback today."
        )

        # Log the notification
        self.db.insert('promise_escalations', {
            'promise_id': promise.id,
            'tier': 1,
            'action': 'agent_notification',
            'timestamp': datetime.now()
        })

    async def escalate_to_supervisor(self, promise):
        """Tier 2: Supervisor takes over + customer apology"""
        # Notify supervisor
        supervisor = self.get_agent_supervisor(promise.agent_id)
        await self.email_service.send(
            to=supervisor.email,
            subject=f"ESCALATED: Overdue callback for {promise.customer_id}",
            body=f"Agent {promise.agent_id} missed callback promised {promise.due_date}. Please reassign."
        )

        # Send customer apology email
        await self.email_service.send(
            to=self.get_customer_email(promise.customer_id),
            subject="We apologize for the delay",
            body=f"We sincerely apologize for missing our callback commitment. A senior specialist will contact you within 4 hours."
        )

        # Auto-assign to callback team
        await self.route_to_callback_team(promise, priority='urgent')

        # Update promise status
        self.db.update('promises', promise.id, {
            'status': 'escalated',
            'escalated_at': datetime.now()
        })

    async def executive_review(self, promise):
        """Tier 3: Critical failure - executive intervention"""
        # Notify executive team
        await self.slack_service.send(
            channel='#executive-alerts',
            message=f"🚨 CRITICAL: Promise to {promise.customer_id} overdue by 48+ hours. Customer may churn."
        )

        # Authorize compensation
        compensation = self.calculate_compensation(promise)
        await self.create_compensation_ticket(promise.customer_id, compensation)

        # Flag for root cause analysis
        self.db.insert('executive_review_queue', {
            'promise_id': promise.id,
            'customer_id': promise.customer_id,
            'agent_id': promise.agent_id,
            'hours_overdue': (datetime.now() - promise.due_date).total_seconds() / 3600,
            'created_at': datetime.now()
        })
```

**Cron Setup:**
```bash
# Run every hour
0 * * * * /usr/bin/python /path/to/check_overdue_promises.py
```

---

### Pattern Detection for Broken Promises (Lines 823-825)

**What it does:** Tracks which agents consistently break promises, triggers retraining or supervisor approval requirements.

**When to use:** After 3+ months of promise data to identify patterns.

**Code:**
```python
if agent.broken_promises > 3:
    require_supervisor_approval_for_promises()
    flag_for_training()
```

**Production Implementation:**
```python
class AgentPerformanceTracker:
    def calculate_promise_metrics(self, agent_id, timeframe_days=30):
        """
        Calculate agent's promise-keeping performance
        """
        metrics = self.db.query(f"""
            SELECT
                COUNT(*) as total_promises,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as kept_promises,
                SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as broken_promises,
                AVG(TIMESTAMPDIFF(HOUR, due_date, completed_at)) as avg_completion_delay
            FROM promises
            WHERE agent_id = '{agent_id}'
            AND created_at > DATE_SUB(NOW(), INTERVAL {timeframe_days} DAY)
        """)

        fulfillment_rate = metrics.kept_promises / metrics.total_promises if metrics.total_promises > 0 else 1.0

        return {
            'agent_id': agent_id,
            'total_promises': metrics.total_promises,
            'fulfillment_rate': fulfillment_rate,
            'broken_promises': metrics.broken_promises,
            'avg_delay_hours': metrics.avg_completion_delay,
            'performance_tier': self.classify_performance(fulfillment_rate)
        }

    def classify_performance(self, fulfillment_rate):
        """Classify agent into performance tier"""
        if fulfillment_rate >= 0.95:
            return 'excellent'
        elif fulfillment_rate >= 0.85:
            return 'good'
        elif fulfillment_rate >= 0.70:
            return 'needs_improvement'
        else:
            return 'critical'

    async def enforce_accountability_rules(self, agent_id):
        """
        Apply consequences for poor promise-keeping
        """
        metrics = self.calculate_promise_metrics(agent_id)

        if metrics['performance_tier'] == 'critical':
            # Require supervisor approval for all new promises
            await self.db.update('agents', agent_id, {
                'promise_approval_required': True,
                'approval_reason': f"Fulfillment rate {metrics['fulfillment_rate']:.1%} below 70%"
            })

            # Flag for mandatory training
            await self.create_training_assignment(agent_id, 'promise_management_101')

            # Notify supervisor
            supervisor = self.get_agent_supervisor(agent_id)
            await self.email_service.send(
                to=supervisor.email,
                subject=f"Action Required: {agent_id} promise performance critical",
                body=f"{agent_id} has broken {metrics['broken_promises']} promises in 30 days. Supervisor approval now required."
            )

        elif metrics['performance_tier'] == 'needs_improvement':
            # Weekly coaching sessions
            await self.schedule_coaching(agent_id, frequency='weekly', duration_weeks=4)
```

**Dashboard for Managers:**
```python
def get_team_promise_leaderboard(self, team_id):
    """
    Show which agents are best/worst at keeping promises
    """
    agents = self.db.query(f"""
        SELECT
            agent_id,
            agent_name,
            COUNT(*) as total_promises,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as kept,
            (SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / COUNT(*)) as rate
        FROM promises p
        JOIN agents a ON p.agent_id = a.id
        WHERE a.team_id = '{team_id}'
        AND p.created_at > DATE_SUB(NOW(), INTERVAL 30 DAY)
        GROUP BY agent_id, agent_name
        ORDER BY rate DESC
    """)

    return agents
```

---

### Customer Scoring and Priority Routing (Lines 827-829)

**What it does:** Routes high-value customers with overdue promises to senior specialists, can authorize automatic compensation.

**When to use:** Once you have customer value data (LTV, revenue, tenure).

**Code:**
```python
if customer.value == "high" and promise.status == "overdue":
    route_to_senior_callback_specialist()
    authorize_compensation_offer()
```

**Production Implementation:**
```python
class CustomerPriorityRouter:
    def __init__(self):
        self.priority_tiers = {
            'vip': {'min_ltv': 10000, 'max_response_hours': 2},
            'high_value': {'min_ltv': 5000, 'max_response_hours': 4},
            'standard': {'min_ltv': 1000, 'max_response_hours': 24},
            'low_value': {'min_ltv': 0, 'max_response_hours': 48}
        }

    def calculate_customer_priority(self, customer_id):
        """
        Determine customer priority based on multiple factors
        """
        customer = self.db.get_customer(customer_id)

        # Calculate lifetime value
        ltv = customer.total_revenue

        # Factor in tenure (longer customers = more valuable)
        tenure_months = (datetime.now() - customer.created_at).days / 30
        tenure_multiplier = min(1 + (tenure_months / 12) * 0.1, 1.5)  # Max 1.5x

        # Factor in recent activity
        recent_purchases = self.db.count_purchases(customer_id, days=30)
        activity_multiplier = 1 + (recent_purchases * 0.05)  # +5% per recent purchase

        # Adjusted LTV
        adjusted_ltv = ltv * tenure_multiplier * activity_multiplier

        # Determine tier
        for tier, config in self.priority_tiers.items():
            if adjusted_ltv >= config['min_ltv']:
                return {
                    'tier': tier,
                    'ltv': adjusted_ltv,
                    'max_response_hours': config['max_response_hours']
                }

        return {'tier': 'low_value', 'ltv': adjusted_ltv, 'max_response_hours': 48}

    async def route_overdue_promise(self, promise):
        """
        Route overdue promise based on customer priority
        """
        priority = self.calculate_customer_priority(promise.customer_id)

        if priority['tier'] == 'vip':
            # VIP: Assign to senior specialist immediately + auto-compensate
            specialist = self.get_available_specialist('senior')
            await self.assign_callback(promise.id, specialist.id, priority='critical')

            # Authorize compensation
            compensation = self.calculate_vip_compensation(promise)
            await self.create_compensation_offer(promise.customer_id, compensation)

            # Notify executive
            await self.slack_service.send(
                channel='#vip-escalations',
                message=f"🚨 VIP customer {promise.customer_id} has overdue promise. Specialist {specialist.name} assigned. ${compensation} compensation authorized."
            )

        elif priority['tier'] == 'high_value':
            # High-value: Assign to experienced agent + supervisor notification
            agent = self.get_available_agent('experienced')
            await self.assign_callback(promise.id, agent.id, priority='high')

            # Notify supervisor
            supervisor = self.get_callback_team_supervisor()
            await self.email_service.send(
                to=supervisor.email,
                subject=f"High-value customer callback: {promise.customer_id}",
                body=f"${priority['ltv']:.0f} LTV customer needs callback. Assigned to {agent.name}."
            )

        else:
            # Standard/Low: Normal callback queue
            await self.add_to_callback_queue(promise, priority='normal')
```

**Compensation Calculation:**
```python
def calculate_vip_compensation(self, promise):
    """
    Calculate appropriate compensation for VIP customer inconvenience
    """
    hours_overdue = (datetime.now() - promise.due_date).total_seconds() / 3600

    # Base compensation
    base = 25  # $25 base

    # Scale with delay
    if hours_overdue > 48:
        compensation = base * 4  # $100 for 48+ hour delay
    elif hours_overdue > 24:
        compensation = base * 2  # $50 for 24+ hour delay
    else:
        compensation = base  # $25 for <24 hour delay

    # Cap at reasonable amount
    return min(compensation, 200)
```

---

## Advanced Features

### Real-Time WebSocket Updates (Lines 485-491)

**What it does:** Provides live updates to agent UI when new context arrives, without page refresh.

**When to use:** Growth tier feature for better UX. Not needed for MVP.

**Code:**
```javascript
// Listen for updates from main support system
const ws = new WebSocket('ws://localhost:8001/updates');
ws.onmessage = (event) => {
    const update = JSON.parse(event.data);
    addNewContext(update);
};
```

**Backend WebSocket Server (Python):**
```python
import asyncio
import websockets
import json

class MARMWebSocketServer:
    def __init__(self):
        self.connections = {}  # agent_id -> websocket

    async def register(self, websocket, agent_id):
        """Register agent connection"""
        self.connections[agent_id] = websocket
        try:
            await websocket.wait_closed()
        finally:
            del self.connections[agent_id]

    async def broadcast_customer_update(self, customer_id, update_data):
        """Send update to all agents viewing this customer"""
        # Find which agents are viewing this customer
        viewing_agents = await self.db.query("""
            SELECT agent_id FROM active_sessions
            WHERE customer_id = ?
        """, customer_id)

        # Send update to those agents
        message = json.dumps({
            'type': 'customer_update',
            'customer_id': customer_id,
            'data': update_data
        })

        for agent in viewing_agents:
            if agent.id in self.connections:
                await self.connections[agent.id].send(message)

# Start server
async def main():
    server = MARMWebSocketServer()
    async with websockets.serve(server.register, "localhost", 8001):
        await asyncio.Future()  # run forever

asyncio.run(main())
```

**Frontend JavaScript (Enhanced):**
```javascript
class MARMRealtimeClient {
    constructor(agentId, customerId) {
        this.agentId = agentId;
        this.customerId = customerId;
        this.ws = null;
        this.reconnectDelay = 1000;
        this.connect();
    }

    connect() {
        this.ws = new WebSocket(`ws://localhost:8001/updates?agent_id=${this.agentId}`);

        this.ws.onopen = () => {
            console.log('Connected to MARM updates');
            this.reconnectDelay = 1000;

            // Subscribe to customer updates
            this.ws.send(JSON.stringify({
                type: 'subscribe',
                customer_id: this.customerId
            }));
        };

        this.ws.onmessage = (event) => {
            const update = JSON.parse(event.data);
            this.handleUpdate(update);
        };

        this.ws.onclose = () => {
            console.log('Disconnected from MARM. Reconnecting...');
            setTimeout(() => this.connect(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);  // Max 30s
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleUpdate(update) {
        switch(update.type) {
            case 'new_interaction':
                this.addInteractionToUI(update.data);
                this.showNotification('New interaction logged');
                break;
            case 'promise_created':
                this.addPromiseToUI(update.data);
                this.showNotification(`New promise: ${update.data.promise_text}`);
                break;
            case 'promise_overdue':
                this.markPromiseOverdue(update.data.promise_id);
                this.showAlert(`Promise overdue: ${update.data.promise_text}`);
                break;
            case 'pattern_detected':
                this.showPatternAlert(update.data);
                break;
        }
    }

    addInteractionToUI(interaction) {
        const container = document.getElementById('interactions');
        const element = document.createElement('div');
        element.className = 'bullet-point';
        element.textContent = `• ${interaction.summary}`;
        container.prepend(element);  // Add to top

        // Highlight with animation
        element.style.animation = 'fadeIn 0.5s';
    }

    showNotification(message) {
        const notification = document.createElement('div');
        notification.className = 'notification';
        notification.textContent = message;
        document.body.appendChild(notification);

        setTimeout(() => notification.remove(), 3000);
    }
}

// Usage
const realtimeClient = new MARMRealtimeClient('agent-123', 'customer-456');
```

---

## Implementation Checklists

### MVP Launch Checklist (Build 1: MARM Companion)

**Week 1:**
- [ ] Set up database (PostgreSQL recommended, SQLite OK for MVP)
- [ ] Create schema (customers, interactions, promises tables)
- [ ] Basic Flask/FastAPI backend with /api/customer/<id> endpoint
- [ ] LLM integration (Claude Haiku API for cost efficiency)
- [ ] Simple HTML/CSS UI from lines 377-491

**Week 2:**
- [ ] Conversation summarization (bullet points not essays)
- [ ] Real-time updates (polling every 30s, WebSocket for v2)
- [ ] Security: API key authentication, rate limiting
- [ ] Error handling and logging
- [ ] Write API documentation

**Week 3-4:**
- [ ] Screenshot upload and analysis
- [ ] Quick chat interface for agents
- [ ] Testing with sample OnePay data
- [ ] Security audit preparation
- [ ] Demo video recording

**Pre-launch:**
- [ ] Pen testing ($5K minimum)
- [ ] Load testing (100 concurrent agents)
- [ ] Backup and recovery procedures
- [ ] Monitoring and alerting setup
- [ ] Customer support documentation

---

### Promise Queue Checklist (Build 2)

**Week 1:**
- [ ] Promise detection NLP logic (lines 770-789)
- [ ] Promise database table with proper indexes
- [ ] Basic promise list API endpoint
- [ ] Test with 50+ sample transcripts

**Week 2:**
- [ ] Callback routing logic
- [ ] Email notification system for overdue promises
- [ ] Promise status updates (pending → completed)
- [ ] Integration with MARM Companion UI

**Week 3:**
- [ ] Auto-escalation workflows (lines 817-821)
- [ ] Agent performance tracking (lines 823-825)
- [ ] Supervisor approval requirements
- [ ] Testing with real pilot customer

**Week 4:**
- [ ] Customer priority routing (lines 827-829)
- [ ] Compensation authorization logic
- [ ] Analytics dashboard for managers
- [ ] Documentation and training materials

---

## Performance Optimization Notes

### Database Optimization
- Always index foreign keys (customer_id, agent_id)
- Use composite indexes for common queries: (customer_id, created_at)
- Consider partitioning promises table by status (pending/completed/overdue)
- Use database connection pooling (SQLAlchemy pool_size=10)

### LLM API Optimization
- Cache summarizations (same transcript = same summary)
- Use cheaper models for simple tasks (Haiku vs Opus)
- Batch requests when possible (5 summaries in 1 API call)
- Set reasonable timeouts (10s max)

### Frontend Optimization
- Lazy load old interactions (only show last 10, load more on scroll)
- Debounce search inputs (300ms delay)
- Use CSS animations instead of JavaScript (better performance)
- Compress images before upload

---

## Security Best Practices

### Data Protection
- Encrypt sensitive fields (customer PII) at rest
- Use HTTPS only (no HTTP)
- Rotate API keys quarterly
- Hash agent IDs in logs (prevent tracking)

### Access Control
- Role-based access (agent, supervisor, admin)
- Audit log all data access
- Require MFA for supervisor accounts
- Auto-logout after 30 minutes idle

### Compliance
- SOC 2 Type II certification (required for enterprise)
- GDPR compliance (data export, right to deletion)
- CCPA compliance (California customers)
- Regular penetration testing (quarterly)

---

**Document Version:** 1.0
**Last Updated:** 2025-10-25
**Code Source:** Lines 82-829 of cp dump.md
**Warning:** Code snippets are conceptual. Requires production hardening before deployment.
