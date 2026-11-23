"""What every agent on Jarvis's team is: a profile, the only tools it may use, what it's allowed to do,
its share of the daily AI budget, and an on/off switch."""
from dataclasses import dataclass, field

from ..config import settings

# What an agent may do. Checked in code (Brain._run_tool), not just asked of the AI.
READ, FILES, SEND, DEVICE = "read", "write files", "send messages", "control devices"


@dataclass
class Specialist:
    name: str                 # id: "scholar"
    title: str                # shown: "Scholar"
    job: str                  # one line, for the dashboard and for Jarvis when choosing who to ask
    instructions: str         # this agent's own system instructions
    color: str
    icon: str
    permissions: tuple = (READ,)
    budget: int = 0           # default share of the day's AI requests (Settings can change it)
    personal: bool = False    # handles personal data, so private mode keeps it off online AI
    tools: set = field(default_factory=set)

    @property
    def enabled(self):
        return bool(settings.get(f"agent_{self.name}_on", True))

    @property
    def budget_share(self):
        return int(settings.get(f"agent_{self.name}_budget", self.budget) or 0)

    def may(self, permission):
        return permission in self.permissions

    def profile(self):
        return {"name": self.name, "title": self.title, "job": self.job, "color": self.color, "icon": self.icon,
                "permissions": list(self.permissions), "budget": self.budget_share, "enabled": self.enabled,
                "tools": sorted(self.tools), "personal": self.personal}
