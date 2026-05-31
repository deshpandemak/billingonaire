"""
Order Document Analysis System
=============================

This module provides machine learning capabilities for analyzing court order documents:
1. Classification of orders as ADJOURNED, HEARD & ADJOURNED, or DISPOSED OFF
2. Entity extraction for petitioners, respondents, AGP names, and dates
3. Integration with existing ML-enhanced parser infrastructure
4. Rule-based extraction tailored to Bombay High Court order documents

Author: Billingonaire Legal Billing System
Date: September 2025
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Basic libraries
try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore[assignment]

# Firebase imports
from firebase_admin import firestore

# Import existing ML parser for base functionality
from ml_enhanced_parser import MLEnhancedParser


@dataclass
class CaseInfo:
    """Information about a single case within an order - simplified structure"""

    case_type: str = ""
    case_number: Optional[Any] = None
    case_year: Optional[Any] = None
    petitioner: str = ""
    respondent: str = ""
    government_pleader: List[str] = field(default_factory=list)
    petitioners: List[str] = field(default_factory=list)
    respondents: List[str] = field(default_factory=list)
    agp_names: List[str] = field(default_factory=list)
    advocates: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.petitioners and self.petitioner:
            self.petitioners = [self.petitioner]
        if not self.respondents and self.respondent:
            self.respondents = [self.respondent]
        if not self.petitioner and self.petitioners:
            self.petitioner = self.petitioners[0]
        if not self.respondent and self.respondents:
            self.respondent = self.respondents[0]
        if not self.government_pleader and self.agp_names:
            self.government_pleader = list(self.agp_names)
        if not self.agp_names and self.government_pleader:
            self.agp_names = list(self.government_pleader)


@dataclass
class OrderAnalysisResult:
    """Result from order document analysis - simplified structure"""

    order_category: str  # ADJOURNED, HEARD_AND_ADJOURNED, DISPOSED_OFF
    category_confidence: float
    order_date: Optional[str]  # Specific date of the order
    cases: List[CaseInfo]  # Multiple cases can be clubbed together
    order_text: str
    analysis_metadata: Dict[str, Any]


class OrderDocumentAnalyzer:
    """
    Specialized analyzer for court order documents
    Extends ML-enhanced parser for order-specific analysis
    """

    def __init__(self):
        """Initialize Order Document Analyzer"""
        self.db = firestore.client()
        self.ml_parser = MLEnhancedParser()
        self.order_patterns = self._create_order_patterns()
        self.entity_patterns = self._create_entity_patterns()
        self.date_patterns = self._create_date_patterns()
        # Pre-compile pattern lists once to avoid per-call overhead.
        self._compiled_no_time = [
            re.compile(p, re.IGNORECASE) for p in self.NO_TIME_PATTERNS
        ]
        self._compiled_strong_disposal = [
            re.compile(p, re.IGNORECASE) for p in self.STRONG_DISPOSAL_PATTERNS
        ]
        # Build an explicit per-pattern weight map.  Keyed by the exact pattern
        # string so lookups are O(1) and immune to substring-matching bugs.
        self._pattern_weights = self._build_pattern_weights()

        logging.info("Order Document Analyzer initialized successfully")

    def _create_order_patterns(self) -> Dict[str, List[str]]:
        """Create patterns for order classification."""
        return {
            "DISPOSED_OFF": [
                r"\bdisposed?\s+off?\b",
                r"\bdisposal\b",
                r"\binfructuous\b",
                # Withdrawal patterns — only match when petition is actually/formally
                # withdrawn (past tense), not when a petitioner merely "seeks to withdraw".
                r"\bpetition(?:s)?\s+(?:is\s+|are\s+)?withdrawn?\b",
                r"\bwrit\s+petition(?:s)?\s+(?:is\s+|are\s+)?withdrawn?\b",
                r"\ballowed?\s+and\s+disposed?\s+off?\b",
                r"\bfinal\s+disposal\b",
                r"\bpetitions?\s+(?:are\s+)?disposed?\s+off?\b",
                r"\bmatter\s+(?:is\s+)?disposed?\s+off?\b",
                r"\bcase\s+(?:is\s+)?disposed?\s+off?\b",
                # "final judgment" is specific enough; "final order" is too broad
                # (appears in compliance contexts: "in compliance of the final order")
                r"\bfinal\s+judgment\b",
                r"\bsuit\s+(?:is\s+)?dismissed?\b",
                r"\bpetition\s+(?:is\s+)?dismissed?\b",
                r"\bwrit\s+(?:is\s+)?dismissed?\b",
                # Standalone \bdismissed?\b removed — it fires on "application for time
                # dismissed" inside an otherwise ADJOURNED order.
                # Keep petition/writ/suit dismissed patterns above.
                # "petition is granted" removed — too broad; fires on "interim relief
                # in the petition is granted" which is HEARD_AND_ADJOURNED, not disposal.
                r"\bwrit\s+(?:is\s+)?allowed\b",
                r"\bwrit\s+petition\s+(?:is\s+)?allowed\b",
                r"\brule\s+(?:is\s+)?made\s+absolute\b",
                r"\bconclusion\b.*?\bdisposed\b",
                r"\bpassed?\s+(?:the\s+)?(?:following\s+)?order\b.*?\bdisposed\b",
                r"\baccordingly\b.*?\bdisposed\b",
                r"\bhence\b.*?\bdisposed\b",
                # "stands closed" variant covers "contempt stands closed"
                r"\bcontempt\s+(?:case\s+|petition\s+)?(?:(?:is|stands?)\s+)?closed\b",
                r"\bmatter\s+(?:is\s+)?finally\s+closed\b",
                # Broad "case/matter closed" patterns removed — "case is closed for
                # arguments" is not a disposal.
            ],
            "ADJOURNED": [
                r"\bstands?\s+over\s+to\b",
                r"\badjourned?\s+to\b",
                r"\blist(?:ed)?\s+(?:the\s+same\s+)?on\b",
                r"\bnext\s+(?:date|hearing)\s+(?:of|on)\b",
                r"\bpost(?:poned?)?\s+to\b",
                r"\breschedule[d]?\s+(?:to|for)\b",
                r"\bdeferred?\s+to\b",
                r"\bwrongly\s+on\s+board\b",
                r"\bremove\s+from\s+(?:the\s+)?board\b",
                r"\bpaucity\s+of\s+time\b",
                r"\bcould\s+not\s+be\s+taken\s+up\b",
                r"\btime\s+(?:sought|requested)\b",
                r"\bseeks?\s+time\b",
                r"\btake\s+instructions\b",
                r"\bto\s+be\s+listed\s+on\b",
                r"\bfor\s+(?:final\s+)?hearing\s+(?:at|on)\b",
                r"\bnext\s+date\s+(?:is\s+)?fixed\b",
                r"\binterim\s+order.*?to\s+continue\b",
            ],
            "HEARD_AND_ADJOURNED": [
                r"\bheard?\s+and\s+adjourned?\b",
                r"\bpartly\s+heard?\b",
                r"\bpartial\s+hearing\b",
                r"\bheard?\s+partially\b",
                r"\barguments?\s+(?:heard?|concluded?)\s+(?:and\s+)?adjourned?\b",
                r"\bafter\s+hearing.*?adjourned?\b",
                r"\bmatter\s+heard?\s+and\s+(?:kept\s+for|posted\s+to)\b",
                r"\bheard?\s+(?:the\s+)?(?:parties?|counsel)\s+and\s+adjourned?\b",
                r"\bon\s+hearing\b",
                r"\bupon\s+hearing\b",
                r"\bhaving\s+heard?\b",
                r"\bafter\s+hearing\s+(?:the\s+)?(?:learned\s+)?(?:counsel|counsels?|advocates?)\b",
                r"\bafter\s+hearing\s+(?:learned\s+)?(?:counsel|advocate)\s+for\s+(?:the\s+)?(?:petitioner|respondent)\b",
                r"\b(?:learned\s+)?counsel.*?submits?\b",
                r"\b(?:learned\s+)?counsel.*?(?:appear(?:s|ed|ing)?)\b",
                r"\b(?:learned\s+)?counsel\s+for.*?(?:submits?|states?|argues?)\b",
                r"\b(?:learned\s+)?(?:AGP|APP)\s+(?:submits?|states?|appear(?:s|ed|ing)?|confirms?)\b",
                r"\b(?:AGP|APP).*?(?:appear(?:s|ed|ing)?|submits?|states?|confirms?)\b",
                r"\bappear(?:s|ed|ing)?\s+(?:as\s+)?(?:AGP|APP)\b",
                r"\b(?:submissions?|arguments?)\s+(?:made|advanced|put\s+forth)\b",
                r"\bcourt.*?observes?\s+that\b",
                r"\b(?:having\s+)?perused\s+(?:the\s+)?(?:papers?|records?|pleadings?)\b",
                r"\bconsidering\s+(?:the\s+)?submissions?\b",
                r"\bin\s+view\s+of\s+(?:the\s+)?(?:above|submissions?)\b",
                r"\blist(?:ed)?\s+(?:the\s+same\s+)?on.*?for.*?(?:final\s+)?hearing\b",
                r"\bproceedings\s+are\s+pending.*?list.*?for.*?hearing\b",
                r"\bmatter[s]?\s+(?:would\s+be\s+)?called\s+out.*?after\b",
                r"\bConsidering\s+that.*?pending.*?(?:final\s+)?hearing\b",
                r"\badmission\s+stage.*?after.*?board\b",
                # Court-directive patterns — when the court issues substantive orders
                # (directions, affidavit filings, deprecations) the matter was heard.
                r"\bwe\s+(?:hereby\s+)?direct\b",
                r"\bcourt\s+directs?\b",
                r"\bdirected?\s+to\s+(?:file|place|communicate|submit|issue|produce|swear|take|pay)\b",
                r"\baffidavit\s+(?:to\s+be|be)\s+(?:filed|sworn|duly\s+sworn|placed)\b",
                r"\bdeprecated?\s+in\s+strong\s+words\b",
                r"\bcorrective\s+instructions?\b",
                r"\bpursuant\s+to\s+(?:the\s+)?(?:compliance|aforesaid|above|order)\b",
                r"\bconduct\s+of\s+(?:the\s+)?(?:officials?|committee|department)\b",
                # "heard, stand over to [date]" — matter was heard then adjourned
                r"\bheard\s*[,.]?\s*(?:and\s+)?stands?\s+over\b",
                # Notice-issuance phrases — court heard petitioner and issued notice
                r"\bissue\s+notice\b",
                r"\bnotice\s+(?:be\s+)?(?:issued|returnable)\b",
                # Interim relief / stay granted — matter was heard, interim order passed
                r"\binterim\s+(?:relief|stay|injunction)\s+(?:as\s+prayed\s+)?(?:is\s+)?granted\b",
            ],
        }

    def _build_pattern_weights(self) -> Dict[str, float]:
        """Return a mapping from every pattern string to its scoring weight.

        Using an explicit map avoids the brittle substring-on-regex-text approach
        that previously caused directive patterns to be mis-weighted.
        Patterns not listed here default to 1.0.
        """
        weights: Dict[str, float] = {}

        # --- DISPOSED_OFF weights -------------------------------------------
        for p in [
            r"\bdisposed?\s+off?\b",
            r"\bdisposal\b",
            r"\ballowed?\s+and\s+disposed?\s+off?\b",
            r"\bfinal\s+disposal\b",
            r"\bpetitions?\s+(?:are\s+)?disposed?\s+off?\b",
            r"\bmatter\s+(?:is\s+)?disposed?\s+off?\b",
            r"\bcase\s+(?:is\s+)?disposed?\s+off?\b",
            r"\bconclusion\b.*?\bdisposed\b",
            r"\bpassed?\s+(?:the\s+)?(?:following\s+)?order\b.*?\bdisposed\b",
            r"\baccordingly\b.*?\bdisposed\b",
            r"\bhence\b.*?\bdisposed\b",
        ]:
            weights[p] = 2.5  # Disposal is definitive

        for p in [
            r"\binfructuous\b",
            r"\bpetition(?:s)?\s+(?:is\s+|are\s+)?withdrawn?\b",
            r"\bwrit\s+petition(?:s)?\s+(?:is\s+|are\s+)?withdrawn?\b",
            r"\bfinal\s+judgment\b",
            r"\bsuit\s+(?:is\s+)?dismissed?\b",
            r"\bpetition\s+(?:is\s+)?dismissed?\b",
            r"\bwrit\s+(?:is\s+)?dismissed?\b",
            r"\bwrit\s+(?:is\s+)?allowed\b",
            r"\bwrit\s+petition\s+(?:is\s+)?allowed\b",
            r"\brule\s+(?:is\s+)?made\s+absolute\b",
            # updated pattern key (now includes "stands?" variant)
            r"\bcontempt\s+(?:case\s+|petition\s+)?(?:(?:is|stands?)\s+)?closed\b",
            r"\bmatter\s+(?:is\s+)?finally\s+closed\b",
        ]:
            weights[p] = 2.0

        # --- ADJOURNED weights ----------------------------------------------
        for p in [
            r"\bstands?\s+over\s+to\b",
            r"\binterim\s+order.*?to\s+continue\b",
        ]:
            weights[p] = 1.5  # "stand over" is a reliable adjournment signal

        # All other ADJOURNED patterns keep the default weight of 1.0

        # --- HEARD_AND_ADJOURNED weights ------------------------------------
        # Very strong hearing indicators
        for p in [
            r"\bheard?\s+and\s+adjourned?\b",
            r"\bon\s+hearing\b",
            r"\bupon\s+hearing\b",
            r"\bhaving\s+heard?\b",
            r"\bwe\s+(?:hereby\s+)?direct\b",
            r"\bcourt\s+directs?\b",
            r"\bdirected?\s+to\s+(?:file|place|communicate|submit|issue|produce|swear|take|pay)\b",
        ]:
            weights[p] = 2.5

        # Strong hearing indicators
        for p in [
            r"\bpartly\s+heard?\b",
            r"\bpartial\s+hearing\b",
            r"\bheard?\s+partially\b",
            r"\barguments?\s+(?:heard?|concluded?)\s+(?:and\s+)?adjourned?\b",
            r"\bafter\s+hearing.*?adjourned?\b",
            r"\bmatter\s+heard?\s+and\s+(?:kept\s+for|posted\s+to)\b",
            r"\bheard?\s+(?:the\s+)?(?:parties?|counsel)\s+and\s+adjourned?\b",
            r"\bafter\s+hearing\s+(?:the\s+)?(?:learned\s+)?(?:counsel|counsels?|advocates?)\b",
            r"\bafter\s+hearing\s+(?:learned\s+)?(?:counsel|advocate)\s+for\s+(?:the\s+)?(?:petitioner|respondent)\b",
            r"\b(?:learned\s+)?counsel.*?submits?\b",
            r"\b(?:learned\s+)?counsel.*?(?:appear(?:s|ed|ing)?)\b",
            r"\b(?:learned\s+)?counsel\s+for.*?(?:submits?|states?|argues?)\b",
            r"\b(?:learned\s+)?(?:AGP|APP)\s+(?:submits?|states?|appear(?:s|ed|ing)?|confirms?)\b",
            r"\b(?:AGP|APP).*?(?:appear(?:s|ed|ing)?|submits?|states?|confirms?)\b",
            r"\bappear(?:s|ed|ing)?\s+(?:as\s+)?(?:AGP|APP)\b",
            r"\b(?:submissions?|arguments?)\s+(?:made|advanced|put\s+forth)\b",
            r"\baffidavit\s+(?:to\s+be|be)\s+(?:filed|sworn|duly\s+sworn|placed)\b",
            r"\bdeprecated?\s+in\s+strong\s+words\b",
            r"\bcorrective\s+instructions?\b",
            r"\bpursuant\s+to\s+(?:the\s+)?(?:compliance|aforesaid|above|order)\b",
        ]:
            weights[p] = 2.0

        # Moderate hearing indicators
        for p in [
            r"\bcourt.*?observes?\s+that\b",
            r"\b(?:having\s+)?perused\s+(?:the\s+)?(?:papers?|records?|pleadings?)\b",
            r"\bconsidering\s+(?:the\s+)?submissions?\b",
            r"\bin\s+view\s+of\s+(?:the\s+)?(?:above|submissions?)\b",
            r"\bconduct\s+of\s+(?:the\s+)?(?:officials?|committee|department)\b",
        ]:
            weights[p] = 1.8

        for p in [
            r"\blist(?:ed)?\s+(?:the\s+same\s+)?on.*?for.*?(?:final\s+)?hearing\b",
            r"\bproceedings\s+are\s+pending.*?list.*?for.*?hearing\b",
            r"\bmatter[s]?\s+(?:would\s+be\s+)?called\s+out.*?after\b",
            r"\bConsidering\s+that.*?pending.*?(?:final\s+)?hearing\b",
            r"\badmission\s+stage.*?after.*?board\b",
        ]:
            weights[p] = 1.5

        # New strong HEARD_AND_ADJOURNED indicators
        for p in [
            r"\bheard\s*[,.]?\s*(?:and\s+)?stands?\s+over\b",
            r"\bissue\s+notice\b",
            r"\bnotice\s+(?:be\s+)?(?:issued|returnable)\b",
            r"\binterim\s+(?:relief|stay|injunction)\s+(?:as\s+prayed\s+)?(?:is\s+)?granted\b",
        ]:
            weights[p] = 2.5

        return weights

    def _create_entity_patterns(self) -> Dict[str, List[str]]:
        """Create patterns for entity extraction."""
        return {
            "PETITIONER": [
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+?(?:\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Petitioners?",
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+?(?:\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Applicants?",
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+?(?:\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Appellants?",
                r"([A-Z][a-zA-Z\.]+(?:\s+[A-Z][a-zA-Z\.]+)+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Petitioners?",
                r"([A-Z][a-zA-Z\.]+(?:\s+[A-Z][a-zA-Z\.]+)+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Applicants?",
                r"Petitioners?\s*:\s*((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)",
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s+vs?\.|\s+versus)",
                r"^((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+?)$\s*(?:Petitioner|Applicant)",
                r"In\s+the\s+matter\s+of\s*:?\s*((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+)",
                r"^([A-Z][a-zA-Z\.]+(?:\s+[A-Z][a-zA-Z\.]+)+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)\s*\.{2,}\s*Petitioners?",
            ],
            "RESPONDENT": [
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?|The\s+)?[A-Z][a-zA-Z\s\.]+?(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?(?=\s|$)",
                r"((?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?)\s+[A-Z][a-zA-Z\s\.]+?(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Defendants?",
                r"(?:versus|vs\.?)\s+([A-Z][a-zA-Z\s]+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?",
                r"(The\s+State\s+Of\s+Maharashtra(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?",
                r"(State\s+Of\s+Maharashtra(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?",
                r"(State\s+of\s+Maharashtra(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?",
                r"The\s+State\s+Of\s+Maharashtra.*?(?=\s*\.{2,}\s*Respondents?)",
                r"(?:vs?\.|\bversus\b)\s+((?:The\s+)?(?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?|State)?\s*[A-Z][a-zA-Z\s\.]+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)(?:\s*\.{2,}\s*)?\.{2,}\s*Respondents?",
                r"Respondents?\s*:\s*((?:The\s+)?[A-Z][a-zA-Z\s\.]+(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)",
                r"^((?:The\s+)?(?:Shri?\.?|Smt\.?|Ms\.?|Mr\.?|State)\s+[A-Z][a-zA-Z\s\.]+?)$\s*(?:Respondent|Defendant)",
                r"^(State\s+of\s+Maharashtra(?:\s+&\s+Ors\.?|\s+And\s+Ors\.?)?)\s*\.{2,}\s*Respondents?",
            ],
            "AGP_ENHANCED": [
                r"((?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?)\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+(?:\s+[A-Za-z]+)?)\s*,?\s*(?:Addl\.?\s*)?(?:AGP|A\.?\s*G\.?\s*P\.?)",
                r"((?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?)\s+[A-Z][a-zA-Z]+(?:\s+[A-Z]\.?)?\s+[A-Za-z]+)\s*,?\s*(?:AGP|A\.?\s*G\.?\s*P\.?)",
                r"\b([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+(?:\s+[A-Za-z]+)?)\s*,?\s*(?:Addl\.?\s*)?(?:AGP|A\.?\s*G\.?\s*P\.?)(?!\s*(?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?))",
                r"((?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?)\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+(?:\s+[A-Za-z]+)?)\s*,?\s*(?:Addl\.?\s*)?(?:GP|G\.?\s*P\.?)",
                r"\b([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+(?:\s+[A-Za-z]+)?)\s*,?\s*(?:Addl\.?\s*)?(?:GP|G\.?\s*P\.?)(?!\s*(?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?))",
                r"((?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?)\s+[A-Z][a-zA-Z\s\.]+?)\s+for\s+(?:the\s+)?State",
                r"((?:Smt\.?|Shri?\.?|Ms\.?|Mr\.?|Adv\.?)\s+[A-Z][a-zA-Z\s\.]+?)\s+for\s+Respondent.*?State",
            ],
        }

    def _create_date_patterns(self) -> List[str]:
        """Create patterns for date extraction."""
        return [
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})\b",
            r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
            r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b",
            r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
            r"\bDATE\s*:\s*(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
            r"\bon\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
            r"\bto\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
            r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
            r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b",
        ]

    def analyze_order_document(
        self, filename: str, file_content: bytes
    ) -> OrderAnalysisResult:
        """Analyze an order document using the structured parser flow."""
        logging.info(f"Starting enhanced order document analysis for {filename}")

        extraction_result = self.ml_parser.enhance_pdf_extraction(
            filename, file_content
        )

        if not extraction_result or not extraction_result.text.strip():
            raise ValueError(f"Could not extract text from order document: {filename}")

        text = extraction_result.text
        document_structure = self._parse_document_structure(text)
        order_date = self._extract_order_date(text, document_structure)
        order_category, category_confidence = self._classify_order_enhanced(
            text, document_structure
        )
        cases = self._extract_structured_cases_simplified(
            document_structure, text, order_date
        )

        logging.info(
            "Enhanced order analysis completed. Category: %s, Cases: %s, Confidence: %.2f",
            order_category,
            len(cases),
            category_confidence,
        )
        return OrderAnalysisResult(
            order_category=order_category,
            category_confidence=category_confidence,
            order_date=order_date,
            cases=cases,
            order_text=text,
            analysis_metadata={
                "primary_category_confidence": category_confidence,
                "extraction_quality_score": extraction_result.quality_score,
                "extraction_confidence": extraction_result.confidence,
            },
        )

    def get_fallback_metrics(self) -> Dict[str, int]:
        """LLM fallback metrics are retired and kept empty for compatibility."""
        return {}

    # High-confidence disposal patterns that unambiguously signal a final order.
    # Phrases that unambiguously mean no hearing took place.  Any match short-
    # circuits the ML scorer and returns ADJOURNED with high confidence.
    # "stand over" is NOT here — it also appears in "heard, stand over to [date]"
    # (HEARD_AND_ADJOURNED) so it cannot be a hard gate.
    NO_TIME_PATTERNS: List[str] = [
        r"\bpaucity\s+of\s+time\b",
        r"\bwant\s+of\s+time\b",
    ]

    # Only these patterns trigger the absolute DISPOSED_OFF priority; weaker
    # patterns (e.g. standalone "dismissed") participate in score comparison only.
    # Defined as a class constant and pre-compiled in __init__ for performance.
    STRONG_DISPOSAL_PATTERNS: List[str] = [
        r"\bdisposed?\s+off?\b",
        r"\binfructuous\b",
        r"\ballowed?\s+and\s+disposed?\s+off?\b",
        r"\bpetitions?\s+(?:are\s+)?disposed?\s+off?\b",
        r"\bmatter\s+(?:is\s+)?disposed?\s+off?\b",
        r"\bcase\s+(?:is\s+)?disposed?\s+off?\b",
        r"\baccordingly\b.*?\bdisposed\b",
        r"\bhence\b.*?\bdisposed\b",
        r"\bconclusion\b.*?\bdisposed\b",
        r"\bpassed?\s+(?:the\s+)?(?:following\s+)?order\b.*?\bdisposed\b",
        r"\bsuit\s+(?:is\s+)?dismissed?\b",
        r"\bpetition\s+(?:is\s+)?dismissed?\b",
        r"\bwrit\s+(?:is\s+)?dismissed?\b",
        r"\bwrit\s+petition\s+(?:is\s+)?allowed\b",
        r"\bwrit\s+(?:is\s+)?allowed\b",
        r"\bfinal\s+disposal\b",
        r"\bfinal\s+judgment\b",
        r"\brule\s+(?:is\s+)?made\s+absolute\b",
    ]

    def _classify_order(self, text: str) -> Tuple[str, float]:
        """Classify order into categories with confidence score"""
        scores: Dict[str, Dict[str, float]] = {}
        logging.info(f"🔍 Classifying order text (length: {len(text)} chars)")

        for category, patterns in self.order_patterns.items():
            score = 0.0
            matches = 0
            matched_patterns = []

            for pattern in patterns:
                regex_matches = re.findall(pattern, text, re.IGNORECASE)
                if regex_matches:
                    matches += len(regex_matches)
                    matched_patterns.append(
                        pattern[:50]
                    )  # Log first 50 chars of pattern
                    # Look up the pre-defined weight; default to 1.0 for any
                    # pattern not explicitly listed (e.g. future additions).
                    weight = self._pattern_weights.get(pattern, 1.0)
                    score += len(regex_matches) * weight

            scores[category] = {
                "score": score,
                "matches": matches,
                "confidence": min(score / 10.0, 1.0),  # Normalize to 0-1
            }

            # Log category results
            if matched_patterns:
                logging.info(
                    f"  📊 {category}: score={score:.2f}, matches={matches}, patterns={matched_patterns[:3]}"
                )
            elif category == "DISPOSED_OFF":
                # Always log disposal check even if no matches
                logging.info(f"  ❌ {category}: No disposal patterns found")

        # Determine best category with enhanced logic
        if not any(scores[cat]["score"] > 0 for cat in scores):
            logging.warning("⚠️ No patterns matched - defaulting to ADJOURNED")
            return "ADJOURNED", 0.5  # Default assumption

        # CRITICAL: Give absolute priority to DISPOSED_OFF only when a strong,
        # high-confidence disposal pattern matches.  Weak patterns (e.g. standalone
        # "dismissed" from an IA dismissal, or "relief is granted" for interim
        # relief) should not override clear ADJOURNED/HEARD_AND_ADJOURNED evidence.
        has_strong_disposal = any(
            p.search(text) for p in self._compiled_strong_disposal
        )
        if has_strong_disposal:
            best_category = "DISPOSED_OFF"
            confidence = scores["DISPOSED_OFF"]["confidence"]
            # Boost confidence for disposal - it's definitive
            confidence = min(confidence * 1.3, 1.0)
            logging.info(
                f"✅ FINAL DECISION: {best_category} (confidence={confidence:.2f}) - STRONG DISPOSAL DETECTED"
            )
            return best_category, confidence

        # Enhanced category selection logic for non-disposal cases
        best_category = max(scores.keys(), key=lambda x: scores[x]["score"])
        confidence = scores[best_category]["confidence"]

        # CRITICAL: Check for non-hearing adjournments (no actual hearing took place)
        # Patterns indicating no hearing occurred
        no_hearing_patterns = [
            r"Balance\s+Daily\s+Board\s+cannot\s+be\s+taken\s+up",
            r"paucity\s+of\s+time",
            r"cannot\s+be\s+taken\s+up\s+today",
            r"no\s+time\s+available",
            r"matter\s+not\s+reached",
            r"insufficient\s+time",
        ]

        is_non_hearing_adjournment = any(
            re.search(pattern, text, re.IGNORECASE) for pattern in no_hearing_patterns
        )

        # CRITICAL FIX: Prioritize HEARD_AND_ADJOURNED over ADJOURNED when both match
        # BUT: If it's clearly a non-hearing adjournment, stay with ADJOURNED
        if (
            scores.get("HEARD_AND_ADJOURNED", {}).get("score", 0) > 0
            and scores.get("ADJOURNED", {}).get("score", 0) > 0
            and not is_non_hearing_adjournment  # NEW: Check for non-hearing
        ):
            # If both categories have matches, prefer HEARD_AND_ADJOURNED aggressively
            heard_score = scores["HEARD_AND_ADJOURNED"]["score"]
            adj_score = scores["ADJOURNED"]["score"]

            # If HEARD_AND_ADJOURNED has at least 30% of ADJOURNED's score, prefer it
            # Very low threshold because hearing indicators are more significant
            if heard_score >= (adj_score * 0.3):
                best_category = "HEARD_AND_ADJOURNED"
                confidence = scores["HEARD_AND_ADJOURNED"]["confidence"]
                # Boost confidence for proper classification
                confidence = min(confidence * 1.4, 1.0)

        # Override to ADJOURNED if non-hearing detected
        if is_non_hearing_adjournment and best_category == "HEARD_AND_ADJOURNED":
            best_category = "ADJOURNED"
            confidence = scores.get("ADJOURNED", {}).get("confidence", 0.5)
            logging.info(
                "   🔄 Overriding to ADJOURNED - no hearing indicators detected"
            )

        # Boost confidence for clear indicators
        if (
            best_category == "HEARD_AND_ADJOURNED"
            and scores[best_category]["score"] >= 2
        ):
            confidence = min(confidence * 1.2, 1.0)

        logging.info(f"✅ FINAL DECISION: {best_category} (confidence={confidence:.2f})")
        return best_category, confidence

    def _parse_document_structure(self, text: str) -> Dict[str, Any]:
        """
        Parse the 4-part document structure:
        1. Case numbers
        2. Parties names
        3. Advocate names (AGP, ADDL GP, GP, AG)
        4. Date + Order text
        """
        structure = {
            "has_case_numbers": False,
            "has_parties": False,
            "has_advocates": False,
            "has_order_date": False,
            "case_numbers_section": "",
            "parties_section": "",
            "advocates_section": "",
            "order_section": "",
            "document_type": "UNKNOWN",
            "full_text": text,  # Include full text for case-specific extraction
        }

        lines = text.split("\n")
        current_section = "header"
        case_numbers_lines = []
        parties_lines = []
        advocates_lines = []
        order_lines = []

        # Patterns for section identification
        case_number_pattern = r"(?:WRIT\s+PETITION\s+NO\.|CRIMINAL\s+PETITION\s+NO\.|CIVIL\s+PETITION\s+NO\.|WP|PIL|CRLP|CRLWP|CRMPL|CP|APPWP|CPWP|APPPL)\s*[-\s]*\d+[-/\s]+OF\s+\d+|\b(?:WP|PIL|CRLP|CRLWP|CRMPL|CP|APPWP|CPWP|APPPL)\s*[-\s]*\d+[-/]\d+"
        parties_pattern = (
            r"\.{2,}.*?(?:Petitioner|Applicant|Appellant|Respondent|Defendant)"
        )
        advocate_pattern = (
            r"(?:Smt?\.?|Shri\.?|Ms\.?|Mr\.?)\s+[A-Z].*?(?:AGP|GP|ADDL\s*GP|AG)\b"
        )
        date_pattern = r"(?:DATE|CORAM|Before|Hon\'ble)\s*[:.]?\s*\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            # Detect case numbers
            if re.search(case_number_pattern, line, re.IGNORECASE):
                current_section = "case_numbers"
                structure["has_case_numbers"] = True
                case_numbers_lines.append(line)
            # Detect parties section
            elif re.search(parties_pattern, line, re.IGNORECASE):
                current_section = "parties"
                structure["has_parties"] = True
                parties_lines.append(line)
            # Detect advocates section
            elif re.search(advocate_pattern, line, re.IGNORECASE):
                current_section = "advocates"
                structure["has_advocates"] = True
                advocates_lines.append(line)
            # Detect order date/beginning of order
            elif re.search(date_pattern, line, re.IGNORECASE):
                current_section = "order"
                structure["has_order_date"] = True
                order_lines.append(line)
            else:
                # Continue adding to current section
                if current_section == "case_numbers":
                    case_numbers_lines.append(line)
                elif current_section == "parties":
                    parties_lines.append(line)
                elif current_section == "advocates":
                    advocates_lines.append(line)
                elif current_section == "order":
                    order_lines.append(line)

        # Populate structure
        structure["case_numbers_section"] = "\n".join(case_numbers_lines)
        structure["parties_section"] = "\n".join(parties_lines)
        structure["advocates_section"] = "\n".join(advocates_lines)
        structure["order_section"] = "\n".join(order_lines)

        # Determine document type based on completeness
        if (
            structure["has_case_numbers"]
            and structure["has_parties"]
            and structure["has_advocates"]
            and structure["has_order_date"]
        ):
            structure["document_type"] = "COMPLETE_ORDER"
        elif structure["has_order_date"] and not (
            structure["has_case_numbers"] and structure["has_parties"]
        ):
            structure["document_type"] = "ADJOURNMENT_ONLY"
        else:
            structure["document_type"] = "PARTIAL"

        return structure

    def _extract_structured_cases(
        self, document_structure: Dict[str, Any]
    ) -> List[CaseInfo]:
        """Extract case information with proper structure and associations"""
        cases = []

        if not document_structure["has_case_numbers"]:
            # No case numbers found, create single generic case
            case_info = CaseInfo(
                case_number=None,
                petitioners=[],
                respondents=[],
                agp_names=[],
                advocates=[],
            )

            # Extract what we can from parties section
            if document_structure["has_parties"]:
                petitioners, respondents = self._parse_parties_section(
                    document_structure["parties_section"]
                )
                case_info.petitioners = petitioners
                case_info.respondents = respondents

            # Extract advocates
            if document_structure["has_advocates"]:
                advocates, agp_names = self._parse_advocates_section(
                    document_structure["advocates_section"]
                )
                case_info.advocates = advocates
                case_info.agp_names = agp_names

            cases.append(case_info)
        else:
            # Extract case numbers and associate with parties/advocates
            case_numbers = self._extract_case_numbers(
                document_structure["case_numbers_section"]
            )

            if len(case_numbers) == 1:
                # Single case - straightforward mapping
                case_info = CaseInfo(
                    case_number=case_numbers[0],
                    petitioners=[],
                    respondents=[],
                    agp_names=[],
                    advocates=[],
                )

                # Extract parties for this case
                if document_structure["has_parties"]:
                    petitioners, respondents = self._parse_parties_section(
                        document_structure["parties_section"]
                    )
                    case_info.petitioners = petitioners
                    case_info.respondents = respondents

                # Extract advocates for this case
                if document_structure["has_advocates"]:
                    advocates, agp_names = self._parse_advocates_section(
                        document_structure["advocates_section"]
                    )
                    case_info.advocates = advocates
                    case_info.agp_names = agp_names

                cases.append(case_info)
            else:
                # Multiple cases - need to split and associate
                cases = self._associate_multiple_cases(case_numbers, document_structure)

        return cases

    def _parse_canonical_case_info(self, case_text: str) -> Dict[str, str]:
        """Parse case information into canonical format with robust pattern matching"""
        case_info = {"case_type": "", "case_number": "", "year": "", "canonical_id": ""}

        # Comprehensive patterns for different case formats
        patterns = [
            # "WRIT PETITION NO.11347 OF 2024" format
            r"(WRIT PETITION|CRIMINAL PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION)(?:\s+NO\.?)?\s*([0-9]+)\s+OF\s+([0-9]{4})",
            # "WP/11347/2024" or "WP-11347-2024" format
            r"(WP|PIL|CRLP|CRLWP|CRMPL|CP|APPWP|CPWP|APPPL)[\s\-/]+([0-9]+)[\s\-/]+([0-9]{4})",
            # "11347/2024" standalone format
            r"^([0-9]+)[/\-]([0-9]{4})$",
        ]

        for pattern in patterns:
            match = re.search(pattern, case_text.strip(), re.IGNORECASE)
            if match:
                if len(match.groups()) == 3:
                    case_type, number, year = match.groups()
                elif len(match.groups()) == 2:  # Standalone number/year format
                    number, year = match.groups()
                    case_type = "WP"  # Default type
                else:
                    continue

                # Normalize case type
                if case_type.upper() in [
                    "WRIT PETITION",
                    "CRIMINAL WRIT PETITION",
                    "CIVIL APPLICATION",
                ]:
                    case_info["case_type"] = case_type.upper()
                else:
                    case_info["case_type"] = case_type.upper()

                case_info["case_number"] = number
                case_info["year"] = year
                case_info["canonical_id"] = f"{number}/{year}"
                break

        return case_info

    def _extract_tabular_data(
        self, text: str, order_category: str, order_date: str
    ) -> List[Dict[str, str]]:
        """Extract data in tabular format: Case Type, Case Number, Year, Date, Petitioner, Respondent, AGP/GP/Addl GP/B'Pnl, Category"""
        tabular_data = []
        seen_canonical_ids = set()  # For de-duplication

        # Get case-specific mappings
        case_agp_mapping = self._extract_case_specific_agps(text)
        case_parties_mapping = self._extract_case_specific_parties(text)
        raw_case_numbers = self._extract_case_numbers(text)

        for raw_case in raw_case_numbers:
            # Parse using canonical parser
            case_info = self._parse_canonical_case_info(raw_case)

            # Skip if parsing failed or already seen
            if (
                not case_info["canonical_id"]
                or case_info["canonical_id"] in seen_canonical_ids
            ):
                continue

            seen_canonical_ids.add(case_info["canonical_id"])

            # Get petitioner and respondent using canonical ID
            canonical_id = case_info["canonical_id"]
            petitioner = ""
            respondent = ""

            if canonical_id in case_parties_mapping:
                petitioners = case_parties_mapping[canonical_id].get("petitioners", [])
                respondents = case_parties_mapping[canonical_id].get("respondents", [])
                petitioner = petitioners[0] if petitioners else ""
                respondent = respondents[0] if respondents else ""

            # Get AGP/GP names using canonical ID
            agp_names = []
            if canonical_id in case_agp_mapping:
                for agp_info in case_agp_mapping[canonical_id]:
                    agp_names.append(f"{agp_info['name']} ({agp_info['role']})")

            # Fallback: If no case-specific AGPs found, extract general AGPs from text
            if not agp_names:
                general_agps = self._extract_general_agps(text)
                agp_names = [f"{name} ({role})" for name, role in general_agps]

            agp_string = ", ".join(agp_names) if agp_names else ""

            # Create tabular row with properly parsed data
            row = {
                "case_type": case_info["case_type"],
                "case_number": case_info["case_number"],
                "year": case_info["year"],
                "date": order_date or "",
                "petitioner": petitioner,
                "respondent": respondent,
                "agp_gp_addl_gp_bpnl": agp_string,
                "category": order_category,
            }

            tabular_data.append(row)

        return tabular_data

    def _extract_case_numbers(self, text: str) -> List[str]:
        """Extract case numbers from text with enhanced pattern matching"""
        patterns = [
            # Pattern for "WRIT PETITION NO.11347 OF 2024" format
            r"((?:WRIT PETITION|CRIMINAL PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION)(?:\s+NO\.?)?\s*[0-9]+\s+OF\s+[0-9]+)",
            # Standard case format like "WP-11347-2024" or "WP/11347/2024"
            r"((?:WP|PIL|CRLP|CRLWP|CRMPL|CP|APPWP|CPWP|APPPL)\s*[-\s/]*\d+[-/]\d+)",
            # Case references in advocate assignments "WP/11347/2024"
            r"(?:in\s+)?(WP/[0-9]+/[0-9]+)",
        ]

        case_numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            case_numbers.extend(matches)

        # Clean, normalize and deduplicate
        normalized_cases = []
        for case in case_numbers:
            case = case.strip()
            if case and len(case) > 4:  # Filter out very short matches
                # For full case references like "CRIMINAL PETITION NO.363 OF 2025"
                # Convert to canonical format for parsing
                if " OF " in case.upper():
                    # Keep the full reference for parsing
                    normalized_cases.append(case)
                else:
                    # For other formats, normalize separators
                    case = re.sub(r"[-\s]+", "/", case)
                    normalized_cases.append(case)

        return list(set(normalized_cases))

    def _extract_case_specific_agps(self, text: str) -> Dict[str, List[Dict[str, str]]]:
        """Extract AGP/GP names with their case associations - ONLY State advocates"""
        case_agp_mapping: Dict[str, List[Dict[str, str]]] = {}

        # REFINED patterns - ONLY for State advocates (AGP/GP)
        patterns = [
            # Pattern 1: "Adv. P. P. Kakade, Addl. GP a/w M J. Deshpande, AGP for the Respondent State in WP/11347/2024"
            r"(?:Adv\.\s+|Ms\.\s+|Mr\.\s+)([^,]+),\s+((?:Addl\.\s+)?(?:AGP|GP))(?:\s+a/w\s+([^,]+),\s+((?:AGP|GP)))?\s+for\s+the\s+Respondent\s+State\s+in\s+(WP/[0-9]+/[0-9]+)",
            # Pattern 2: "Ms. Pooja Joshi Deshpande for Respondent Nos.3 to 5-State." (State advocates only)
            r"(?:Ms\.\s+|Mr\.\s+|Adv\.\s+)([A-Za-z\s\.]+?)\s+for\s+Respondent\s+Nos?\.([0-9\s,to\-]+)State",
            # Pattern 3: "AGP/GP for State" direct mentions
            r"(?:Ms\.\s+|Mr\.\s+|Adv\.\s+)([A-Za-z\s\.]+?),?\s+((?:Addl\.\s+)?(?:AGP|GP|A\.?\s*G\.?P\.?|G\.?\s*P\.?))\s+(?:for\s+)?(?:the\s+)?State",
            # Pattern 4: "State of Maharashtra" representatives
            r"(?:Ms\.\s+|Mr\.\s+|Adv\.\s+)([A-Za-z\s\.]+?)\s+for\s+(?:the\s+)?State\s+of\s+Maharashtra",
        ]

        # Try each pattern - ONLY extract State advocates
        for pattern_idx, pattern in enumerate(patterns):
            matches = re.findall(pattern, text, re.IGNORECASE)

            for match in matches:
                if pattern_idx == 0:
                    # Pattern 1: Full AGP format with case reference
                    advocate1, role1, advocate2, role2, case_num = match
                    # Normalize to "NNNN/YYYY" (same format as canonical_id in
                    # _parse_canonical_case_info) so the lookup at line 828 succeeds.
                    canonical_key = (
                        self._parse_canonical_case_info(case_num).get("canonical_id")
                        or case_num
                    )

                    if canonical_key not in case_agp_mapping:
                        case_agp_mapping[canonical_key] = []

                    # Add first advocate (State representative)
                    case_agp_mapping[canonical_key].append(
                        {
                            "name": advocate1.strip(),
                            "role": role1.strip(),
                            "case_number": case_num,
                        }
                    )

                    # Add second advocate if present (State representative)
                    if advocate2 and advocate2.strip():
                        case_agp_mapping[canonical_key].append(
                            {
                                "name": advocate2.strip(),
                                "role": role2.strip() if role2 else "AGP",
                                "case_number": case_num,
                            }
                        )

                elif pattern_idx == 1:
                    # Pattern 2: State advocate (Respondent Nos.X-State)
                    advocate_name, respondent_nos = match
                    # Apply this to all cases since it mentions "State"
                    for case_num in self._extract_all_case_numbers(text):
                        canonical_case = self._parse_canonical_case_info(case_num)[
                            "canonical_id"
                        ]
                        if canonical_case and canonical_case not in case_agp_mapping:
                            case_agp_mapping[canonical_case] = []
                        if canonical_case:
                            case_agp_mapping[canonical_case].append(
                                {
                                    "name": advocate_name.strip(),
                                    "role": "GP (State)",
                                    "case_number": canonical_case,
                                }
                            )

                elif pattern_idx == 2:
                    # Pattern 3: Direct AGP/GP for State mentions
                    advocate_name, role = match
                    # Apply to all cases
                    for case_num in self._extract_all_case_numbers(text):
                        canonical_case = self._parse_canonical_case_info(case_num)[
                            "canonical_id"
                        ]
                        if canonical_case and canonical_case not in case_agp_mapping:
                            case_agp_mapping[canonical_case] = []
                        if canonical_case:
                            case_agp_mapping[canonical_case].append(
                                {
                                    "name": advocate_name.strip(),
                                    "role": role.strip(),
                                    "case_number": canonical_case,
                                }
                            )

                elif pattern_idx == 3:
                    # Pattern 4: State of Maharashtra representatives
                    advocate_name = match
                    # Apply to all cases
                    for case_num in self._extract_all_case_numbers(text):
                        canonical_case = self._parse_canonical_case_info(case_num)[
                            "canonical_id"
                        ]
                        if canonical_case and canonical_case not in case_agp_mapping:
                            case_agp_mapping[canonical_case] = []
                        if canonical_case:
                            case_agp_mapping[canonical_case].append(
                                {
                                    "name": advocate_name.strip(),
                                    "role": "GP (State of Maharashtra)",
                                    "case_number": canonical_case,
                                }
                            )

        return case_agp_mapping

    def _extract_general_agps(self, text: str) -> List[Tuple[str, str]]:
        """Extract AGP/GP names from text without case associations"""
        agps = []

        # Split text on "and" to handle multiple advocates
        parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)

        for part in parts:
            # Pattern for individual advocate: Mr./Ms. Name, Role
            pattern = (
                r"(?:Mr\.|Ms\.|Adv\.)\s+([A-Z]\.\s*[A-Z]\.\s*[A-Za-z]+)\s*,\s*([^,\n]+)"
            )
            matches = re.findall(pattern, part, re.IGNORECASE)

            for match in matches:
                name, role_desc = match
                # Extract the role (AGP, GP, Addl. GP, etc.)
                role_match = re.search(
                    r"(?:Addl\.?\s*)?(?:AGP|G\.?\s*P\.?)", role_desc, re.IGNORECASE
                )
                if role_match:
                    role = role_match.group(0)
                    agps.append((name.strip(), role.strip()))

        return agps

    def _extract_all_case_numbers(self, text: str) -> List[str]:
        """Helper method to get all case numbers for AGP mapping"""
        patterns = [
            r"(?:WRIT PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION)(?:\s+NO\.?)?\s*([0-9]+\s+OF\s+[0-9]+)",
            r"((?:WP|PIL|CRLP|CRLWP|CRMPL|CP|APPWP|CPWP|APPPL)\s*[-\s/]*\d+[-/]\d+)",
            r"(?:in\s+)?(WP/[0-9]+/[0-9]+)",
        ]

        case_numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            case_numbers.extend(matches)

        # Clean and normalize
        normalized_cases = []
        for case in case_numbers:
            case = case.strip()
            if case and len(case) > 4:
                case = re.sub(r"\s+OF\s+", "/", case, flags=re.IGNORECASE)
                case = re.sub(r"[-\s]+", "/", case)
                normalized_cases.append(case)

        return list(set(normalized_cases))

    def _extract_case_specific_parties(
        self, text: str
    ) -> Dict[str, Dict[str, List[str]]]:
        """Extract petitioners and respondents with their case associations"""
        case_parties_mapping = {}

        # Enhanced pattern to match case blocks with parties - handles different case number formats
        case_block_pattern = r"((?:WRIT|CRIMINAL|CIVIL) PETITION NO\.\s*([0-9]+)\s+OF\s+([0-9]+))(.*?)(?=(?:WRIT PETITION NO\.|CRIMINAL PETITION NO\.|CIVIL PETITION NO\.|WITH|Mr\.\s+\w+\s+\w+\s+for|Ms\.\s+\w+\s+\w+\s+for|$))"

        matches = re.findall(case_block_pattern, text, re.DOTALL | re.IGNORECASE)

        for case_header, case_num, year, case_content in matches:
            canonical_case_num = f"{case_num}/{year}"

            # Enhanced petitioner extraction
            petitioner_pattern = r"((?:Shri?\.?|Smt\.?|Mr\.?|Ms\.?|Shree)\s+)?([A-Za-z][A-Za-z\s\.]+?)(?:\s+\.{2,}\s*(?:Petitioner|Applicant))"
            petitioner_match = re.search(
                petitioner_pattern, case_content, re.IGNORECASE
            )

            # Enhanced respondent extraction - look after "versus" pattern
            respondent_pattern = r"versus\s+(.*?)(?:\s+\.{2,}\s*(?:Respondent))"
            respondent_match = re.search(
                respondent_pattern, case_content, re.DOTALL | re.IGNORECASE
            )

            # If no respondent found with versus, try direct pattern
            if not respondent_match:
                respondent_pattern = r"((?:Shri?\.?|Smt\.?|Mr\.?|Ms\.?|The\s+State\s+Of|Shree)\s+[A-Za-z\s\.]+(?:\s+Through\s+[^\.]+)?(?:\s+And\s+Ors\.?)?)(?:\s+\.{2,}\s*(?:Respondent))"
                respondent_match = re.search(
                    respondent_pattern, case_content, re.IGNORECASE
                )

            # Extract petitioner and clean up
            petitioner = ""
            if petitioner_match:
                title = petitioner_match.group(1) or ""
                name = petitioner_match.group(2) or ""
                petitioner = (title + name).strip()

            # Extract and clean respondent
            respondent = ""
            if respondent_match:
                respondent_raw = respondent_match.group(1).strip()
                # Clean up the respondent text (remove extra whitespace, newlines)
                respondent = re.sub(r"\s+", " ", respondent_raw)
                # Remove any trailing dots before .. Respondents
                respondent = re.sub(r"\s*\.+\s*$", "", respondent)

            case_parties_mapping[canonical_case_num] = {
                "petitioners": [petitioner] if petitioner else [],
                "respondents": [respondent] if respondent else [],
            }

        # Also extract State information from advocates section
        state_pattern = r"for\s+Respondent\s+Nos?\.([0-9\s,and\-]+)State"
        state_matches = re.findall(state_pattern, text, re.IGNORECASE)
        if state_matches:
            state_info = f"Respondent Nos.{state_matches[0].strip()}-State"
            # Add state info to all cases as additional respondent
            for case_num in case_parties_mapping:
                if case_parties_mapping[case_num]["respondents"]:
                    case_parties_mapping[case_num]["respondents"].append(
                        f"The State Of Maharashtra ({state_info})"
                    )
                else:
                    case_parties_mapping[case_num]["respondents"] = [
                        f"The State Of Maharashtra ({state_info})"
                    ]

        return case_parties_mapping

    def _parse_parties_section(self, text: str) -> Tuple[List[str], List[str]]:
        """Parse parties section to extract petitioners and respondents"""
        petitioners = []
        respondents = []

        # Split by lines and process each
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for petitioner indicators
            if re.search(
                r"\.{3,}.*?(?:Petitioner|Applicant|Appellant)", line, re.IGNORECASE
            ):
                # Extract name before the dots
                name_match = re.match(r"([^.]+?)\.{3,}", line)
                if name_match:
                    name = name_match.group(1).strip()
                    if name and len(name) > 2:
                        petitioners.append(name)

            # Look for respondent indicators
            elif re.search(r"\.{3,}.*?(?:Respondent|Defendant)", line, re.IGNORECASE):
                # Extract name before the dots
                name_match = re.match(r"([^.]+?)\.{3,}", line)
                if name_match:
                    name = name_match.group(1).strip()
                    if name and len(name) > 2:
                        respondents.append(name)

        return petitioners, respondents

    def _parse_advocates_section(self, text: str) -> Tuple[List[str], List[str]]:
        """Parse advocates section to extract all advocates and specifically AGP names"""
        advocates = []
        agp_names = []

        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for advocate patterns
            advocate_match = re.search(
                r"((?:Smt?\.?|Shri\.?|Ms\.?|Mr\.?)\s+[A-Z][^,\n]+?)(?:\s*,?\s*(?:AGP|GP|ADDL\s*GP|AG))?",
                line,
                re.IGNORECASE,
            )
            if advocate_match:
                advocate_name = advocate_match.group(1).strip()
                advocates.append(advocate_name)

                # Check if this is an AGP/GP
                if re.search(r"\b(?:AGP|GP|ADDL\s*GP|AG)\b", line, re.IGNORECASE):
                    agp_names.append(advocate_name)

        return advocates, agp_names

    def _associate_multiple_cases(
        self, case_numbers: List[str], document_structure: Dict[str, Any]
    ) -> List[CaseInfo]:
        """Handle multiple cases clubbed together with case-specific AGP assignments"""
        cases = []

        # Extract full text from document structure for case-specific extraction
        full_text = document_structure.get("full_text", "")

        # Extract case-specific AGP/GP mappings
        case_agp_mapping: Dict[str, List[Dict[str, str]]] = (
            self._extract_case_specific_agps(full_text) if full_text else {}
        )
        case_parties_mapping: Dict[str, Dict[str, List[str]]] = (
            self._extract_case_specific_parties(full_text) if full_text else {}
        )

        # Extract common/fallback data
        common_petitioners: List[str] = []
        common_respondents: List[str] = []
        common_advocates: List[str] = []
        common_agp_names: List[str] = []

        if document_structure["has_parties"]:
            common_petitioners, common_respondents = self._parse_parties_section(
                document_structure["parties_section"]
            )

        if document_structure["has_advocates"]:
            common_advocates, common_agp_names = self._parse_advocates_section(
                document_structure["advocates_section"]
            )

        # Create case info for each case number
        for case_number in case_numbers:
            # Parse canonical case ID for lookup
            case_info_parsed = self._parse_canonical_case_info(case_number)
            canonical_id = case_info_parsed.get("canonical_id", "")

            # Try to get case-specific data first, fall back to common data
            petitioners = common_petitioners.copy()
            respondents = common_respondents.copy()
            agp_names_list = []

            # Get case-specific parties if available
            if canonical_id and canonical_id in case_parties_mapping:
                case_parties = case_parties_mapping[canonical_id]
                if case_parties.get("petitioners"):
                    petitioners = case_parties["petitioners"]
                if case_parties.get("respondents"):
                    respondents = case_parties["respondents"]

            # Get case-specific AGP names if available
            if canonical_id and canonical_id in case_agp_mapping:
                # Use case-specific AGP names
                for agp_info in case_agp_mapping[canonical_id]:
                    agp_names_list.append(agp_info["name"])
            else:
                # Fall back to common AGP names
                agp_names_list = list(common_agp_names)

            case_info = CaseInfo(
                case_number=case_number,
                petitioners=petitioners,
                respondents=respondents,
                agp_names=agp_names_list,  # Case-specific or fallback
                advocates=common_advocates.copy(),
            )
            cases.append(case_info)

        return cases

    def _extract_order_date(
        self, text: str, document_structure: Dict[str, Any]
    ) -> Optional[str]:
        """Extract the specific order date from the document and format as dd-mmm-yyyy"""
        # Try to search in order section first if available
        search_text = document_structure.get("order_section", "")

        # If no order section or empty, search entire text
        if not search_text:
            search_text = text

        # Look for date patterns - prioritize DATE: prefix but also search without it
        date_patterns = [
            # DATE: 24 JULY 2024 (most common format in court orders)
            r"DATE\s*[:.]?\s*(\d{1,2})(?:st|nd|rd|th)?\s+(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER),?\s+(\d{4})",
            # 24th July, 2024 or 24 July 2024
            r"(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
            # DD/MM/YYYY or DD-MM-YYYY
            r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
        ]

        for pattern in date_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                date_str = match.group().strip()
                formatted_date = self._format_date_dd_mmm_yyyy(date_str)
                if formatted_date:
                    return formatted_date

        return None

    def _format_date_dd_mmm_yyyy(self, date_str: str) -> Optional[str]:
        """Format date to YYYY-MM-DD format for validation (e.g., 2024-07-24)"""
        # Month name to number mapping
        month_to_num = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }

        # Try different date patterns
        patterns = [
            # "3rd February, 2025" or "DATE: 3rd February, 2025" or "24 JULY 2024"
            r"(?:DATE\s*[:.]?\s*)?(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
            # "3/2/2025" or "03-02-2025" format
            r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str, re.IGNORECASE)
            if match:
                if len(match.groups()) == 3:
                    day, month_or_num, year = match.groups()

                    # Check if month is a name or number
                    if month_or_num.lower() in month_to_num:
                        # Month name format - convert to YYYY-MM-DD
                        day_formatted = day.zfill(2)
                        month_num = month_to_num[month_or_num.lower()]
                        month_formatted = str(month_num).zfill(2)
                        return f"{year}-{month_formatted}-{day_formatted}"
                    else:
                        # Numeric format (assume month_or_num is month number)
                        try:
                            day_formatted = day.zfill(2)
                            month_num = int(month_or_num)
                            if 1 <= month_num <= 12:
                                month_formatted = str(month_num).zfill(2)
                                return f"{year}-{month_formatted}-{day_formatted}"
                        except ValueError:
                            continue

        # If no pattern matches, return None to indicate failure
        return None

    def _classify_order_enhanced(
        self, text: str, document_structure: Dict[str, Any]
    ) -> Tuple[str, float]:
        """Enhanced classification using document structure information"""

        # Gate: no-time phrases mean the matter was never heard → always ADJOURNED.
        # Checked before the ML scorer so scoring noise cannot override this.
        if any(p.search(text) for p in self._compiled_no_time):
            logging.info("⏱️ NO_TIME gate triggered — classifying as ADJOURNED")
            return "ADJOURNED", 0.95

        # For all document types, use the improved classification logic
        category, confidence = self._classify_order(text)

        # BUSINESS RULE: If AGP names are present AND text contains "stand over",
        # classify as HEARD_AND_ADJOURNED instead of ADJOURNED
        # This indicates the matter was heard (AGP appeared) even though just adjourned
        has_agp_names = bool(document_structure.get("advocates_section", "").strip())
        has_standover = bool(re.search(r"\bstand\s+over\b", text, re.IGNORECASE))

        if category == "ADJOURNED" and has_agp_names and has_standover:
            logging.info(
                "Overriding ADJOURNED to HEARD_AND_ADJOURNED: AGP present + Standover found"
            )
            category = "HEARD_AND_ADJOURNED"
            confidence = min(
                confidence * 1.2, 1.0
            )  # Boost confidence for this business rule match

        # Apply document-type-specific adjustments
        if document_structure["document_type"] == "ADJOURNMENT_ONLY":
            # For incomplete documents, check if we found hearing evidence despite missing structure
            if category == "HEARD_AND_ADJOURNED":
                # Keep HEARD_AND_ADJOURNED classification but adjust confidence
                confidence = min(
                    confidence * 0.9, 1.0
                )  # Slight reduction due to incomplete structure
            elif category == "ADJOURNED":
                # Standard adjournment for incomplete docs
                confidence = min(0.8 + (confidence * 0.2), 1.0)
            # For DISPOSED_OFF, keep as-is since disposal is definitive regardless of structure
        elif document_structure["document_type"] == "COMPLETE_ORDER":
            # Boost confidence for complete documents
            confidence = min(confidence * 1.15, 1.0)

        return category, confidence

    def _extract_structured_cases_simplified(
        self,
        document_structure: Dict[str, Any],
        full_text: str,
        order_date: Optional[str],
    ) -> List[CaseInfo]:
        """
        Extract case information in simplified format
        Each case has: case_type, case_number, case_year, petitioner, respondent, government_pleader[]
        """
        cases = []

        # Extract all case numbers from document
        case_numbers_text = document_structure.get("case_numbers_section", "")
        if not case_numbers_text:
            # Fallback to full text if no specific section
            case_numbers_text = full_text

        # Extract case-specific information mappings
        case_info_mapping = self._extract_multi_case_details(full_text)

        # If we found specific case mappings, use them
        if case_info_mapping:
            for case_key, case_data in case_info_mapping.items():
                case_info = CaseInfo(
                    case_type=case_data.get("case_type", ""),
                    case_number=case_data.get("case_number", 0),
                    case_year=case_data.get("case_year", 0),
                    petitioner=case_data.get("petitioner", ""),
                    respondent=case_data.get("respondent", ""),
                    government_pleader=case_data.get("government_pleader", []),
                )
                cases.append(case_info)
        else:
            # Fallback: Extract case numbers and try to match with parties/advocates
            extracted_cases = self._extract_case_numbers(case_numbers_text)

            for case_str in extracted_cases:
                parsed = self._parse_canonical_case_info(case_str)

                case_info = CaseInfo(
                    case_type=parsed.get("case_type", ""),
                    case_number=(
                        int(parsed.get("case_number", "0"))
                        if parsed.get("case_number", "").isdigit()
                        else 0
                    ),
                    case_year=(
                        int(parsed.get("year", "0"))
                        if parsed.get("year", "").isdigit()
                        else 0
                    ),
                    petitioner="",
                    respondent="",
                    government_pleader=[],
                )

                # Try to extract parties from full text
                petitioner, respondent = self._extract_parties_for_case(
                    full_text, parsed.get("canonical_id", "")
                )
                case_info.petitioner = petitioner
                case_info.respondent = respondent

                # Try to extract government pleader
                govt_pleaders = self._extract_govt_pleader_for_case(
                    full_text, parsed.get("canonical_id", "")
                )
                case_info.government_pleader = govt_pleaders

                cases.append(case_info)

        return cases

    def _extract_multi_case_details(self, text: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract details for multiple cases from order text
        Returns: {case_key: {case_type, case_number, case_year, petitioner, respondent, government_pleader}}
        """
        case_details = {}
        logging.info("🔍 Extracting multi-case details from order text")
        logging.info(f"  📄 FULL TEXT (first 800 chars): {text[:800]}")

        # First, filter out all "IN" references to avoid treating them as separate cases
        # Pattern to identify "IN" cases: "IN WP/8485/2007" or "IN WRIT PETITION NO.8485 OF 2007"
        in_pattern = r"IN\s+(?:WRIT PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION|CONTEMPT PETITION)(?:\s+NO\.?)?\s*([0-9]+)\s+OF\s+([0-9]{4})"
        in_matches = re.findall(in_pattern, text, re.IGNORECASE)
        in_cases = set(f"{num}/{year}" for num, year in in_matches)
        if in_cases:
            logging.info(
                f"  Found {len(in_cases)} IN case(s) (associated cases): {in_cases}"
            )

        # Simpler approach: Find all case headers, then extract text between them
        # Pattern to match case headers: "CONTEMPT PETITION NO.363 OF 2025" or "INTERIM APPLICATION (ST) NO. 21796 OF 2025"
        case_header_pattern = r"(WRIT PETITION|CRIMINAL WRIT PETITION|CIVIL APPLICATION|CONTEMPT PETITION|INTERIM APPLICATION\s*\(ST\))(?:\s+NO\.?)?\s*([0-9]+)\s+OF\s+([0-9]{4})"

        # Find all matches with their positions
        all_case_matches = []
        for match in re.finditer(case_header_pattern, text, re.IGNORECASE):
            case_type_full = match.group(1)
            case_number = match.group(2)
            case_year = match.group(3)
            start_pos = match.end()  # Start extracting after the case header

            # Skip if this is an "IN" case
            # Check if "IN " appears within 10 chars before this match
            before_text = text[max(0, match.start() - 10) : match.start()]
            if re.search(r"IN\s*$", before_text, re.IGNORECASE):
                logging.info(
                    f"  Skipping IN case: {case_type_full} {case_number}/{case_year}"
                )
                continue

            all_case_matches.append((case_type_full, case_number, case_year, start_pos))

        logging.info(
            f"  Found {len(all_case_matches)} main case block(s) in order text (excluding IN cases)"
        )

        # Extract text blocks for each case
        matches = []
        for i, (case_type_full, case_number, case_year, start_pos) in enumerate(
            all_case_matches
        ):
            # Determine end position: either start of next case or end of text
            if i + 1 < len(all_case_matches):
                end_pos = (
                    all_case_matches[i + 1][3] - 50
                )  # End 50 chars before next case header
            else:
                end_pos = len(text)  # Last case: go to end of text

            # Extract block text between cases
            block_text = text[start_pos:end_pos]
            matches.append((case_type_full, case_number, case_year, block_text))

        for case_type_full, case_number, year, block_text in matches:
            # Map case type to abbreviation
            case_type_map = {
                "WRIT PETITION": "WP",
                "CRIMINAL WRIT PETITION": "CWP",
                "CIVIL APPLICATION": "CA",
                "CONTEMPT PETITION": "CP",
                "INTERIM APPLICATION (ST)": "IA(ST)",
            }
            case_type = case_type_map.get(case_type_full.upper(), "WP")
            case_key = f"{case_type}/{case_number}/{year}"
            logging.info(f"  Processing case: {case_key} (type: {case_type_full})")
            logging.info(f"  📄 BLOCK TEXT (first 500 chars): {block_text[:500]}")

            # Enhanced petitioner extraction with multiple patterns
            # Support for: Alias names, "…Petitioner" separator, titles, compound names
            petitioner = ""

            # Pattern 1: Handle PDF format with "…Petitioner" or "...Petitioner" separator (split name)
            # Example: "Hemlata Kirtikumar Kakade Alias Hemlata …Petitioner Jagannath Veer"
            # This means the full name is "Hemlata Kirtikumar Kakade Alias Hemlata Jagannath Veer"
            # Also supports: "Bhimrao s/o Gangaramji …Petitioner"
            petitioner_pattern1 = r"([A-Z][a-zA-Z\s\.\-/]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s/]+?)?)(?:\s*(?:…\.{0,2}|\.{2,})\s*Petitioners?\.?\s+)([A-Z][a-zA-Z\s\.\-/]+?)\s*(?:Versus|V/s\.?|vs\.?)"
            pet_match1 = re.search(petitioner_pattern1, block_text, re.IGNORECASE)
            if pet_match1:
                # Combine parts before and after "…Petitioner" or "...Petitioner"
                part1 = pet_match1.group(1).strip()
                part2 = pet_match1.group(2).strip()
                petitioner = f"{part1} {part2}"
                logging.info(
                    f"    ✅ Petitioner Pattern 1 (Split by …/...Petitioner) matched: '{petitioner}'"
                )

            # Pattern 2: Handle "IN THE MATTER BETWEEN" format for IA cases
            # Example: "IN THE MATTER BETWEEN Kanhaiyalal Madhavji Thakkar …Petitioner"
            # Also supports: "Bhimrao s/o Gangaramji Chourpagar …Petitioner"
            if not petitioner:
                petitioner_pattern2 = r"IN\s+THE\s+MATTER\s+BETWEEN\s+([A-Z][a-zA-Z\s\.\-/]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+?)?)\s*(?:…\.{0,2}|\.{2,})\s*Petitioners?\.?"
                pet_match2 = re.search(petitioner_pattern2, block_text, re.IGNORECASE)
                if pet_match2:
                    petitioner = pet_match2.group(1).strip()
                    logging.info(
                        f"    ✅ Petitioner Pattern 2 (IN THE MATTER BETWEEN) matched: '{petitioner}'"
                    )

            # Pattern 3: Handle "Name …Petitioner Versus" format (name before separator, nothing after)
            # Example: "Sunil Shivaji Wagh …Petitioner Versus" or "Alvito Carvalho …Petitioner/Applicant Versus"
            # Also handles "...Petitioners" (three dots) variant and "V/s" (slash variant)
            if not petitioner:
                petitioner_pattern3 = r"([A-Z][a-zA-Z\s\.\-/&]+?(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+?)?)\s*(?:…\.{0,2}|\.{2,})\s*Petitioners?\.?(?:/Applicant|/Appellant)?\s+(?:Versus|V/s\.?|vs\.?)"
                pet_match3 = re.search(petitioner_pattern3, block_text, re.IGNORECASE)
                if pet_match3:
                    petitioner = pet_match3.group(1).strip()
                    logging.info(
                        f"    ✅ Petitioner Pattern 3 (Name …/...Petitioner Versus) matched: '{petitioner}'"
                    )

            # Pattern 4: Standard format before "Versus" (no separator)
            # Example: "Hemlata Kirtikumar Kakade Alias Hemlata Jagannath Veer Versus"
            # Also supports: "Bhimrao s/o Gangaramji Chourpagar Versus"
            if not petitioner:
                # Must be at least 3 words to avoid matching just "Petitioner Versus"
                petitioner_pattern4 = r"([A-Z][a-zA-Z]+(?:\s+[a-zA-Z\.\-/]+){2,}(?:\s+[Aa]lias\s+[A-Z][a-zA-Z\s\.\-/]+)?)\s+(?:Versus|V/s\.?|vs\.?)\s"
                pet_match4 = re.search(petitioner_pattern4, block_text, re.IGNORECASE)
                if pet_match4:
                    petitioner = pet_match4.group(1).strip()
                    logging.info(
                        f"    ✅ Petitioner Pattern 4 (Before Versus, no separator) matched: '{petitioner}'"
                    )

            # Pattern 5: Handle "Name ....PETITIONER V/S" format (uppercase, dots separator)
            # Example: "Manikrao Shankar Devkate ....PETITIONER V/S"
            if not petitioner:
                petitioner_pattern5 = (
                    r"([A-Z][a-zA-Z]+(?:\s+[a-zA-Z\.\-/]+){1,})\s+\.{2,}\s*PETITIONER"
                )
                pet_match5 = re.search(petitioner_pattern5, block_text)
                if pet_match5:
                    petitioner = pet_match5.group(1).strip()
                    logging.info(
                        f"    ✅ Petitioner Pattern 5 (....PETITIONER format) matched: '{petitioner}'"
                    )

            # Clean up petitioner name
            if petitioner:
                petitioner = re.sub(r"\s+", " ", petitioner).strip()
                # Remove trailing dots and labels
                petitioner = re.sub(r"\.{2,}.*$", "", petitioner).strip()
                petitioner = re.sub(
                    r"\s*\.{2,}\s*PETITIONER.*$", "", petitioner, flags=re.IGNORECASE
                ).strip()

            # Extract respondent - support for "…Respondents" or "...Respondents" separator, & Anr., And Ors.
            respondent = ""

            # Pattern 1: versus/v/s ... …Respondents or ...Respondents (with ellipsis or dots separator)
            # Example: "Versus Mr. Harun Attar & Anr. …Respondents" or "V/s. State of Maharashtra ...Respondents"
            respondent_pattern1 = r"(?:versus|V/s\.?)\s+((?:(?:Mr\.?|Ms\.?|Dr\.?|Shri?\.?|Smt\.?|The|State\s+of)\s+)?[A-Za-z\s\.\-&,]+?(?:\s+(?:And|&)\s+(?:Ors?\.?|Anr\.?))*?)\s*(?:…\.{0,2}|\.{2,})\s*Respondents?\.?"
            resp_match1 = re.search(
                respondent_pattern1, block_text, re.DOTALL | re.IGNORECASE
            )
            if resp_match1:
                respondent = resp_match1.group(1).strip()
                # Clean up whitespace and newlines
                respondent = re.sub(r"\s+", " ", respondent).strip()
                logging.info(
                    f"    ✅ Respondent Pattern 1 (…/...Respondents separator) matched: '{respondent}'"
                )

            # Pattern 2: versus ... before next major section (Mr./Ms./CORAM)
            if not respondent:
                respondent_pattern2 = r"versus\s+((?:(?:Mr\.?|Ms\.?|Dr\.?|Shri?\.?|Smt\.?|The)\s+)?[A-Za-z\s\.\-&,]+?(?:\s+(?:And|&)\s+(?:Ors?\.?|Anr\.?))*?)(?:\s+(?:Mr\.|Ms\.|Adv\.|CORAM)|\n|$)"
                resp_match2 = re.search(
                    respondent_pattern2, block_text, re.DOTALL | re.IGNORECASE
                )
                if resp_match2:
                    respondent = resp_match2.group(1).strip()
                    # Clean up whitespace, newlines, and trailing separator
                    respondent = re.sub(r"\s+", " ", respondent).strip()
                    respondent = re.sub(r"\s*…\s*$", "", respondent).strip()
                    logging.info(
                        f"    ✅ Respondent Pattern 2 (before next section) matched: '{respondent}'"
                    )

            # Pattern 3: Handle "....RESPONDENT And Ors" format (uppercase, dots separator)
            # Example: "The State Of Maharashtra Throu.govt Pleader....RESPONDENT And Ors"
            if not respondent:
                respondent_pattern3 = r"V/S\s+((?:The\s+)?[A-Za-z\s\.\-&,]+?)\s*\.{2,}\s*RESPONDENT(?:\s+And\s+Ors)?"
                resp_match3 = re.search(respondent_pattern3, block_text)
                if resp_match3:
                    respondent = resp_match3.group(1).strip()
                    respondent = re.sub(r"\s+", " ", respondent).strip()
                    logging.info(
                        f"    ✅ Respondent Pattern 3 (....RESPONDENT format) matched: '{respondent}'"
                    )

            if not respondent:
                logging.warning(f"    ❌ No respondent found for case {case_key}")

            # Extract government pleader from the advocates section
            govt_pleaders = self._extract_govt_pleader_from_text(text, case_key)
            logging.info(f"    📊 AGP/GP extracted: {govt_pleaders}")

            case_details[case_key] = {
                "case_type": case_type,
                "case_number": int(case_number),
                "case_year": int(year),
                "petitioner": petitioner,
                "respondent": respondent,
                "government_pleader": govt_pleaders,
            }
            logging.info(
                f"  ✅ Case {case_key} details: Petitioner={petitioner}, Respondent={respondent}, AGP={govt_pleaders}"
            )

        return case_details

    def _extract_govt_pleader_from_text(self, text: str, case_key: str) -> List[str]:
        """Extract government pleader names for a specific case with enhanced patterns"""
        pleaders = []
        logging.info(f"    🔍 Extracting AGP/GP names for case {case_key}")

        # Pattern 1: Extract AGP/GP names who appear "for the Respondent-State" or similar
        # Simpler, more robust pattern that handles both "a/w" and "with"
        # Match format: "Title Name, Role (a/w|with) Title Name, Role for Respondent"
        logging.info("      🔍 Testing Pattern 1 for AGP/GP extraction...")
        logging.info(f"      📄 Text snippet being searched (100 chars): '{text[:100]}'")

        # Handles "Mr. Name, Role a/w[.] Mr[.]Name, Role for Respondent" and
        # the Lok Adalat variant "Mr. Name, Role a/w. Mr.Name, Role present."
        # Key differences handled vs older patterns:
        #   • a/w.  — trailing period after 'w' (a/w\.?)
        #   • Mr.Name — no space between title and name (\s*)
        #   • 'B' Panel Council — non-standard GP role keyword
        #   • ends with "present" instead of "for Respondent"
        simple_pattern = (
            r"((?:Mr\.?|Ms\.?|Smt\.?|Adv\.)\s*[A-Z][A-Za-z\s\.]+?),"
            r"\s*([A-Za-z\.\s]+?)\s+(?:a/w\.?|with)\s*"
            r"((?:Mr\.?|Ms\.?|Smt\.?|Adv\.)\s*[A-Z][A-Za-z\s\.]+?),"
            r"\s*([^\n]+?)"
            r"(?=\s*(?:for\s+(?:the\s+)?Respondent|(?:is\s+)?present[,\.]?))"
        )

        for match in re.finditer(simple_pattern, text, re.IGNORECASE):
            title1_name1 = self._normalise_title_name(match.group(1))
            role1 = match.group(2).strip()
            title2_name2 = self._normalise_title_name(match.group(3))
            role2 = match.group(4).strip()

            logging.info(
                f"      🎯 Simple pattern matched: '{title1_name1}' role='{role1}', '{title2_name2}' role='{role2}'"
            )

            # Accept GP/AGP/G.P./Addl. roles and 'B'/'A' Panel Counsel roles
            _gp_role_re = r"(?:AGP|GP|G\.?\s*P\.?|Addl|Panel\s+Coun)"
            if re.search(_gp_role_re, role1, re.IGNORECASE):
                role1_normalized = self._normalize_agp_role(role1)
                formatted1 = f"{title1_name1.strip()}, {role1_normalized}"
                if formatted1 not in pleaders:
                    pleaders.append(formatted1)
                    logging.info(f"      ✅ AGP Pattern 1.1 matched: '{formatted1}'")

            if re.search(_gp_role_re, role2, re.IGNORECASE):
                role2_normalized = self._normalize_agp_role(role2)
                formatted2 = f"{title2_name2.strip()}, {role2_normalized}"
                if formatted2 not in pleaders:
                    pleaders.append(formatted2)
                    logging.info(
                        f"      ✅ AGP Pattern 1.2 (a/w|with) matched: '{formatted2}'"
                    )

        logging.info(f"      📊 Total AGP/GP found from Pattern 1: {len(pleaders)}")

        # Pattern 2a: "Adv/Ms/Mr Name, Role a/w Name, Role for the Respondent State in CASE_KEY"
        # Handles WP-11347 format where each case has named AGPs at the end of an order block.
        if not pleaders:
            pattern2a = (
                rf"(?:Adv\.\s+|Ms\.\s+|Mr\.\s+)([^,]+),\s*((?:Addl\.\s+)?(?:AGP|GP))"
                rf"(?:\s+a/w\s+([^,]+),\s*((?:AGP|GP)))?"
                rf"\s+for\s+the\s+Respondent\s+State\s+in\s+{re.escape(case_key)}"
            )
            match2a = re.search(pattern2a, text, re.IGNORECASE)
            if match2a:
                name1 = match2a.group(1).strip()
                role1 = self._normalize_agp_role(match2a.group(2).strip())
                formatted1 = f"{name1}, {role1}"
                if formatted1 not in pleaders:
                    pleaders.append(formatted1)
                    logging.info(f"      ✅ AGP Pattern 2a matched: '{formatted1}'")
                if match2a.group(3) and match2a.group(3).strip():
                    name2 = match2a.group(3).strip()
                    role2 = self._normalize_agp_role(
                        (match2a.group(4) or "AGP").strip()
                    )
                    formatted2 = f"{name2}, {role2}"
                    if formatted2 not in pleaders:
                        pleaders.append(formatted2)
                        logging.info(
                            f"      ✅ AGP Pattern 2a (a/w) matched: '{formatted2}'"
                        )

        # Pattern 2b: "Ms./Mr./Adv. Name for Respondent Nos.3 to 5-State in CASE_KEY"
        # Handles case-specific variant where role keyword is absent (WP-11347/WP-10601).
        if not pleaders:
            pattern2b = (
                rf"(?:Ms\.\s+|Mr\.\s+|Adv\.\s+|Shri\.?\s+|Smt\.?\s+)"
                rf"([A-Za-z\s\.]+?)\s+(?:for\s+)?Respondent\s+Nos?\.([0-9\s,to\-]+)"
                rf"State\s+in\s+{re.escape(case_key)}"
            )
            match2b = re.search(pattern2b, text, re.IGNORECASE)
            if match2b:
                name = match2b.group(1).strip()
                formatted = f"{name}, GP"
                if formatted not in pleaders:
                    pleaders.append(formatted)
                    logging.info(f"      ✅ AGP Pattern 2b matched: '{formatted}'")

        # Pattern 2c: "Ms./Mr./Adv. Name for Respondent Nos.X to Y-State" (no case ref at end)
        # Handles WP-10601 where the state-advocate line has no trailing case number.
        if not pleaders:
            for match2c in re.finditer(
                r"(?:Ms\.\s+|Mr\.\s+|Adv\.\s+|Shri\.?\s+|Smt\.?\s+)"
                r"([A-Za-z][A-Za-z\s\.]+?)\s+for\s+Respondent\s+Nos?\.[^\.]+?[-–]?State",
                text,
                re.IGNORECASE,
            ):
                name = match2c.group(1).strip()
                if len(name) > 3:
                    formatted = f"{name}, AGP"
                    if formatted not in pleaders:
                        pleaders.append(formatted)
                        logging.info(f"      ✅ AGP Pattern 2c matched: '{formatted}'")

        # Pattern 3: General State advocates (if no specific case match found)
        if not pleaders:
            # More precise patterns for AGP/GP mentions
            agp_patterns = [
                # Pattern 1: "Adv. Full Name, Role" - PRIORITY: capture everything after Adv. until comma
                r"Adv\.\s+([^,]+),\s*((?:Addl\.?\s*)?(?:AGP|GP|G\.?\s*P\.?|A\.?\s*G\.?\s*P\.?))\b",
                # Pattern 2: "Full Name, Role" - fallback for cases without Adv. prefix (must start with capital letter, not 'a' or 'w')
                r"\b(?!a/|w\s)([A-Z][A-Za-z]*(?:\s+[A-Z]\.?\s*)*[A-Za-z]+(?:\s+[A-Z][A-Za-z]*)*),\s*((?:Addl\.?\s*)?(?:AGP|GP|G\.?\s*P\.?|A\.?\s*G\.?\s*P\.?))\b",
                # Pattern 3: "AGP Shri/Mr. Name" - role followed by title and name (improved)
                r"(?:AGP|GP|Addl\.?\s*GP)\s+(?:Shri\.?|Smt\.?|Mr\.?|Ms\.?)\s+([A-Z][A-Za-z]*(?:\s+[A-Z]\.?\s*)*[A-Za-z]+(?:\s+[A-Z][A-Za-z]*)*)\b",
                # Pattern 4: "Government Pleader: Name" (improved)
                r"(?:Government\s+Pleader|Govt\.?\s+Pleader)\s*:?\s*([A-Z][A-Za-z]*(?:\s+[A-Z]\.?\s*)*[A-Za-z]+(?:\s+[A-Z][A-Za-z]*)*)",
                # Pattern 5: "APP/AGP Name" - standalone role and name (exclude common words) (improved)
                r"\b(?:APP|AGP|A\.?\s*P\.?\s*P\.?|A\.?\s*G\.?\s*P\.?)\s+(?!for|the|and|with|in\b)([A-Z][A-Za-z]*(?:\s+[A-Z]\.?\s*)*[A-Za-z]+(?:\s+[A-Z][A-Za-z]*)*)\b",
            ]

            # Process patterns with priority (Adv. patterns first, then filter general matches)
            adv_matches: List[str] = []
            general_matches: List[str] = []

            for i, pattern in enumerate(agp_patterns):
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple) and len(match) == 2:
                        name, role = match
                        name = name.strip()
                        role = role.strip()

                        # Skip if name contains common words that indicate it's not a person
                        # Use word boundaries to avoid false positives (e.g., "and" in "Deshpande")
                        if any(
                            re.search(
                                r"\b" + re.escape(word) + r"\b", name, re.IGNORECASE
                            )
                            for word in [
                                "for",
                                "the",
                                "and",
                                "with",
                                "in",
                                "state",
                                "respondent",
                            ]
                        ):
                            continue

                        normalized_role = self._normalize_agp_role(role)

                        if name and len(name) > 1:
                            if i == 0:  # Pattern 1 (Adv. prefix) gets priority
                                adv_matches.append(f"{name}, {normalized_role}")
                            else:
                                # Avoid duplicates: skip if this name is already in an Adv. match
                                is_duplicate = False
                                for adv_match in adv_matches:
                                    adv_name = adv_match.split(", ")[0]
                                    if name in adv_name or adv_name in name:
                                        is_duplicate = True
                                        break
                                if not is_duplicate:
                                    general_matches.append(f"{name}, {normalized_role}")

            # Combine results: Adv. patterns first, then general patterns
            all_matches = adv_matches + general_matches

            # Handle "a/w" / "a/w." (along with) pattern for second advocates.
            # \s* instead of \s+ allows "Mr.Name" (no space after title prefix).
            # G\.?\s*P\.? handles "G.P" / "G.P." without A-prefix.
            aw_pattern = (
                r"a/w\.?\s*(?:(?:Mr\.?|Ms\.?|Smt\.?|Adv\.)\s*)?"
                r"([A-Z][^,\n]+?),\s*((?:Addl\.?\s*)?(?:AGP|GP|G\.?\s*P\.?|A\.?\s*G\.?\s*P\.?))\b"
            )
            aw_matches: List[Tuple[str, str]] = re.findall(
                aw_pattern, text, re.IGNORECASE
            )
            for aw_match in aw_matches:
                name, role = aw_match
                name = name.strip()
                role = role.strip()

                # Skip if name contains common words
                if any(
                    re.search(r"\b" + re.escape(word) + r"\b", name, re.IGNORECASE)
                    for word in [
                        "for",
                        "the",
                        "and",
                        "with",
                        "in",
                        "state",
                        "respondent",
                    ]
                ):
                    continue

                normalized_role = self._normalize_agp_role(role)

                if name and len(name) > 1:
                    all_matches.append(f"{name}, {normalized_role}")

            # Add all matches to pleaders list
            pleaders.extend(all_matches)

        # Remove duplicates while preserving order.
        # Use a normalised key so "Mr. Asif Patel" and "Mr.Asif Patel" collapse
        # to the same entry regardless of which code path produced each string.
        seen: set = set()
        unique_pleaders = []
        for pleader in pleaders:
            key = self._normalise_title_name(pleader).lower()
            if key not in seen:
                seen.add(key)
                unique_pleaders.append(self._normalise_title_name(pleader))

        return unique_pleaders

    @staticmethod
    def _normalise_title_name(s: str) -> str:
        """Ensure a space after title prefixes so 'Mr.Name' and 'Mr. Name' normalise
        to the same string — prevents spurious duplicates when the same advocate
        appears in both the header and the body of an order with inconsistent spacing.
        """
        s = re.sub(
            r"\b(Mr|Ms|Mrs|Smt|Adv|Dr)\.([A-Za-z])",
            r"\1. \2",
            s,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", s).strip()

    def _normalize_agp_role(self, role: str) -> str:
        """Normalize AGP/GP role names to standard format"""
        role_upper = role.upper().replace(".", "").replace(" ", "").replace("'", "")
        if "AGP" in role_upper or "APP" in role_upper:
            return "AGP"
        elif "ADDLGP" in role_upper or "ADDL" in role_upper:
            return "Addl. G.P."
        elif "PANEL" in role_upper:
            # Preserve the Panel designation as-is — 'B' Panel Council is a
            # distinct role and must not be collapsed to GP.
            return role.strip()
        else:
            return "GP"

    def _normalize_person_name(self, name: str) -> str:
        """Strip common title prefixes so all names are stored in a consistent format.

        Patterns like 'Ms. N. M. Mehra' and 'Adv. N. M. Mehra' refer to the same
        person but compare as unequal. Stripping the prefix and re-prefixing with
        'Adv.' lets deduplication work across extraction patterns.
        """
        return re.sub(
            r"^(?:Adv\.?\s*|Ms\.?\s*|Mr\.?\s*|Shri\.?\s*|Smt\.?\s*|Dr\.?\s*)",
            "",
            name.strip(),
            flags=re.IGNORECASE,
        ).strip()

    def _extract_parties_for_case(
        self, text: str, case_canonical: str
    ) -> Tuple[str, str]:
        """Extract petitioner and respondent for a specific case"""
        # Try to find the case block
        # Move the replace outside f-string to avoid backslash in f-string expression
        case_with_of = case_canonical.replace("/", r"\s+OF\s+")
        case_pattern = rf"({re.escape(case_canonical)}|{case_with_of})(.*?)(?=(?:WRIT PETITION|WITH|(?:Mr\.|Ms\.|Adv\.)\s+[A-Z].*?for|$))"
        match = re.search(case_pattern, text, re.DOTALL | re.IGNORECASE)

        petitioner = ""
        respondent = ""

        if match:
            block = match.group(2)

            # Enhanced petitioner extraction with multiple patterns
            petitioner = ""

            # Pattern 1: Standard format with title and dots
            pet_pattern1 = r"((?:Shri?\.?|Smt\.?|Mr\.?|Ms\.?|Dr\.?)\s+[A-Za-z\s\.\-]+?)(?:\s+And\s+Ors\.?)?\s*\.{2,}\s*Petitioners?"
            pet_match1 = re.search(pet_pattern1, block, re.IGNORECASE)
            if pet_match1:
                petitioner = pet_match1.group(1).strip()
                if re.search(
                    r"And\s+Ors\.?",
                    block[pet_match1.start() : pet_match1.end() + 50],
                    re.IGNORECASE,
                ):
                    petitioner += " And Ors."

            # Pattern 2: Name followed by petitioner designation (more flexible)
            if not petitioner:
                pet_pattern2 = r"([A-Z][a-zA-Z\s\.\-]+?)(?:\s+And\s+Ors\.?)?\s*\.{2,}\s*Petitioners?"
                pet_match2 = re.search(pet_pattern2, block, re.IGNORECASE)
                if pet_match2:
                    petitioner = pet_match2.group(1).strip()

            # Pattern 3: Petitioner mentioned in sentence format
            if not petitioner:
                pet_pattern3 = (
                    r"Petitioners?\s*:?\s*([A-Z][a-zA-Z\s\.\-]+?)(?:\s+And\s+Ors\.?)?"
                )
                pet_match3 = re.search(pet_pattern3, block, re.IGNORECASE)
                if pet_match3:
                    petitioner = pet_match3.group(1).strip()

            # Pattern 4: Name before "versus" or "vs" (fallback)
            if not petitioner:
                versus_pattern = (
                    r"^([A-Z][a-zA-Z\s\.\-]+?)(?:\s+And\s+Ors\.?)?\s*(?:versus|vs\.?)\s"
                )
                versus_match = re.search(
                    versus_pattern, block.strip(), re.IGNORECASE | re.MULTILINE
                )
                if versus_match:
                    petitioner = versus_match.group(1).strip()

            # Clean up petitioner name
            if petitioner:
                petitioner = re.sub(r"\s+", " ", petitioner).strip()
                petitioner = re.sub(r"\.{2,}$", "", petitioner).strip()

            # Enhanced respondent extraction
            respondent = ""
            resp_pattern1 = r"versus\s+(.*?)(?:\s*\.{2,}\s*Respondent)"
            resp_match1 = re.search(resp_pattern1, block, re.DOTALL | re.IGNORECASE)
            if resp_match1:
                respondent = resp_match1.group(1).strip()
            else:
                # Fallback: look for respondent after versus without requiring dots
                resp_pattern2 = r"versus\s+(.*?)(?=\s*\.{2,}|$)"
                resp_match2 = re.search(resp_pattern2, block, re.DOTALL | re.IGNORECASE)
                if resp_match2:
                    respondent = resp_match2.group(1).strip()

            # Clean up respondent
            if respondent:
                respondent = re.sub(r"\s+", " ", respondent).strip()
                respondent = re.sub(r"\.{2,}$", "", respondent).strip()

        return petitioner, respondent

    def _extract_govt_pleader_for_case(
        self, text: str, case_canonical: str
    ) -> List[str]:
        """Extract government pleader for a specific case by canonical ID"""
        # Use the case key format (e.g., "WP/11347/2024")
        case_key = case_canonical.replace("/", "/")
        return self._extract_govt_pleader_from_text(text, case_key)

    def _extract_petitioners(self, text: str) -> List[Dict[str, Any]]:
        """Extract petitioner names and information"""
        petitioners = []
        logging.info(f"🔍 Extracting petitioners from text (length: {len(text)} chars)")

        for idx, pattern in enumerate(self.entity_patterns["PETITIONER"]):
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            match_count = 0
            for match in matches:
                match_count += 1
                try:
                    name = (
                        match.group(1).strip()
                        if match.groups()
                        else match.group().strip()
                    )
                    # Clean up the name
                    name = re.sub(r"\s+", " ", name)
                    name = re.sub(
                        r"^(Shri\.?|Smt\.?|Ms\.?|Mr\.?)\s+",
                        "",
                        name,
                        flags=re.IGNORECASE,
                    )

                    if name and len(name) > 2:
                        petitioners.append(
                            {
                                "name": name,
                                "type": "PETITIONER",
                                "raw_text": match.group(),
                                "start": match.start(),
                                "end": match.end(),
                                "confidence": 0.9,
                            }
                        )
                        logging.info(f"  ✅ Pattern {idx+1} found petitioner: '{name}'")
                except IndexError:
                    logging.warning(
                        f"Pattern {pattern} matched but has no capturing groups"
                    )
                    continue

            if match_count == 0:
                logging.debug(f"  ❌ Pattern {idx+1} found no matches")

        deduplicated = self._deduplicate_entities(petitioners)
        logging.info(
            f"  📊 Total petitioners extracted: {len(deduplicated)} (after deduplication from {len(petitioners)})"
        )
        return deduplicated

    def _extract_respondents(self, text: str) -> List[Dict[str, Any]]:
        """Extract respondent names and information"""
        respondents = []
        logging.info(f"🔍 Extracting respondents from text (length: {len(text)} chars)")

        for idx, pattern in enumerate(self.entity_patterns["RESPONDENT"]):
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            match_count = 0
            for match in matches:
                match_count += 1
                try:
                    name = (
                        match.group(1).strip()
                        if match.groups()
                        else match.group().strip()
                    )
                    # Clean up the name
                    name = re.sub(r"\s+", " ", name)
                    name = re.sub(
                        r"^(The\s+)?State\s+Of\s+Maharashtra.*",
                        "State Of Maharashtra",
                        name,
                        flags=re.IGNORECASE,
                    )

                    if name and len(name) > 2:
                        respondents.append(
                            {
                                "name": name,
                                "type": "RESPONDENT",
                                "raw_text": match.group(),
                                "start": match.start(),
                                "end": match.end(),
                                "confidence": 0.9,
                            }
                        )
                        logging.info(f"  ✅ Pattern {idx+1} found respondent: '{name}'")
                except IndexError:
                    logging.warning(
                        f"Pattern {pattern} matched but has no capturing groups"
                    )
                    continue

            if match_count == 0:
                logging.debug(f"  ❌ Pattern {idx+1} found no matches")

        deduplicated = self._deduplicate_entities(respondents)
        logging.info(
            f"  📊 Total respondents extracted: {len(deduplicated)} (after deduplication from {len(respondents)})"
        )
        return deduplicated

    def _extract_agp_names(
        self, text: str, existing_entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract AGP names using enhanced patterns and existing ML results"""
        agp_names = []
        logging.info(f"🔍 Extracting AGP/GP names from text (length: {len(text)} chars)")

        # Use existing ML parser results
        ml_count = 0
        for entity in existing_entities:
            if entity.get("label") in ["AGP", "GP", "AG", "ADDL_GP", "B_PNL"]:
                ml_count += 1
                agp_names.append(
                    {
                        "name": entity.get("text", ""),
                        "type": entity.get("label", "AGP"),
                        "raw_text": entity.get("text", ""),
                        "start": entity.get("start", 0),
                        "end": entity.get("end", 0),
                        "confidence": entity.get("confidence", 0.8),
                        "source": "ml_parser",
                    }
                )
        logging.info(f"  📊 ML Parser found {ml_count} AGP/GP names")

        # Enhance with additional patterns
        for idx, pattern in enumerate(self.entity_patterns["AGP_ENHANCED"]):
            matches = re.finditer(pattern, text, re.IGNORECASE)
            match_count = 0
            for match in matches:
                match_count += 1
                name = match.group(1).strip()
                # Clean up the name
                name = re.sub(r"\s+", " ", name)

                if name and len(name) > 1:
                    agp_names.append(
                        {
                            "name": name,
                            "type": "AGP",
                            "raw_text": match.group(),
                            "start": match.start(),
                            "end": match.end(),
                            "confidence": 0.85,
                            "source": "enhanced_patterns",
                        }
                    )
                    logging.info(f"  ✅ Pattern {idx+1} found AGP: '{name}'")

            if match_count == 0:
                logging.debug(f"  ❌ Pattern {idx+1} found no matches")

        deduplicated = self._deduplicate_entities(agp_names)
        logging.info(
            f"  📊 Total AGP/GP extracted: {len(deduplicated)} (after deduplication from {len(agp_names)})"
        )
        return deduplicated

    def _extract_dates(self, text: str) -> List[Dict[str, Any]]:
        """Extract dates from order text"""
        dates = []

        for pattern in self.date_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                raw_date = match.group().strip()

                # Try to parse and normalize the date
                normalized_date = self._normalize_date(raw_date)

                if normalized_date:
                    dates.append(
                        {
                            "raw_date": raw_date,
                            "normalized_date": normalized_date,
                            "start": match.start(),
                            "end": match.end(),
                            "confidence": 0.9,
                        }
                    )

        return self._deduplicate_dates(dates)

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize date string to standard format"""
        try:
            # Common date format patterns
            patterns = [
                r"(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})",
                r"(\d{1,2})/(\d{1,2})/(\d{4})",
                r"(\d{1,2})-(\d{1,2})-(\d{4})",
                r"(\d{4})-(\d{1,2})-(\d{1,2})",
            ]

            for pattern in patterns:
                match = re.search(pattern, date_str, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        # Handle different formats
                        if groups[1].isalpha():  # Month name format
                            month_map = {
                                "january": "01",
                                "february": "02",
                                "march": "03",
                                "april": "04",
                                "may": "05",
                                "june": "06",
                                "july": "07",
                                "august": "08",
                                "september": "09",
                                "october": "10",
                                "november": "11",
                                "december": "12",
                            }
                            month = month_map.get(groups[1].lower(), groups[1])
                            return f"{groups[2]}-{month.zfill(2)}-{groups[0].zfill(2)}"
                        else:  # Numeric format
                            if len(groups[0]) == 4:  # YYYY-MM-DD format
                                return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}"
                            else:  # DD/MM/YYYY or MM/DD/YYYY format
                                return f"{groups[2]}-{groups[1].zfill(2)}-{groups[0].zfill(2)}"

            return None

        except Exception as e:
            logging.warning(f"Could not normalize date '{date_str}': {e}")
            return None

    def _extract_key_phrases(self, text: str, order_category: str) -> List[str]:
        """Extract key phrases relevant to the order category"""
        key_phrases = []

        if order_category == "DISPOSED_OFF":
            disposal_phrases = [
                r"disposed?\s+off?\s+as\s+[^.]*",
                r"petition\s+is\s+dismissed?[^.]*",
                r"final\s+disposal[^.]*",
                r"matter\s+(?:is\s+)?disposed?\s+off?[^.]*",
            ]
            for pattern in disposal_phrases:
                matches = re.findall(pattern, text, re.IGNORECASE)
                key_phrases.extend(matches)

        elif order_category == "ADJOURNED":
            adjournment_phrases = [
                r"stand\s+over\s+to\s+[^.]*",
                r"list(?:ed)?\s+(?:the\s+same\s+)?on\s+[^.]*",
                r"next\s+(?:date|hearing)\s+[^.]*",
                r"interim\s+order[^.]*to\s+continue[^.]*",
            ]
            for pattern in adjournment_phrases:
                matches = re.findall(pattern, text, re.IGNORECASE)
                key_phrases.extend(matches)

        return [phrase.strip() for phrase in key_phrases if phrase.strip()]

    def _extract_next_hearing_date(self, text: str) -> Optional[str]:
        """Extract next hearing date if mentioned"""
        next_date_patterns = [
            r"stand\s+over\s+to\s+([^.]+)",
            r"list(?:ed)?\s+(?:the\s+same\s+)?on\s+([^.]+)",
            r"next\s+(?:date|hearing)\s+(?:is\s+)?(?:fixed\s+)?(?:on\s+)?([^.]+)",
            r"to\s+be\s+listed\s+on\s+([^.]+)",
        ]

        for pattern in next_date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                # Clean up the date string
                date_str = re.sub(r"[,.].*$", "", date_str)  # Remove trailing content
                normalized = self._normalize_date(date_str)
                return normalized if normalized else date_str

        return None

    def _extract_disposal_reason(self, text: str) -> Optional[str]:
        """Extract reason for disposal if order is disposed off"""
        disposal_patterns = [
            r"disposed?\s+off?\s+as\s+([^.]+)",
            r"dismissed?\s+as\s+([^.]+)",
            r"petition\s+(?:is\s+)?dismissed?\s+([^.]*)",
            r"withdrawn\s+([^.]*)",
        ]

        for pattern in disposal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                reason = match.group(1).strip()
                # Clean up the reason
                reason = re.sub(r"^being\s+", "", reason, flags=re.IGNORECASE)
                return reason if reason else None

        return None

    def _deduplicate_entities(
        self, entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove duplicate entities based on name similarity"""
        if not entities:
            return entities

        unique_entities = []
        seen_names = set()

        for entity in entities:
            name_key = entity["name"].lower().strip()
            if name_key not in seen_names:
                seen_names.add(name_key)
                unique_entities.append(entity)

        return unique_entities

    def _deduplicate_dates(self, dates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate dates"""
        if not dates:
            return dates

        unique_dates = []
        seen_dates = set()

        for date_info in dates:
            date_key = date_info.get("normalized_date") or date_info.get("raw_date")
            if date_key and date_key not in seen_dates:
                seen_dates.add(date_key)
                unique_dates.append(date_info)

        return unique_dates

    def save_analysis_result(
        self, filename: str, analysis_result: OrderAnalysisResult
    ) -> str:
        """Save analysis result to Firestore"""
        try:
            # Prepare data for storage with simplified structure
            result_data = {
                "filename": filename,
                "order_category": analysis_result.order_category,
                "category_confidence": analysis_result.category_confidence,
                "order_date": analysis_result.order_date,
                "cases": [
                    {
                        "case_type": case.case_type,
                        "case_number": case.case_number,
                        "case_year": case.case_year,
                        "petitioner": case.petitioner,
                        "respondent": case.respondent,
                        "government_pleader": case.government_pleader,
                    }
                    for case in analysis_result.cases
                ],
                "analysis_timestamp": datetime.now().isoformat(),
                "text_length": len(analysis_result.order_text),
            }

            # Save to Firestore
            doc_ref = self.db.collection("order_analysis").add(result_data)
            doc_id = doc_ref[1].id

            logging.info(f"Order analysis saved with ID: {doc_id}")
            return doc_id

        except Exception as e:
            logging.error(f"Error saving analysis result: {e}")
            raise RuntimeError(f"Failed to save analysis result: {str(e)}")
