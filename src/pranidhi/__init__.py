"""
PRANIDHI: Prompt Risk Analysis, Network Inspection & Data Handling Integrity.

A pre-prompt data governance and coaching framework that scans corporate
user prompts before they reach external AI tools, and provides real-time
reformulation guidance instead of opaque blocking.
"""

__version__ = "0.2.0"
__author__ = "PRANIDHI Contributors"
__license__ = "Apache-2.0"

from pranidhi.models import CoachingSuggestion, Disposition, RiskScore, ScanResult
from pranidhi.pipeline import PranidhiPipeline

__all__ = [
    "CoachingSuggestion",
    "Disposition",
    "PranidhiPipeline",
    "RiskScore",
    "ScanResult",
]
