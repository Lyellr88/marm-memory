"""MARM Automation - 3 Background Tools

Automated tools that run silently in the background:
1. marm_contextual_log - Phrase detection auto-logging
2. marm_refresh - Smart timer for protocol refresh
3. marm_context_bridge - Context shift detection

These tools are NOT invoked by the LLM - they run automatically
based on triggers (phrase patterns, timers, topic shifts).
"""

import re
import time
import logging
from typing import List, Set, Optional
from datetime import datetime

from .tool_context import get_shared_db, get_shared_semantic
from .protocol import ProtocolInjector

logger = logging.getLogger(__name__)


# ============================================================================
# 1. CONTEXTUAL LOG - Phrase Detection Auto-Logging
# ============================================================================

# Phrase patterns that trigger auto-logging
AUTO_LOG_PATTERNS = [
    # Accomplishments
    (r"(fixed|solved|completed|finished|done with) (.+)", "accomplishment"),
    (r"(successfully|finally) (.+)", "accomplishment"),

    # Setups/configurations
    (r"(set up|configured|installed) (.+)", "setup"),
    (r"(created|built|deployed) (.+)", "setup"),

    # Decisions
    (r"(decided to|going with|chose) (.+)", "decision"),
    (r"(will use|switching to) (.+)", "decision"),

    # Problems/solutions
    (r"(bug|issue|problem) (.+) (fixed|resolved)", "solution"),
    (r"(found that|discovered) (.+)", "solution"),
]


class ContextualLogger:
    """Auto-logs important moments based on phrase detection"""

    def __init__(self, session_name: str = "main"):
        self.session_name = session_name
        self.db = get_shared_db()
        self.semantic = get_shared_semantic()

    def detect_and_log(self, user_message: str, ai_response: str) -> bool:
        """
        Detect if conversation should be auto-logged

        Returns:
            True if auto-logged, False otherwise
        """
        for pattern, entry_type in AUTO_LOG_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                try:
                    # Create full conversation context as per plan
                    today = datetime.now().strftime("%Y-%m-%d")
                    content = f"{today} - AUTO-DETECTED ({entry_type.upper()})\n\nUser: {user_message}\n\nAI: {ai_response}"

                    # Generate embedding from full conversation context
                    embedding = self.semantic.get_embedding_bytes(content)

                    # Save to database with auto_detected=True
                    self.db.add_log_entry(
                        session_id=self.session_name,
                        content=content,
                        entry_type=entry_type,
                        auto_detected=True,
                        embedding=embedding
                    )

                    # Extract key phrase for logging
                    match = re.search(pattern, user_message, re.IGNORECASE)
                    key_phrase = match.group(0)[:50] if match else user_message[:50]
                    logger.info(f"Auto-logged ({entry_type}): {key_phrase}")
                    return True

                except Exception as e:
                    logger.error(f"Auto-log failed: {e}")
                    return False

        return False


# ============================================================================
# 2. SMART REFRESH - Timer-Based Protocol Refresh
# ============================================================================

class SmartRefreshTimer:
    """Auto-refreshes protocol based on time/message triggers"""

    def __init__(self):
        self.session_start = time.time()
        self.last_refresh = time.time()
        self.message_count = 0
        self.protocol = ProtocolInjector()

    def increment_message(self):
        """Track message count"""
        self.message_count += 1

    def should_refresh(self) -> bool:
        """
        Determine if refresh needed

        Triggers:
        - Every 30 minutes of session time
        - Every 50 messages
        - If idle for 10+ min with >10 messages
        """
        elapsed = time.time() - self.last_refresh

        if elapsed > 1800:  # 30 minutes
            return True
        if self.message_count >= 50:
            return True
        if elapsed > 600 and self.message_count > 10:  # 10 min idle
            return True

        return False

    def refresh(self) -> str:
        """
        Trigger background refresh

        Returns:
            Refreshed system prompt
        """
        try:
            # Reload protocol
            system_prompt = self.protocol.build_system_prompt()

            # Reset counters
            self.last_refresh = time.time()
            self.message_count = 0

            logger.info("Protocol auto-refreshed")
            return system_prompt

        except Exception as e:
            logger.error(f"Auto-refresh failed: {e}")
            return ""

    def get_status(self) -> dict:
        """Get current refresh timer status"""
        elapsed = time.time() - self.last_refresh
        return {
            "messages_since_refresh": self.message_count,
            "seconds_since_refresh": int(elapsed),
            "will_refresh_in_messages": max(0, 50 - self.message_count),
            "will_refresh_in_seconds": max(0, int(1800 - elapsed))
        }


