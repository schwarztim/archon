"""Red-team sub-package — automated adversarial testing of AI agents."""

from security.red_team.attacks import Attack, AttackCategory, Severity
from security.red_team.engine import RedTeamEngine

__all__ = ["RedTeamEngine", "Attack", "AttackCategory", "Severity"]
