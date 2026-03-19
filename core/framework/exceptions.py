"""Framework exceptions for the oikOS Agent Framework."""


class ApprovalRequired(Exception):
    """Raised when a tool requires ASK_FIRST approval before execution."""

    def __init__(self, proposal_id: str, tool_name: str):
        self.proposal_id = proposal_id
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' requires approval (proposal: {proposal_id})")


class RateLimitExceeded(Exception):
    """Raised when a tool exceeds its per-minute rate limit."""

    def __init__(self, tool_name: str, retry_after: float):
        self.tool_name = tool_name
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded for '{tool_name}' (retry after {retry_after:.0f}s)")


class PrivacyViolation(Exception):
    """Raised when content violates privacy tier enforcement."""

    def __init__(self, tool_name: str, tier: str):
        self.tool_name = tool_name
        self.tier = tier
        super().__init__(f"Privacy violation on '{tool_name}': content classified as {tier}")