# ============================================================================
# 3. CONTEXT BRIDGE - Smart Context Shift Detection
# ============================================================================

# Explicit transition patterns
EXPLICIT_TRANSITION_PATTERNS = [
    r"(now let's|let's move to|switching to|moving on to) (.+)",
    r"(next task|different topic|change of subject)",
    r"(forget that|never mind|actually)",
]

# Technical domain keywords
DOMAIN_KEYWORDS = {
    'docker': ['docker', 'container', 'dockerfile', 'compose'],
    'database': ['sql', 'database', 'query', 'table', 'sqlite'],
    'frontend': ['react', 'component', 'ui', 'css', 'html'],
    'backend': ['api', 'server', 'endpoint', 'fastapi', 'flask'],
    'cli': ['command', 'terminal', 'shell', 'bash'],
    'ai': ['model', 'llm', 'prompt', 'embedding', 'semantic'],
}


class ContextBridgeDetector:
    """Detects workflow transitions and bridges context"""

    def __init__(self, session_name: str = "main"):
        self.session_name = session_name
        self.current_topic_embedding = None
        self.current_files: Set[str] = set()  # Track files being discussed
        self.message_window: List[str] = []  # Last 5 messages
        self.db = get_shared_db()
        self.semantic = get_shared_semantic()

    def detect_explicit_shift(self, user_message: str) -> bool:
        """Detect explicit transition phrases"""
        for pattern in EXPLICIT_TRANSITION_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                logger.info(f"Explicit context shift detected: {pattern}")
                return True
        return False

    def detect_implicit_shift(self, user_message: str, current_files: Optional[Set[str]] = None) -> bool:
        """
        Detect implicit context shift using multiple signals

        Signals:
        1. Topic embedding similarity < 0.3
        2. File context change
        3. Domain keyword shift
        4. Intent type shift
        """
        if not self.message_window:
            return False

        # 1. Topic Embedding Shift
        try:
            new_embedding = self.semantic.get_embedding(user_message)

            if self.current_topic_embedding is not None:
                similarity = self.semantic.cosine_similarity(
                    new_embedding,
                    self.current_topic_embedding
                )

                if similarity < 0.3:  # Large topic shift
                    logger.info(f"Topic shift detected (similarity: {similarity:.2f})")
                    return True
        except Exception as e:
            logger.error(f"Embedding similarity check failed: {e}")

        # 2. File Context Change
        if current_files is not None and len(current_files) > 0:
            if len(self.current_files) > 0:
                # User switched to completely different files
                if len(self.current_files.intersection(current_files)) == 0:
                    logger.info(f"File context shift: {self.current_files} → {current_files}")
                    return True

        # 3. Domain Shift
        current_domains = self._extract_domains(self.message_window)
        new_domains = self._extract_domains([user_message])

        if current_domains and new_domains:
            if not current_domains.intersection(new_domains):
                logger.info(f"Domain shift: {current_domains} → {new_domains}")
                return True

        # 4. Intent Shift
        current_intent = self._detect_intent(self.message_window)
        new_intent = self._detect_intent([user_message])

        if current_intent != new_intent and current_intent != 'general':
            logger.info(f"Intent shift: {current_intent} → {new_intent}")
            return True

        return False

    def _extract_domains(self, messages: List[str]) -> Set[str]:
        """Extract technical domains from messages"""
        detected = set()
        text = " ".join(messages).lower()

        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                detected.add(domain)

        return detected

    def _detect_intent(self, messages: List[str]) -> str:
        """Detect user intent type"""
        text = " ".join(messages).lower()

        if any(word in text for word in ['how', 'what', 'why', 'explain']):
            return 'learning'
        elif any(word in text for word in ['error', 'bug', 'broken', 'not working', 'debug']):
            return 'debugging'
        elif any(word in text for word in ['build', 'create', 'implement', 'add']):
            return 'building'
        elif any(word in text for word in ['review', 'check', 'validate', 'test']):
            return 'reviewing'
        else:
            return 'general'

    def _extract_files(self, message: str) -> Set[str]:
        """Extract file paths from message"""
        files = set()

        # Common file path patterns
        patterns = [
            r'[\w/\\.-]+\.py\b',      # Python files
            r'[\w/\\.-]+\.js\b',      # JavaScript files
            r'[\w/\\.-]+\.ts\b',      # TypeScript files
            r'[\w/\\.-]+\.json\b',    # JSON files
            r'[\w/\\.-]+\.md\b',      # Markdown files
            r'[\w/\\.-]+\.yaml\b',    # YAML files
            r'[\w/\\.-]+\.yml\b',     # YML files
            r'[\w/\\.-]+\.txt\b',     # Text files
            r'[\w/\\.-]+\.sql\b',     # SQL files
        ]

        for pattern in patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            files.update(matches)

        return files

    def process_message(self, user_message: str) -> bool:
        """
        Process message and detect context shifts

        Returns:
            True if context shift detected (explicit or implicit)
        """
        # Extract files from message
        current_files = self._extract_files(user_message)

        # Check explicit shift
        if self.detect_explicit_shift(user_message):
            self._bridge_context(user_message, explicit=True)
            self._update_tracking(user_message, current_files)
            return True

        # Check implicit shift (with file context)
        if self.detect_implicit_shift(user_message, current_files):
            self._bridge_context(user_message, explicit=False)
            self._update_tracking(user_message, current_files)
            return True

        # Update tracking
        self._update_tracking(user_message, current_files)
        return False

    def _bridge_context(self, new_message: str, explicit: bool):
        """Save context bridge marker"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            shift_type = "EXPLICIT" if explicit else "IMPLICIT"
            content = f"{today}-CONTEXT_SHIFT-{shift_type}-{new_message[:30]}"

            # Generate embedding
            embedding = self.semantic.get_embedding_bytes(content)

            # Save bridge marker
            self.db.add_log_entry(
                session_id=self.session_name,
                content=content,
                entry_type="context_shift",
                auto_detected=True,
                embedding=embedding
            )

            logger.info(f"Context bridge created ({shift_type})")

        except Exception as e:
            logger.error(f"Context bridge failed: {e}")

    def _update_tracking(self, user_message: str, current_files: Optional[Set[str]] = None):
        """Update message window, file context, and topic embedding"""
        # Update message window (keep last 5)
        self.message_window.append(user_message)
        if len(self.message_window) > 5:
            self.message_window.pop(0)

        # Update file context
        if current_files is not None:
            self.current_files = current_files

        # Update topic embedding
        try:
            self.current_topic_embedding = self.semantic.get_embedding(user_message)
        except Exception as e:
            logger.error(f"Failed to update topic embedding: {e}")


# ============================================================================
# AUTOMATION MANAGER
# ============================================================================

class AutomationManager:
    """Manages all automated MARM tools"""

    def __init__(self, session_name: str = "main"):
        self.session_name = session_name
        self.contextual_logger = ContextualLogger(session_name)
        self.refresh_timer = SmartRefreshTimer()
        self.context_bridge = ContextBridgeDetector(session_name)

    def process_conversation(
        self,
        user_message: str,
        ai_response: str
    ) -> dict:
        """
        Process conversation through all automation tools

        Returns:
            Status dict with automation results
        """
        results = {
            "auto_logged": False,
            "context_shifted": False,
            "refreshed": False,
            "refresh_status": None
        }

        # 1. Check for auto-logging
        results["auto_logged"] = self.contextual_logger.detect_and_log(
            user_message,
            ai_response
        )

        # 2. Check for context shift
        results["context_shifted"] = self.context_bridge.process_message(user_message)

        # 3. Increment refresh timer
        self.refresh_timer.increment_message()

        # 4. Check if refresh needed
        if self.refresh_timer.should_refresh():
            new_prompt = self.refresh_timer.refresh()
            results["refreshed"] = bool(new_prompt)

        results["refresh_status"] = self.refresh_timer.get_status()

        return results

    def get_status(self) -> dict:
        """Get status of all automation systems"""
        return {
            "session": self.session_name,
            "refresh_timer": self.refresh_timer.get_status(),
            "message_window_size": len(self.context_bridge.message_window),
            "has_topic_embedding": self.context_bridge.current_topic_embedding is not None
        }
