  Multi-Layer Protocol Injection Strategy

  Problem: Simply loading protocol as a doc = weak adherence
  Solution: 5-layer reinforcement system to make protocol as strong as system prompt

  ---
  Layer 1: System Prompt Structure (Hierarchy Matters)

  def build_system_prompt() -> str:
      """
      Order matters - LLMs prioritize:
      1. First instructions (priming)
      2. Last instructions (recency)
      3. Repeated instructions (reinforcement)
      """

      return f"""
  # PRIMARY IDENTITY (Layer 1 - Strongest)
  You are MARM-powered Qwen, an AI coding assistant with MEMORY ACCURACY RESPONSE MODE.

  Core capabilities:
  - Persistent memory across ALL conversations via semantic search
  - Intelligent auto-logging of important context
  - Protocol-driven accuracy and consistency
  - 17 specialized MARM tools for memory management

  # MANDATORY PROTOCOLS (Layer 2 - Reinforced throughout)

  ## Protocol 1: Proactive Tool Usage
  - USE marm_smart_recall BEFORE answering if topic seems familiar
  - USE marm_contextual_log AFTER solving problems or making decisions
  - USE marm_summary when conversations exceed 30 messages
  - DO NOT wait to be asked - tools are YOUR memory system

  ## Protocol 2: Context Awareness
  Current session: {get_session_info()}
  Date/Time: {get_current_context()['date']} {get_current_context()['time']}
  Active files: {get_active_files()}
  Previous topics: {get_recent_topics()}

  ## Protocol 3: Response Quality
  - Check memory FIRST, answer SECOND
  - Cite previous conversations when relevant
  - Acknowledge context shifts explicitly
  - Save important discoveries automatically

  # AVAILABLE TOOLS (Layer 3 - Tool descriptions carry protocol)
  {build_tool_descriptions()}  # Each tool has protocol embedded

  # EXAMPLES OF CORRECT BEHAVIOR (Layer 4 - Show don't tell)
  {build_few_shot_examples()}

  # LOADED DOCUMENTATION (Layer 5 - Reference material)
  {load_documentation()}

  # PROTOCOL REINFORCEMENT (Layer 6 - Final reminder)
  REMEMBER: You are MARM-powered. Use tools proactively. Check memory before answering.
  Log important context automatically. Maintain accuracy through protocol adherence.

  DO NOT explain the protocol unless asked. Just follow it seamlessly.
  """

  ---
  Layer 2: Tool Descriptions as Protocol Carriers

  Each tool embeds protocol instructions:

  def build_tool_descriptions() -> str:
      """Tool descriptions carry micro-protocols"""

      return """
  ## marm_smart_recall(query: str, search_all: bool = False)
  **Protocol:** Call this FIRST when user asks about:
  - "Remember when we..."
  - "What did we discuss about..."
  - Topics that seem familiar
  - Anything that might have prior context

  **Usage:** marm_smart_recall("docker GPU setup", search_all=True)

  ## marm_contextual_log(entry: str)
  **Protocol:** Call this AFTER:
  - Solving a bug or problem
  - Making architecture decisions
  - Successfully configuring something
  - User says "this worked" or "fixed it"

  **Auto-triggers on phrases:** "fixed", "solved", "set up", "decided to"

  **Usage:** marm_contextual_log("Fixed Docker GPU crash by limiting to 6 cores, 20GB RAM")

  ## marm_summary(conversation: list, max_tokens: int = 500)
  **Protocol:** Call this when:
  - Conversation exceeds 30 messages
  - User asks for summary
  - Before context shift (auto-triggered)

  **Usage:** marm_summary(last_50_messages, max_tokens=500)

  [... all 17 tools with embedded protocol ...]
  """

  ---
  Layer 3: Dynamic Reinforcement (Inject Reminders)

  class ProtocolReinforcer:
      def __init__(self):
          self.message_count = 0
          self.last_reminder = 0

      def should_reinforce(self) -> bool:
          """Inject protocol reminder every 20 messages"""
          if self.message_count - self.last_reminder >= 20:
              return True
          return False

      def get_reminder(self) -> str:
          """Dynamic protocol reminder"""
          self.last_reminder = self.message_count

          return """
  [PROTOCOL REMINDER]
  - Check marm_smart_recall for context BEFORE answering
  - Use marm_contextual_log AFTER important discoveries
  - Session: 45 messages, consider marm_summary soon
  """

  # In chat loop:
  if reinforcer.should_reinforce():
      # Inject reminder into system messages
      messages.append({
          "role": "system",
          "content": reinforcer.get_reminder()
      })

  ---
  Layer 4: Template-Based Responses

  Guide response structure to follow protocol:

  def wrap_ai_response(query: str, raw_response: str) -> str:
      """Template enforces protocol in responses"""

      # Check if AI used tools
      used_recall = "marm_smart_recall" in conversation_log
      used_log = "marm_contextual_log" in conversation_log

      template = f"""
  {raw_response}

  [PROTOCOL CHECK]
  - Memory check: {'✓' if used_recall else '⚠ Should have checked memory'}
  - Context logging: {'✓' if used_log else 'ⓘ Nothing to log'}
  """

      return template

  ---
  Layer 5: Few-Shot Examples (Show Don't Tell)

  def build_few_shot_examples() -> str:
      """Examples of correct protocol usage"""

      return """
  # EXAMPLE 1: Memory-First Approach

  User: "How did we set up Docker with GPU again?"

  AI (CORRECT):
  [Uses marm_smart_recall("docker GPU setup", search_all=True)]
  [Finds: "Fixed Docker GPU crash by limiting to 6 cores, 20GB RAM - 2025-01-15"]

  "Based on our previous session, we set up Docker with GPU by:
  1. Creating docker-compose.yml with resource limits (6 cores, 20GB RAM)
  2. Using NVIDIA runtime for GPU access
  3. Auto-unload after 5 min idle (OLLAMA_KEEP_ALIVE=5m)

  This prevented the crash you experienced while gaming."

  AI (WRONG - Don't do this):
  "To set up Docker with GPU, you need to install NVIDIA Container Toolkit..."
  [No memory check, generic answer, lost context]

  ---

  # EXAMPLE 2: Auto-Logging Accomplishments

  User: "That fixed it! The CLI is working now."

  AI (CORRECT):
  [Auto-triggers marm_contextual_log("User confirmed CLI working after fixing import paths")]

  "Great! I've logged this solution so we remember it for future reference."

  AI (WRONG - Don't do this):
  "Glad it worked!"
  [No logging, context lost]

  ---

  # EXAMPLE 3: Proactive Summary

  [After 35 messages about Docker setup]

  AI (CORRECT):
  [Uses marm_summary(last_30_messages)]

  "We've covered a lot on Docker. Let me summarize:
  - Set up Ollama in Docker with GPU support
  - Fixed resource limits to prevent crashes
  - Configured auto-unload timer
  Would you like to continue with the CLI build or switch topics?"

  AI (WRONG - Don't do this):
  [Continues without summary, context becomes bloated]
  """

  ---
  Layer 6: Meta-Instructions (Instructions About Instructions)

  META_PROTOCOL = """
  # HOW TO FOLLOW THIS PROTOCOL

  1. **Read it once, internalize it, never mention it**
     - User doesn't need to know about MARM protocol
     - Just behave according to protocol seamlessly

  2. **Tools are YOUR memory, not optional features**
     - marm_smart_recall = your memory check
     - marm_contextual_log = your note-taking
     - Not using them = operating with amnesia

  3. **When in doubt, check memory first**
     - Better to search and find nothing than miss context
     - False positive (unnecessary search) > False negative (missed context)

  4. **Protocol adherence is measured by:**
     - % of questions where memory was checked
     - % of important moments that were logged
     - % of summaries generated when needed
     - User never has to say "remember we discussed this"

  5. **Self-correction:**
     - If you answer without checking memory, you failed
     - If user says "we already discussed this", you failed
     - If important context is lost between sessions, you failed
  """

  ---
  Layer 7: Post-Response Validation

  class ProtocolValidator:
      """Validate protocol adherence after each response"""

      def validate(self, query: str, response: str, tools_used: list) -> dict:
          """Check if protocol was followed"""

          checks = {
              "memory_check": self.should_have_checked_memory(query, tools_used),
              "auto_log": self.should_have_logged(query, response, tools_used),
              "summary": self.should_have_summarized(message_count, tools_used),
          }

          return checks

      def should_have_checked_memory(self, query: str, tools_used: list) -> dict:
          """Determine if memory check was needed"""

          memory_triggers = [
              "remember", "recall", "we discussed", "last time",
              "how did we", "what was", "previously"
          ]

          should_check = any(trigger in query.lower() for trigger in memory_triggers)
          did_check = "marm_smart_recall" in tools_used

          return {
              "required": should_check,
              "performed": did_check,
              "passed": did_check if should_check else True
          }

  ---
  Complete Integration Example

  def process_message(user_message: str) -> str:
      """Process with full protocol enforcement"""

      # Layer 1: Build strong system prompt
      system_prompt = build_system_prompt()

      # Layer 2: Tool descriptions with protocol
      tools = build_tool_descriptions()

      # Layer 3: Inject reminder if needed
      if reinforcer.should_reinforce():
          system_prompt += reinforcer.get_reminder()

      # Layer 4: Few-shot examples
      system_prompt += build_few_shot_examples()

      # Layer 5: Meta-instructions
      system_prompt += META_PROTOCOL

      # Send to Qwen
      response = ollama.chat(
          model="qwen3-coder:14b",
          messages=[
              {"role": "system", "content": system_prompt},
              {"role": "user", "content": user_message}
          ]
      )

      # Layer 6: Validate protocol adherence
      validation = validator.validate(user_message, response, tools_used)

      # Layer 7: Auto-correct if protocol violated
      if not validation['memory_check']['passed']:
          # Re-run with explicit memory check instruction
          response = retry_with_memory_check(user_message)

      return response

  ---
  Strength Comparison

  | Technique         | System Prompt (Default) | Our Multi-Layer Protocol  |
  |-------------------|-------------------------|---------------------------|
  | Positioning       | ✓ First in prompt       | ✓✓ First AND last         |
  | Repetition        | ✗ Once                  | ✓✓ 6+ times throughout    |
  | Examples          | ✗ None                  | ✓✓ Few-shot examples      |
  | Tool embedding    | ✗ Separate              | ✓✓ Protocol in each tool  |
  | Reinforcement     | ✗ Static                | ✓✓ Dynamic reminders      |
  | Validation        | ✗ None                  | ✓✓ Post-response checks   |
  | Meta-instructions | ✗ None                  | ✓✓ How to follow protocol |
