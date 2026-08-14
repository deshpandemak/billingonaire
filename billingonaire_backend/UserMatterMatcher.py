"""
User Matter Matcher - Links logged-in users to their legal matters
Uses pattern matching and ML techniques to identify user involvement in cases
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from firebase_admin import firestore

try:
    from case_data_store import CaseDataStore
except ImportError:
    from .case_data_store import CaseDataStore


@dataclass
class UserRole:
    """Represents a user's legal role and associated name patterns"""

    role_type: str  # AGP, GP, Addl GP, B_Pnl, State Advocate, AG
    full_name: str
    name_variations: List[str]
    pattern_keywords: List[str]  # Role-specific keywords
    confidence_threshold: float = (
        0.50  # Lowered from 0.75 to match bill generation logic
    )


@dataclass
class MatterMatch:
    """Represents a matched matter for a user"""

    case_id: str
    case_ref: str
    match_source: str  # 'board_data', 'case_details'
    match_field: (
        str  # 'petitioner_lawyer', 'respondent_lawyer', 'government_pleader', etc.
    )
    matched_text: str
    confidence_score: float
    role_type: str
    board_date: Optional[str] = None


class UserMatterMatcher:
    """
    Intelligent user-matter matching system for Government Pleaders
    Supports fuzzy matching, pattern recognition, and ML-based name matching
    """

    def __init__(self):
        self.db = firestore.client()
        self.case_store = CaseDataStore(self.db)

        # Government Pleader role patterns
        self.role_patterns = {
            "AGP": [
                r"(?:Asst\.?\s*)?(?:A\.?G\.?P\.?|Assistant\s+Government\s+Pleader)",
                r"A\.?\s*G\.?\s*P\.?",
                r"Assistant\s+Government\s+Pleader",
            ],
            "GP": [
                r"(?:G\.?P\.?|Government\s+Pleader)(?!\s*(?:Asst|Assistant))",
                r"Government\s+Pleader(?!\s*(?:Asst|Assistant))",
                r"Govt\.?\s+Pleader(?!\s*(?:Asst|Assistant))",
                r"G\.?\s*P\.?(?!\s*(?:Asst|Assistant))",
                r"Spl\.?\s*G\.?P\.?",
                r"Special\s+Government\s+Pleader",
            ],
            "Addl_GP": [
                r"(?:Addl\.?\s*G\.?P\.?|Additional\s+Government\s+Pleader)",
                r"Additional\s+Government\s+Pleader",
                r"Addl\.?\s*G\.?\s*P\.?",
            ],
            "B_Pnl": [
                r"B[\'\"]?\s*Pnl",
                r"B\s*Panel",
                r"Brief\s*Panel",
                r"Panel\s*(?:Advocate|Counsel)",
            ],
            "State_Advocate": [
                r"State\s+Advocate",
                r"Advocate\s+for\s+State",
                r"State\s+Counsel",
            ],
            "AG": [
                r"(?:A\.?G\.?|Advocate\s+General)(?!\s*P)",
                r"Advocate\s+General",
                r"A\.?\s*G\.?(?!\s*P)",
            ],
        }

        # Common name prefixes and suffixes
        self.name_prefixes = [
            "Mr.",
            "Ms.",
            "Mrs.",
            "Dr.",
            "Adv.",
            "Smt.",
            "Shri",
            "Kumari",
        ]
        self.name_suffixes = ["Esq.", "Jr.", "Sr.", "II", "III"]

    def normalize_name(self, name: str) -> str:
        """Normalize name for better matching"""
        if not name:
            return ""

        # Remove unicode normalization
        name = unicodedata.normalize("NFKD", name)

        # Remove common prefixes and suffixes
        for prefix in self.name_prefixes:
            if name.startswith(prefix):
                name = name[len(prefix) :].strip()

        for suffix in self.name_suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()

        # Clean up spacing and punctuation
        name = re.sub(r"[.,;]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()

        return name.lower()

    def generate_name_variations(self, full_name: str) -> List[str]:
        """Generate possible name variations for matching - enhanced to match UserManager logic"""
        variations = [full_name]
        normalized = self.normalize_name(full_name)
        variations.append(normalized)

        # Split into parts
        parts = normalized.split()
        if len(parts) >= 2:
            # First and last name combinations
            variations.extend(
                [
                    f"{parts[0]} {parts[-1]}",  # First + Last
                    f"{parts[0][0]}. {parts[-1]}",  # Initial + Last
                    f"{parts[0]} {parts[-1][0]}.",  # First + Last Initial
                    parts[0],  # First name only
                    parts[-1],  # Last name only
                ]
            )

            # Add middle name combinations if available
            if len(parts) >= 3:
                variations.extend(
                    [
                        f"{parts[0]} {parts[1]} {parts[-1]}",  # First Middle Last
                        f"{parts[0][0]}. {parts[1][0]}. {parts[-1]}",  # Initials + Last
                        f"{parts[0]} {parts[1]}",  # First + Middle
                    ]
                )

        # Enhanced variations similar to UserManager logic
        import re

        user_words = re.findall(r"\b\w+\b", normalized)
        if len(user_words) >= 2:
            # Generate initials combinations
            user_initials = [word[0] for word in user_words]

            # All initials with dots: "P.M.J.D."
            if len(user_initials) >= 2:
                initials_with_dots = ".".join(user_initials) + "."
                variations.append(initials_with_dots)

                # Partial initials combinations
                for i in range(2, len(user_initials) + 1):
                    partial_initials = ".".join(user_initials[:i]) + "."
                    variations.append(partial_initials)

            # Last name with different initial combinations
            last_name = user_words[-1]
            for i in range(1, len(user_initials)):
                init_combo = "".join(user_initials[:i])
                variations.extend(
                    [
                        f"{init_combo}.{last_name}",
                        f"{init_combo} {last_name}",
                    ]
                )

            # Handle compound last names (e.g., "Joshi Deshpande")
            if len(user_words) >= 3:
                # Check if second-to-last word might be part of last name
                middle_word = user_words[-2]
                compound_last = f"{middle_word} {last_name}"
                variations.append(compound_last)

                # Initials with compound last name
                for i in range(1, len(user_initials)):
                    init_combo = "".join(user_initials[:i])
                    variations.extend(
                        [
                            f"{init_combo}.{compound_last}",
                            f"{init_combo} {compound_last}",
                        ]
                    )

                # Special case: middle name as last name (e.g., "P.M.Joshi" for "Pooja Makarand Joshi Deshpande")
                for i in range(1, len(user_words) - 1):  # Don't use actual last name
                    middle_as_last = user_words[i]
                    for j in range(1, len(user_initials)):
                        init_combo = "".join(user_initials[:j])
                        variations.extend(
                            [
                                f"{init_combo}.{middle_as_last}",
                                f"{init_combo} {middle_as_last}",
                            ]
                        )
                        # Also add with spaces between initials
                        spaced_initials = " ".join(user_initials[:j])
                        variations.extend(
                            [
                                f"{spaced_initials}.{middle_as_last}",
                                f"{spaced_initials} {middle_as_last}",
                            ]
                        )

        # Remove duplicates while preserving order
        seen = set()
        unique_variations = []
        for var in variations:
            if var and var not in seen:
                seen.add(var)
                unique_variations.append(var)

        return unique_variations

    def fuzzy_match_score(self, name1: str, name2: str) -> float:
        """Calculate fuzzy matching score between two names.

        Delegates to the module-level score_name_match -- this method used to
        carry its own, independently-tuned scoring (different component
        weights: 25/35/25/15 here vs 35/25/25/15 there, and no last-name
        gate), which meant this class's matches and UserManager's
        match_user_name_to_all_agps/Board's any_name_matches could disagree
        on the exact same two names depending on which code path asked.
        UserManager.py already made this same fix (see
        match_user_name_to_all_agps's docstring: "so the scoring logic is
        defined in one place"); this brings the last caller into line so
        there is exactly one scoring algorithm in the codebase.
        """
        return score_name_match(name1, name2)

    def extract_role_from_text(self, text: str) -> Optional[str]:
        """Extract government pleader role from text using pattern matching"""
        if not text:
            return None

        for role, patterns in self.role_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return role

        return None

    # How far below the acceptance threshold a match can fall and still be
    # worth asking a human about, rather than discarded with no trace at
    # all. Below (threshold - NEAR_MISS_BAND), a match is noise, not a
    # plausible-but-uncertain candidate.
    NEAR_MISS_BAND = 0.15

    def find_user_matches_in_text(
        self, text: str, user_role: UserRole, field_context: str = ""
    ) -> List[Tuple[str, float]]:
        """Find user name matches in given text with role-aware scoring."""
        accepted, _ = self._score_text_against_role(text, user_role, field_context)
        return accepted

    def find_near_miss_matches_in_text(
        self, text: str, user_role: UserRole, field_context: str = ""
    ) -> List[Tuple[str, float]]:
        """Matches that fell just short of the acceptance threshold --
        plausible enough to ask a human to confirm rather than silently
        drop. See ``NEAR_MISS_BAND`` for how far "just short" reaches."""
        _, near_misses = self._score_text_against_role(text, user_role, field_context)
        return near_misses

    def _score_text_against_role(
        self, text: str, user_role: UserRole, field_context: str = ""
    ) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Single scoring pass shared by find_user_matches_in_text and
        find_near_miss_matches_in_text so the two never drift out of sync.
        Returns (accepted, near_miss) -- each a list of (matched_text, score).
        """
        if not text:
            return [], []

        accepted: List[Tuple[str, float]] = []
        near_miss: List[Tuple[str, float]] = []

        # Detect role context in text for scoring boost
        role_context_bonus = 0.0
        detected_role = self.extract_role_from_text(text)

        # Boost score if detected role matches user's role or is compatible
        if detected_role and detected_role == user_role.role_type:
            role_context_bonus = 0.1
        elif detected_role and self._is_compatible_role(
            detected_role, user_role.role_type
        ):
            role_context_bonus = 0.05

        # Additional context bonus based on field type
        field_bonus = 0.0
        if field_context:
            field_bonus = self._get_field_context_bonus(
                field_context, user_role.role_type
            )

        # Check all name variations
        for name_var in user_role.name_variations:
            if not name_var:
                continue

            # Direct substring match (case insensitive)
            if name_var.lower() in text.lower():
                base_score = 0.95
                final_score = min(1.0, base_score + role_context_bonus + field_bonus)
                accepted.append((name_var, final_score))
                continue

            # Fuzzy matching against text segments
            # Split text into potential name segments
            text_segments = re.findall(r"\b[A-Za-z][A-Za-z\s\.]{2,30}\b", text)

            for segment in text_segments:
                base_score = self.fuzzy_match_score(name_var, segment.strip())
                # Last-name-only matches are ambiguous when multiple users share a
                # surname (e.g. "Deshpande" → both "Pooja Deshpande" and "Priya
                # Deshpande").  Require a higher threshold unless initials also match.
                effective_threshold = user_role.confidence_threshold
                if base_score >= effective_threshold:
                    import re as _re

                    norm_var = self.normalize_name(name_var)
                    norm_seg = self.normalize_name(segment.strip())
                    words_var = _re.findall(r"\b\w+\b", norm_var)
                    words_seg = _re.findall(r"\b\w+\b", norm_seg)
                    if (
                        words_var
                        and words_seg
                        and words_var[-1] == words_seg[-1]
                        and len(words_seg) == 1
                    ):
                        # Segment is only the last name — require 0.80 to accept.
                        effective_threshold = max(effective_threshold, 0.80)
                if base_score >= effective_threshold:
                    final_score = min(
                        1.0, base_score + role_context_bonus + field_bonus
                    )
                    accepted.append((segment.strip(), final_score))
                elif base_score >= effective_threshold - self.NEAR_MISS_BAND:
                    final_score = min(
                        1.0, base_score + role_context_bonus + field_bonus
                    )
                    near_miss.append((segment.strip(), final_score))

        return accepted, near_miss

    def _is_compatible_role(self, detected_role: str, user_role: str) -> bool:
        """Check if detected role is compatible with user's role"""
        # Define role compatibility (e.g., AGP and GP are both government side)
        govt_roles = {"AGP", "GP", "Addl_GP", "State_Advocate", "AG"}
        panel_roles = {"B_Pnl"}

        if detected_role in govt_roles and user_role in govt_roles:
            return True
        if detected_role in panel_roles and user_role in panel_roles:
            return True

        return False

    def _get_field_context_bonus(self, field_context: str, user_role: str) -> float:
        """Get scoring bonus based on field context and user role"""
        # Government pleaders typically appear on respondent side
        govt_roles = {"AGP", "GP", "Addl_GP", "State_Advocate", "AG"}

        if user_role in govt_roles:
            if (
                "respondent" in field_context.lower()
                or "order_agp" in field_context.lower()
            ):
                return 0.05  # Bonus for appropriate field
            elif "petitioner" in field_context.lower():
                return -0.05  # Penalty for unexpected field

        return 0.0

    def get_user_role_config(self, user_id: str) -> Optional[UserRole]:
        """Get user role configuration from database"""
        try:
            doc_ref = self.db.collection("user-roles").document(user_id)
            doc = doc_ref.get()

            if not doc.exists:
                return None

            data = doc.to_dict()

            # Generate name variations if not provided
            name_variations = data.get("name_variations", [])
            if not name_variations and data.get("full_name"):
                name_variations = self.generate_name_variations(data["full_name"])

            return UserRole(
                role_type=data.get("role_type", ""),
                full_name=data.get("full_name", ""),
                name_variations=name_variations,
                pattern_keywords=data.get("pattern_keywords", []),
                confidence_threshold=data.get(
                    "confidence_threshold", 0.50
                ),  # Lowered default
            )

        except Exception as e:
            logging.error(f"Error getting user role config for {user_id}: {e}")
            return None

    def save_user_role_config(self, user_id: str, user_role: UserRole) -> bool:
        """Save user role configuration to database"""
        try:
            doc_ref = self.db.collection("user-roles").document(user_id)
            doc_ref.set(
                {
                    "role_type": user_role.role_type,
                    "full_name": user_role.full_name,
                    "name_variations": user_role.name_variations,
                    "pattern_keywords": user_role.pattern_keywords,
                    "confidence_threshold": user_role.confidence_threshold,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
            )
            return True

        except Exception as e:
            logging.error(f"Error saving user role config for {user_id}: {e}")
            return False

    def find_user_matters(self, user_id: str, limit: int = 100) -> List[MatterMatch]:
        """Find all matters associated with a user"""
        user_role = self.get_user_role_config(user_id)
        if not user_role:
            logging.warning(f"No role configuration found for user {user_id}")
            return []

        matches = []
        try:
            # Load all board docs first (single stream call)
            all_docs = list(self.db.collection("daily-boards").limit(limit).stream())

            # Batch-fetch case details to avoid N+1 (one read per case → 10 per chunk)
            case_refs_for_batch = []
            doc_case_refs = []
            for doc in all_docs:
                d = doc.to_dict()
                cr = f"{d.get('case_type', '')}/{d.get('case_no', '')}/{d.get('case_year', '')}"
                doc_case_refs.append(cr)
                case_refs_for_batch.append(cr)

            details_map = self.case_store.get_case_details_map(case_refs_for_batch)

            for doc, case_ref in zip(all_docs, doc_case_refs):
                doc_data = doc.to_dict()
                case_id = doc.id

                # Check board data fields
                board_fields = {
                    "petitioner_lawyer": doc_data.get("petitioner_lawyer", ""),
                    "respondent_lawyer": doc_data.get("respondent_lawyer", ""),
                }
                for field_name, field_value in board_fields.items():
                    if field_value:
                        for matched_text, confidence in self.find_user_matches_in_text(
                            field_value, user_role, field_name
                        ):
                            matches.append(
                                MatterMatch(
                                    case_id=case_id,
                                    case_ref=case_ref,
                                    match_source="board_data",
                                    match_field=field_name,
                                    matched_text=matched_text,
                                    confidence_score=confidence,
                                    role_type=user_role.role_type,
                                    board_date=str(doc_data.get("board_date", "")),
                                )
                            )

                additional_lawyers = doc_data.get("additional_respondent_lawyers", [])
                if additional_lawyers and isinstance(additional_lawyers, list):
                    text_to_search = " ".join(str(lw) for lw in additional_lawyers)
                    for matched_text, confidence in self.find_user_matches_in_text(
                        text_to_search, user_role, "additional_respondent_lawyers"
                    ):
                        matches.append(
                            MatterMatch(
                                case_id=case_id,
                                case_ref=case_ref,
                                match_source="board_data",
                                match_field="additional_respondent_lawyers",
                                matched_text=matched_text,
                                confidence_score=confidence,
                                role_type=user_role.role_type,
                                board_date=str(doc_data.get("board_date", "")),
                            )
                        )

                # Use pre-fetched case details map (no per-doc Firestore call)
                case_details = details_map.get(case_ref) or {}
                case_fields = {
                    "government_pleader": case_details.get("government_pleader", []),
                    "petitioner": case_details.get("petitioner", ""),
                    "respondent": case_details.get("respondent", ""),
                }
                for field_name, field_value in case_fields.items():
                    if isinstance(field_value, list):
                        text_to_search = " ".join(str(item) for item in field_value)
                    else:
                        text_to_search = str(field_value) if field_value else ""
                    if text_to_search:
                        for matched_text, confidence in self.find_user_matches_in_text(
                            text_to_search, user_role, field_name
                        ):
                            matches.append(
                                MatterMatch(
                                    case_id=case_id,
                                    case_ref=case_ref,
                                    match_source="case_details",
                                    match_field=field_name,
                                    matched_text=matched_text,
                                    confidence_score=confidence,
                                    role_type=user_role.role_type,
                                    board_date=str(doc_data.get("board_date", "")),
                                )
                            )

        except Exception as e:
            logging.error(f"Error finding user matters: {e}")

        return sorted(matches, key=lambda m: m.board_date or "", reverse=True)

    def get_matters_summary(self, user_id: str) -> Dict[str, Any]:
        """Get summary of matters for a user"""
        matches = self.find_user_matters(user_id)

        summary = {
            "total_matches": len(matches),
            "high_confidence_matches": len(
                [m for m in matches if m.confidence_score >= 0.9]
            ),
            "medium_confidence_matches": len(
                [m for m in matches if 0.75 <= m.confidence_score < 0.9]
            ),
            "low_confidence_matches": len(
                [m for m in matches if m.confidence_score < 0.75]
            ),
            "match_sources": {
                "board_data": len(
                    [m for m in matches if m.match_source == "board_data"]
                ),
                "case_details": len(
                    [m for m in matches if m.match_source == "case_details"]
                ),
            },
            "recent_matches": len(
                [m for m in matches if m.board_date and m.board_date >= "2024-01-01"]
            ),
        }

        return summary

    def find_user_matters_for_case(
        self, user_id: str, user_role: UserRole, case_id: str
    ) -> List[MatterMatch]:
        """Find user matches for a specific case ID"""
        matches, _ = self._find_matters_and_near_misses_for_case(
            user_id, user_role, case_id
        )
        return matches

    def find_near_miss_matters_for_case(
        self, user_id: str, user_role: UserRole, case_id: str
    ) -> List[MatterMatch]:
        """Matches for this case that fell just short of the acceptance
        threshold -- plausible enough to ask the user to confirm rather
        than silently miss the matter assignment entirely."""
        _, near_misses = self._find_matters_and_near_misses_for_case(
            user_id, user_role, case_id
        )
        return near_misses

    def _find_matters_and_near_misses_for_case(
        self, user_id: str, user_role: UserRole, case_id: str
    ) -> Tuple[List[MatterMatch], List[MatterMatch]]:
        try:
            matches: List[MatterMatch] = []
            near_misses: List[MatterMatch] = []

            # Get the specific case from daily-boards
            doc_ref = self.db.collection("daily-boards").document(case_id)
            doc = doc_ref.get()

            if not doc.exists:
                logging.warning(f"Case {case_id} not found in daily-boards")
                return matches, near_misses

            doc_data = doc.to_dict()
            case_ref = f"{doc_data.get('case_type')}/{doc_data.get('case_no')}/{doc_data.get('case_year')}"
            board_date = str(doc_data.get("board_date", ""))

            def _collect(text_to_search, match_source, field_name, boost=0.0):
                accepted, near_miss = self._score_text_against_role(
                    text_to_search, user_role, field_name
                )
                for matched_text, confidence in accepted:
                    matches.append(
                        MatterMatch(
                            case_id=case_id,
                            case_ref=case_ref,
                            match_source=match_source,
                            match_field=field_name,
                            matched_text=matched_text,
                            confidence_score=min(1.0, confidence + boost),
                            role_type=user_role.role_type,
                            board_date=board_date,
                        )
                    )
                for matched_text, confidence in near_miss:
                    near_misses.append(
                        MatterMatch(
                            case_id=case_id,
                            case_ref=case_ref,
                            match_source=match_source,
                            match_field=field_name,
                            matched_text=matched_text,
                            confidence_score=min(1.0, confidence + boost),
                            role_type=user_role.role_type,
                            board_date=board_date,
                        )
                    )

            # Search board data fields
            board_fields = {
                "petitioner_lawyer": doc_data.get("petitioner_lawyer", ""),
                "respondent_lawyer": doc_data.get("respondent_lawyer", ""),
            }
            for field_name, field_value in board_fields.items():
                if field_value:
                    _collect(field_value, "board_data", field_name)

            # Search additional_respondent_lawyers (array field)
            additional_lawyers = doc_data.get("additional_respondent_lawyers", [])
            if additional_lawyers and isinstance(additional_lawyers, list):
                text_to_search = " ".join(str(lawyer) for lawyer in additional_lawyers)
                _collect(text_to_search, "board_data", "additional_respondent_lawyers")

            # Search normalized case-details fields.
            case_details = self.case_store.get_case_details(case_ref) or {}
            case_fields = {
                "government_pleader": case_details.get("government_pleader", []),
                "petitioner": case_details.get("petitioner", ""),
                "respondent": case_details.get("respondent", ""),
            }
            for field_name, field_value in case_fields.items():
                if field_value:
                    text_to_search = (
                        " ".join(str(item) for item in field_value)
                        if isinstance(field_value, list)
                        else str(field_value)
                    )
                    if text_to_search:
                        _collect(text_to_search, "case_details", field_name, boost=0.05)

            matches.sort(key=lambda x: x.confidence_score, reverse=True)
            near_misses.sort(key=lambda x: x.confidence_score, reverse=True)

            return matches, near_misses

        except Exception as e:
            logging.error(f"Error finding user matters for case {case_id}: {e}")
            return [], []


# ---------------------------------------------------------------------------
# Standalone matching helpers — importable by Board.py, UserManager.py, etc.
# ---------------------------------------------------------------------------

_TITLE_STRIP_RE = re.compile(
    r"\b(shri|smt|ms|mr|mrs|dr|adv|advocate|agp|addl|gp)\b", re.IGNORECASE
)
_PUNCT_RE = re.compile(r"[.,*#\-/;]+")
_WS_RE = re.compile(r"\s+")


def is_bare_initials(text: str) -> bool:
    """True when *text* is nothing but single-letter initials (e.g. "P M J"
    or "p.m.j.") -- the modern Bombay HC board format for government
    lawyers, printed with no surname at all. Callers that see two different
    registered users both match a bare-initials board value should treat it
    as a genuine collision (several AGPs can share 3 initials) rather than
    auto-picking whichever one scored fractionally higher.
    """
    words = re.findall(r"\b\w+\b", (text or "").strip())
    return bool(words) and all(len(w) == 1 for w in words)


def score_name_match(user_name: str, candidate_name: str) -> float:
    """
    Score how well *candidate_name* (a raw field value from a Firestore doc,
    e.g. "SHRI S.D.VYAS, AGP") matches *user_name* (e.g. "S D Vyas").

    Uses the same weighted algorithm as UserManager.match_user_name_to_all_agps:
      - last-name match  35 %
      - initials match   25 %
      - full-word match  25 %
      - sequence score   15 %

    Returns a float in [0, 1].  If the last-name fails to score >= 0.60 the
    function short-circuits and returns 0.0 — identical to the bill-generation
    gate that avoids false positives.
    """
    from difflib import SequenceMatcher as _SM

    if not user_name or not candidate_name:
        return 0.0

    user_norm = _WS_RE.sub(" ", user_name.lower()).strip()
    user_words = re.findall(r"\b\w+\b", user_norm)
    if not user_words:
        return 0.0

    cand_norm = _PUNCT_RE.sub(" ", _TITLE_STRIP_RE.sub(" ", candidate_name.lower()))
    cand_norm = _WS_RE.sub(" ", cand_norm).strip()
    cand_words = [w for w in re.findall(r"\b\w+\b", cand_norm) if w]
    if not cand_words:
        return 0.0

    # Bare-initials candidate (e.g. "P M J" — the modern Bombay HC board
    # format prints only single-letter initials with no surname at all;
    # see Board.py's _GP_INITIALS_PATTERN). The last-name gate below
    # assumes cand_words[-1] is a real surname; for an all-initials
    # candidate that word is just one letter, and the substring-match
    # branch then passes for nearly any name containing that letter
    # anywhere — verified in practice to let a same-initialed but
    # different AGP outscore the correct one (e.g. "Priya Manoj Jadhav"
    # outscoring "Pooja Makarand Joshi Deshpande" against board text
    # "P M J"). Score these on an exact, in-order initials-PREFIX match
    # instead: real board initials are always a left-to-right prefix of
    # the true name's word-initials, never reordered or gapped. No
    # partial credit — a wrong letter anywhere means it isn't this
    # person. The caller is still responsible for checking whether more
    # than one registered person's initials match the same board text
    # (a genuine collision at this length) before treating this as a
    # confident, sole match.
    if all(len(w) == 1 for w in cand_words):
        if len(cand_words) > len(user_words):
            return 0.0
        user_initials_prefix = [w[0] for w in user_words[: len(cand_words)]]
        if cand_words == user_initials_prefix:
            return 0.80
        return 0.0

    # 1. Last-name gate (35 %)
    # Only multi-character words are considered as potential last-name tokens.
    # Single-letter initials (e.g. "S", "D") are not last names and must not
    # be checked via substring matching against the candidate last word — that
    # would cause "d" in "chipade" to pass the gate for unrelated names like
    # "S D Vyas" vs "S D Chipade".
    cand_last = cand_words[-1]
    last_score = 0.0
    for uw in user_words:
        if len(uw) <= 1:
            continue
        if uw == cand_last:
            last_score = 1.0
            break
        elif uw in cand_last or cand_last in uw:
            last_score = max(last_score, 0.8)
        else:
            sim = _SM(None, uw, cand_last).ratio()
            if sim >= 0.75:
                last_score = max(last_score, sim * 0.9)
    if last_score < 0.60:
        return 0.0

    scores = [last_score * 0.35]

    # 2. Initials (25 %)
    user_initials = [w[0] for w in user_words]
    cand_initials = [
        w[0] for w in cand_words if len(w) == 1 or (len(w) == 2 and w.endswith("."))
    ]
    if cand_initials and user_initials:
        matched = sum(
            1
            for i, ci in enumerate(cand_initials)
            if i < len(user_initials) and ci == user_initials[i]
        )
        scores.append((matched / len(user_initials)) * 0.25)
    else:
        scores.append(0.0)

    # 3. Full-word overlap (25 %)
    fw_matches = 0.0
    for uw in user_words:
        for cw in cand_words:
            if len(uw) > 1 and len(cw) > 1:
                if uw == cw:
                    fw_matches += 1
                elif uw in cw or cw in uw:
                    fw_matches += 0.5
    scores.append(min(fw_matches / len(user_words), 1.0) * 0.25)

    # 4. Sequence similarity (15 %)
    scores.append(_SM(None, user_norm, cand_norm).ratio() * 0.15)

    return sum(scores)


def any_name_matches(
    user_name: str,
    candidate_names: List[str],
    threshold: float = 0.50,
) -> bool:
    """
    Return True if *any* name in *candidate_names* scores >= *threshold*
    against *user_name* via :func:`score_name_match`.

    Used by Board.getData (search-orders advocate filter) to apply the same
    matching logic as bill generation without requiring a pre-computed
    variations list.
    """
    return any(
        score_name_match(user_name, name) >= threshold
        for name in candidate_names
        if name and str(name).strip()
    )
