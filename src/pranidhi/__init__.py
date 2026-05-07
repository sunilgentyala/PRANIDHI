"""
PRANIDHI: Secure ENterprise Tokenisation, Inspection, and Nudging Engine
for LLM Interactions.

A pre-prompt data governance and coaching framework that scans corporate
user prompts before they reach external AI tools, and provides real-time
reformulation guidance instead of opaque blocking.
"""

__version__ = "0.1.0-alpha"
__author__ = "PRANIDHI Contributors"
__license__ = "Apache-2.0"

from pranidhi.pipeline import PranidhiPipeline
from pranidhi.models import ScanResult, RiskScore, Disposition, CoachingSuggestion

__all__ = [
    "PranidhiPipeline",
    "ScanResult",
    "RiskScore",
    "Disposition",
    "CoachingSuggestion",
]
