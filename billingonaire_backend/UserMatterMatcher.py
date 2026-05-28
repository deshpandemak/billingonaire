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
        """Calculate fuzzy matching score between two names - enhanced for legal name variations"""
        if not name1 or not name2:
            return 0.0

        # Normalize both names
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        if norm1 == norm2:
            return 1.0

        import re
        from difflib import SequenceMatcher

        # Extract words from both names
        words1 = re.findall(r"\b\w+\b", norm1)
        words2 = re.findall(r"\b\w+\b", norm2)

        if not words1 or not words2:
            return 0.0

        scores = []

        # 1. Last name matching (but more flexible for legal names)
        last_name_score = 0.0
        if len(words1) > 0 and len(words2) > 0:
            last1 = words1[-1]
            last2 = words2[-1]

            if last1 == last2:
                last_name_score = 1.0
            elif last1 in last2 or last2 in last1:
                last_name_score = 0.8
            else:
                # Check for close spelling variations
                word_similarity = SequenceMatcher(None, last1, last2).ratio()
                if word_similarity >= 0.75:
                    last_name_score = word_similarity * 0.9
                else:
                    # For legal names, check if the "last name" in name2 could be a middle name in name1
                    # E.g., "P.M.Joshi" vs "Pooja Makarand Joshi Deshpande"
                    if (
                        len(words1) >= 3 and last2 in words1[:-1]
                    ):  # last2 appears in name1 except actual last name
                        last_name_score = (
                            0.7  # Good score for middle name used as last name
                        )

        scores.append(("last_name", last_name_score, 0.25))  # Reduced weight

        # 2. Initials pattern matching (higher priority for legal names)
        initials1 = [word[0] for word in words1]
        initials2 = [word[0] for word in words2]

        initials_match = 0.0
        if initials1 and initials2:
            # Check if name2 initials are a prefix of name1 initials
            if len(initials2) <= len(initials1):
                matches = sum(
                    1
                    for i, init2 in enumerate(initials2)
                    if i < len(initials1) and init2 == initials1[i]
                )
                if matches > 0:
                    initials_match = matches / len(initials1)
                    # Boost score if we have strong initials match
                    if initials_match >= 0.5:
                        initials_match = min(1.0, initials_match + 0.2)

        scores.append(("initials", initials_match, 0.35))  # Increased weight

        # 3. Full word matches (check for shared names)
        full_word_matches = 0
        for word1 in words1:
            for word2 in words2:
                if len(word1) > 1 and len(word2) > 1:
                    if word1 == word2:
                        full_word_matches += 1
                    elif word1 in word2 or word2 in word1:
                        full_word_matches += 0.5

        if words1:
            full_word_score = min(full_word_matches / len(words1), 1.0)
            scores.append(("full_words", full_word_score, 0.25))

        # 4. Overall sequence similarity
        seq_score = SequenceMatcher(None, norm1, norm2).ratio()
        scores.append(("sequence", seq_score, 0.15))

        # Calculate weighted combined score
        combined_score = sum(score * weight for _, score, weight in scores)

        # Special case: If initials match very well but last name doesn't,
        # still give a reasonable score (for cases like "P.M.Joshi" -> "Pooja Makarand Joshi Deshpande")
        initials_score = next(
            (score for name, score, _ in scores if name == "initials"), 0
        )
        last_name_score = next(
            (score for name, score, _ in scores if name == "last_name"), 0
        )

        if initials_score >= 0.6 and last_name_score < 0.5:
            # Boost the score for strong initials match even with weak last name match
            combined_score = min(1.0, combined_score + 0.2)

        return combined_score

    def extract_role_from_text(self, text: str) -> Optional[str]:
        """Extract government pleader role from text using pattern matching"""
        if not text:
            return None

        for role, patterns in self.role_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return role

        return None

    def find_user_matches_in_text(
        self, text: str, user_role: UserRole, field_context: str = ""
    ) -> List[Tuple[str, float]]:
        """Find user name matches in given text with role-aware scoring"""
        if not text:
            return []

        matches = []

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
                matches.append((name_var, final_score))
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
                    matches.append((segment.strip(), final_score))

        return matches

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
        try:
            matches = []

            # Get the specific case from daily-boards
            doc_ref = self.db.collection("daily-boards").document(case_id)
            doc = doc_ref.get()

            if not doc.exists:
                logging.warning(f"Case {case_id} not found in daily-boards")
                return matches

            doc_data = doc.to_dict()
            case_ref = f"{doc_data.get('case_type')}/{doc_data.get('case_no')}/{doc_data.get('case_year')}"

            # Search board data fields
            board_fields = {
                "petitioner_lawyer": doc_data.get("petitioner_lawyer", ""),
                "respondent_lawyer": doc_data.get("respondent_lawyer", ""),
            }

            for field_name, field_value in board_fields.items():
                if field_value:
                    text_matches = self.find_user_matches_in_text(
                        field_value, user_role, field_name
                    )
                    for matched_text, confidence in text_matches:
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

            # Search additional_respondent_lawyers (array field)
            additional_lawyers = doc_data.get("additional_respondent_lawyers", [])
            if additional_lawyers and isinstance(additional_lawyers, list):
                # Join array into searchable text
                text_to_search = " ".join(str(lawyer) for lawyer in additional_lawyers)
                text_matches = self.find_user_matches_in_text(
                    text_to_search, user_role, "additional_respondent_lawyers"
                )
                for matched_text, confidence in text_matches:
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

            # Search normalized case-details fields.
            case_details = self.case_store.get_case_details(case_ref) or {}
            case_fields = {
                "government_pleader": case_details.get("government_pleader", []),
                "petitioner": case_details.get("petitioner", ""),
                "respondent": case_details.get("respondent", ""),
            }

            for field_name, field_value in case_fields.items():
                if field_value:
                    if isinstance(field_value, list):
                        text_to_search = " ".join(str(item) for item in field_value)
                    else:
                        text_to_search = str(field_value)

                    if text_to_search:
                        text_matches = self.find_user_matches_in_text(
                            text_to_search, user_role, field_name
                        )
                        for matched_text, confidence in text_matches:
                            boosted_confidence = min(1.0, confidence + 0.05)
                            matches.append(
                                MatterMatch(
                                    case_id=case_id,
                                    case_ref=case_ref,
                                    match_source="case_details",
                                    match_field=field_name,
                                    matched_text=matched_text,
                                    confidence_score=boosted_confidence,
                                    role_type=user_role.role_type,
                                    board_date=str(doc_data.get("board_date", "")),
                                )
                            )

            # Sort by confidence and remove duplicates
            matches.sort(key=lambda x: x.confidence_score, reverse=True)

            return matches

        except Exception as e:
            logging.error(f"Error finding user matters for case {case_id}: {e}")
            return []
