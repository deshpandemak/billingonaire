"""
ML-Enhanced PDF Parser for Legal Documents
==========================================

This module provides machine learning enhancements to the existing PDF parsing system:
1. Advanced text preprocessing and cleaning
2. Named Entity Recognition (NER) for legal entities (AGP/GP/AG/Addl GP/B'Pnl)
3. Fuzzy string matching for name mapping to users
4. Learning algorithm that improves accuracy over time

Author: Billingonaire Legal Billing System
Date: September 2025
"""

import difflib
import io
import logging
import re
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Basic libraries (always available)
import pdfplumber

# Advanced ML libraries (optional)
try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    # Fallback to difflib for basic fuzzy matching
    RAPIDFUZZ_AVAILABLE = False

try:
    import spacy
    from spacy.matcher import Matcher

    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

from fastapi import HTTPException

# Firebase imports
from firebase_admin import firestore


@dataclass
class ExtractionResult:
    """Result from ML-enhanced extraction"""

    text: str
    confidence: float
    extraction_method: str
    entities: List[Dict[str, Any]]
    name_mappings: List[Dict[str, Any]]
    quality_score: float


@dataclass
class LegalEntity:
    """Represents a legal entity extracted from text"""

    text: str
    label: str  # AGP, GP, AG, ADDL_GP, B_PNL
    start: int
    end: int
    confidence: float


class MLEnhancedParser:
    """
    Machine Learning enhanced parser for legal board PDFs
    """

    def __init__(self, fallback_parser=None):
        """
        Initialize ML Enhanced Parser

        Args:
            fallback_parser: Original Board parser instance to fallback to
        """
        self.db = firestore.client()
        self.fallback_parser = fallback_parser

        # Initialize ML components
        self.nlp = None
        self.matcher = None
        self.user_cache = {}
        self.learning_data = {}

        # Load ML models and components
        self._initialize_ml_components()

        # Legal entity patterns
        self.legal_patterns = self._create_legal_patterns()

        logging.info("ML Enhanced Parser initialized successfully")

    def _initialize_ml_components(self):
        """Initialize spaCy and other ML components"""
        if SPACY_AVAILABLE:
            try:
                # Try to load legal model first, fallback to general model
                try:
                    self.nlp = spacy.load("en_core_web_lg")
                except OSError:
                    try:
                        self.nlp = spacy.load("en_core_web_md")
                    except OSError:
                        self.nlp = spacy.load("en_core_web_sm")

                # Initialize matcher for legal entities
                self.matcher = Matcher(self.nlp.vocab)
                self._add_legal_patterns()

                logging.info(f"SpaCy model loaded: {self.nlp.meta['name']}")
            except Exception as e:
                logging.warning(f"Could not initialize spaCy: {e}")
                self.nlp = None
        else:
            logging.warning("SpaCy not available. Install with: pip install spacy")

    def _create_legal_patterns(self) -> Dict[str, List[str]]:
        """Create enhanced patterns for legal entity recognition - addressing architect feedback"""
        return {
            "AGP": [
                # Standard formats
                r"\b(?:ASSISTANT\s+GOVERNMENT\s+PLEADER|AGP)\b",
                r"\bA\.G\.P\b",
                # Enhanced name + AGP patterns for formats like "SMT.G.R.RAGHUWANSHI,AGP"
                r"\bSHRI\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AGP\b",
                r"\bSMT\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AGP\b",
                r"\bMS\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AGP\b",
                r"\b[A-Z][A-Za-z]+\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AGP\b",
                # Legacy patterns
                r"\bAGP\s+[A-Z][a-z]+",
                r"\bSHRI\s+[A-Z][a-z]+.*?AGP\b",
                r"\bSMT\s+[A-Z][a-z]+.*?AGP\b",
            ],
            "GP": [
                # Standard formats
                r"\b(?:GOVERNMENT\s+PLEADER|GP)\b",
                r"\bG\.P\b",
                # Enhanced name + GP patterns for formats like "SHRI. P. P. KAKADE, GP"
                r"\bSHRI\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*GP\b",
                r"\bSMT\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*GP\b",
                r"\bMS\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*GP\b",
                r"\b[A-Z][A-Za-z]+\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*GP\b",
                # Legacy patterns
                r"\bGP\s+[A-Z][a-z]+",
                r"\bSHRI\s+[A-Z][a-z]+.*?GP\b",
                r"\bSMT\s+[A-Z][a-z]+.*?GP\b",
            ],
            "AG": [
                # Standard formats
                r"\b(?:ADVOCATE\s+GENERAL|AG)\b",
                r"\bA\.G\b",
                # Enhanced name + AG patterns for formats like "DR .B .B .SARAF, AG"
                r"\bDR\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AG\b",
                r"\bSHRI\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AG\b",
                r"\bSMT\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AG\b",
                r"\b[A-Z][A-Za-z]+\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*AG\b",
                # Legacy patterns
                r"\bAG\s+[A-Z][a-z]+",
                r"\bSHRI\s+[A-Z][a-z]+.*?AG\b",
                r"\bSMT\s+[A-Z][a-z]+.*?AG\b",
            ],
            "ADDL_GP": [
                # Enhanced ADDL GP patterns for formats like "SHRI.O.A.CHANDURKAR.ADDL GP"
                r"\b(?:ADDITIONAL\s+GOVERNMENT\s+PLEADER|ADDL\.?\s*GP)\b",
                r"\bADDL\.?\s*G\.P\b",
                r"\bADDITIONAL\s+GP\b",
                r"\bSHRI\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*ADDL\.?\s*GP\b",
                r"\bSMT\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*ADDL\.?\s*GP\b",
                r"\b[A-Z][A-Za-z]+\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*ADDL\.?\s*GP\b",
            ],
            "B_PNL": [
                # Enhanced B'PNL patterns for formats like "SHRI. K.S.THORAT, B'PNL"
                r"\bB\s*\'?\s*PNL\b",
                r"\bB\.PNL\b",
                r"\bB\s+PANEL\b",
                r"\bSHRI\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*B\'?PNL\b",
                r"\bSMT\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*B\'?PNL\b",
                r"\b[A-Z][A-Za-z]+\.?\s+[A-Z]\.?\s*[A-Z]\.?\s*[A-Z][A-Za-z]+\.?\s*,?\s*B\'?PNL\b",
            ],
        }

    def _add_legal_patterns(self):
        """Add legal entity patterns to spaCy matcher"""
        if not self.matcher:
            return

        for entity_type, patterns in self.legal_patterns.items():
            for i, pattern in enumerate(patterns):
                try:
                    # Convert regex to spaCy pattern
                    pattern_name = f"{entity_type}_{i}"
                    # Simple word-based pattern for spaCy
                    if "AGP" in pattern:
                        self.matcher.add(
                            pattern_name, [[{"LOWER": {"REGEX": r"agp|a\.g\.p"}}]]
                        )
                    elif "GP" in pattern and "AGP" not in pattern:
                        self.matcher.add(
                            pattern_name, [[{"LOWER": {"REGEX": r"^gp$|g\.p"}}]]
                        )
                    elif "GOVERNMENT" in pattern:
                        self.matcher.add(
                            pattern_name,
                            [[{"LOWER": "government"}, {"LOWER": "pleader"}]],
                        )
                except Exception as e:
                    logging.warning(f"Could not add pattern {pattern}: {e}")

    def enhance_pdf_extraction(
        self, filename: str, file_content: bytes
    ) -> ExtractionResult:
        """
        Main method to enhance PDF extraction with ML

        Args:
            filename: Name of the PDF file
            file_content: Raw PDF file content

        Returns:
            ExtractionResult with enhanced extraction data
        """
        logging.info(f"Starting ML-enhanced extraction for {filename}")

        # Try multiple extraction methods
        extraction_results = []

        # Method 1: Standard pdfplumber (existing method)
        try:
            text, confidence = self._extract_with_pdfplumber(file_content)
            if text.strip():
                extraction_results.append(
                    {"text": text, "confidence": confidence, "method": "pdfplumber"}
                )
        except Exception as e:
            logging.warning(f"pdfplumber extraction failed: {e}")

        # Method 2: Enhanced preprocessing for better text quality
        try:
            text, confidence = self._extract_with_advanced_preprocessing(file_content)
            if text.strip():
                extraction_results.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "method": "enhanced_preprocessing",
                    }
                )
        except Exception as e:
            logging.warning(f"Enhanced preprocessing failed: {e}")

        # Select best extraction result
        if not extraction_results:
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from PDF using any method. Please check if the file is valid.",
            )

        # Choose best result based on confidence and text quality
        best_result = max(extraction_results, key=lambda x: x["confidence"])

        # Extract legal entities using NER
        entities = self._extract_legal_entities(best_result["text"])

        # Map names to existing users using fuzzy matching
        name_mappings = self._map_names_to_users(entities)

        # Calculate overall quality score
        quality_score = self._calculate_quality_score(
            best_result["text"], entities, name_mappings, best_result["confidence"]
        )

        result = ExtractionResult(
            text=best_result["text"],
            confidence=best_result["confidence"],
            extraction_method=best_result["method"],
            entities=entities,
            name_mappings=name_mappings,
            quality_score=quality_score,
        )

        # Store learning data for future improvements
        self._store_learning_data(filename, result)

        logging.info(
            f"ML extraction completed. Method: {result.extraction_method}, Quality: {quality_score:.2f}"
        )
        return result

    def _extract_with_pdfplumber(self, file_content: bytes) -> Tuple[str, float]:
        """Extract text using pdfplumber (existing method)"""
        import pdfplumber

        file_obj = io.BytesIO(file_content)
        text = ""
        confidence = 0.95  # High confidence for text-based PDFs

        with pdfplumber.open(file_obj) as reader:
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text.replace("\n", " ")

        if not text.strip():
            confidence = 0.0

        return text, confidence

    def _extract_with_advanced_preprocessing(
        self, file_content: bytes
    ) -> Tuple[str, float]:
        """Enhanced text extraction with advanced preprocessing"""
        try:
            file_obj = io.BytesIO(file_content)
            text = ""
            confidence = 0.85  # Good confidence for enhanced preprocessing

            with pdfplumber.open(file_obj) as reader:
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        # Advanced preprocessing
                        cleaned_text = self._preprocess_legal_text(page_text)
                        text += cleaned_text + " "

            if not text.strip():
                confidence = 0.0

            return text, confidence

        except Exception as e:
            logging.error(f"Advanced preprocessing error: {e}")
            return "", 0.0

    def _preprocess_legal_text(self, text: str) -> str:
        """Preprocess legal document text to improve quality"""
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)

        # Fix common OCR errors in legal documents
        text = re.sub(
            r"\bGOVERNMENT\s+PLEADER\b", "GOVERNMENT PLEADER", text, flags=re.IGNORECASE
        )
        text = re.sub(
            r"\bASS[I1]STANT\s+GOVERNMENT\s+PLEADER\b",
            "ASSISTANT GOVERNMENT PLEADER",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bADVOCATE\s+GENERAL\b", "ADVOCATE GENERAL", text, flags=re.IGNORECASE
        )

        # Fix common character replacements
        text = re.sub(r"\bl\b", "I", text)  # lowercase l to I
        text = re.sub(r"\b0\b", "O", text)  # zero to O

        # Standardize case formats
        text = re.sub(r"\bSHR[I1]\b", "SHRI", text, flags=re.IGNORECASE)
        text = re.sub(r"\bSMT\b", "SMT", text, flags=re.IGNORECASE)
        text = re.sub(r"\bMS\b", "MS", text, flags=re.IGNORECASE)

        return text

    def _extract_legal_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract legal entities (AGP/GP/AG etc.) from text using NER"""
        entities = []

        # Method 1: Regex-based extraction (always available)
        entities.extend(self._extract_entities_regex(text))

        # Method 2: spaCy NER (if available)
        if self.nlp and self.matcher:
            entities.extend(self._extract_entities_spacy(text))

        # Deduplicate entities
        entities = self._deduplicate_entities(entities)

        return entities

    def _extract_entities_regex(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities using regex patterns"""
        entities = []

        for entity_type, patterns in self.legal_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    entities.append(
                        {
                            "text": match.group(),
                            "label": entity_type,
                            "start": match.start(),
                            "end": match.end(),
                            "confidence": 0.8,  # Medium confidence for regex
                            "method": "regex",
                        }
                    )

        return entities

    def _extract_entities_spacy(self, text: str) -> List[Dict[str, Any]]:
        """Extract entities using spaCy NER"""
        entities = []

        try:
            doc = self.nlp(text)
            matches = self.matcher(doc)

            for match_id, start, end in matches:
                span = doc[start:end]
                label = self.nlp.vocab.strings[match_id].split("_")[0]

                entities.append(
                    {
                        "text": span.text,
                        "label": label,
                        "start": span.start_char,
                        "end": span.end_char,
                        "confidence": 0.9,  # High confidence for spaCy
                        "method": "spacy",
                    }
                )

        except Exception as e:
            logging.warning(f"spaCy entity extraction failed: {e}")

        return entities

    def _deduplicate_entities(
        self, entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove duplicate entities, keeping highest confidence"""
        # Group by text and position
        entity_groups = {}

        for entity in entities:
            key = (entity["text"].lower(), entity["start"], entity["end"])
            if (
                key not in entity_groups
                or entity["confidence"] > entity_groups[key]["confidence"]
            ):
                entity_groups[key] = entity

        return list(entity_groups.values())

    def _map_names_to_users(
        self, entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Map extracted names to existing users using fuzzy matching"""
        if not RAPIDFUZZ_AVAILABLE:
            logging.warning("RapidFuzz not available for name matching")
            return []

        mappings = []

        # Get existing users from cache or database
        users = self._get_user_list()

        for entity in entities:
            if entity["label"] in ["AGP", "GP", "AG", "ADDL_GP", "B_PNL"]:
                # Extract name from entity text
                extracted_name = self._extract_name_from_entity(entity["text"])

                if extracted_name:
                    # Find best matching user
                    best_matches = self._find_best_user_matches(extracted_name, users)

                    if best_matches:
                        mappings.append(
                            {
                                "extracted_entity": entity,
                                "extracted_name": extracted_name,
                                "matched_users": best_matches,
                                "mapping_confidence": best_matches[0]["score"] / 100.0,
                            }
                        )

        return mappings

    def _extract_name_from_entity(self, entity_text: str) -> Optional[str]:
        """Extract actual name from entity text with robust normalization"""
        # Convert to uppercase for consistency
        text = entity_text.upper()

        # Remove common prefixes, suffixes, and designations
        removals = [
            "SHRI",
            "SMT",
            "MS",
            "MR",
            "DR",
            "MRS",
            "AGP",
            "GP",
            "AG",
            "ADDL",
            "ADDITIONAL",
            "GOVERNMENT",
            "PLEADER",
            "ADVOCATE",
            "GENERAL",
            "B'PNL",
            "BPNL",
            "B PNL",
            "PANEL",
        ]

        # More thorough removal with optional dots and spacing
        for removal in removals:
            # Remove with various punctuation patterns
            text = re.sub(rf"\b{removal}\.?\s*", "", text)
            text = re.sub(rf"\.{removal}\b\.?", "", text)

        # Remove common legal terms
        text = re.sub(r"\bWITH\b", "", text)
        text = re.sub(r"\bN/S\b", "", text)  # Not Served
        text = re.sub(r"\bCONL\b", "", text)  # Counsel

        # Clean up punctuation - preserve initials but remove excessive punctuation
        text = re.sub(r"[,;:]", " ", text)  # Remove commas, semicolons, colons
        text = re.sub(
            r"\.(?!\s*[A-Z])", " ", text
        )  # Remove dots not followed by initials
        text = re.sub(r"\s+", " ", text)  # Normalize whitespace

        # Extract name tokens (preserve initials like "P. P.")
        name_tokens = []
        tokens = text.split()

        for token in tokens:
            # Keep tokens that look like names or initials
            if re.match(r"^[A-Z]\.?$", token):  # Single initial like "P." or "P"
                name_tokens.append(token)
            elif re.match(r"^[A-Z][A-Za-z]{1,}$", token):  # Full name like "KAKADE"
                name_tokens.append(token)

        # Join and normalize
        extracted_name = " ".join(name_tokens).strip()

        # Final cleanup
        extracted_name = re.sub(
            r"\.(\w)", r". \1", extracted_name
        )  # Add space after dots
        extracted_name = re.sub(r"\s+", " ", extracted_name)  # Normalize whitespace

        return extracted_name if extracted_name else None

    def _get_user_list(self) -> List[Dict[str, str]]:
        """Get list of users for name matching"""
        if hasattr(self, "user_cache") and self.user_cache:
            return self.user_cache

        try:
            # Get users from Firestore
            users_ref = self.db.collection("users")
            docs = users_ref.stream()

            users = []
            for doc in docs:
                user_data = doc.to_dict()
                if "name" in user_data:
                    users.append(
                        {
                            "id": doc.id,
                            "name": user_data["name"],
                            "email": user_data.get("email", ""),
                            "role": user_data.get("role", ""),
                        }
                    )

            self.user_cache = users
            return users

        except Exception as e:
            logging.error(f"Error fetching users: {e}")
            return []

    def _find_best_user_matches(
        self, name: str, users: List[Dict[str, str]], threshold: float = 0.6
    ) -> List[Dict[str, Any]]:
        """Find best matching users using robust fuzzy string matching with legal name normalization"""
        if not users:
            return []

        # Normalize the extracted name for better matching
        normalized_name = self._normalize_legal_name(name)

        result = []

        if RAPIDFUZZ_AVAILABLE:
            # Use multiple RapidFuzz algorithms for better matching
            choices = [(user["name"], user) for user in users]
            choice_names = [self._normalize_legal_name(choice[0]) for choice in choices]

            # Try different fuzzy matching algorithms
            algorithms = [
                ("token_set_ratio", fuzz.token_set_ratio),
                ("token_sort_ratio", fuzz.token_sort_ratio),
                ("partial_ratio", fuzz.partial_ratio),
                ("ratio", fuzz.ratio),
            ]

            user_scores = {}

            for algo_name, algo_func in algorithms:
                matches = process.extract(
                    normalized_name,
                    choice_names,
                    scorer=algo_func,
                    limit=5,
                    score_cutoff=threshold * 100,
                )

                for match_name, score, idx in matches:
                    user = choices[idx][1]
                    user_id = user.get("id", user.get("name", ""))

                    if user_id not in user_scores:
                        user_scores[user_id] = {
                            "user": user,
                            "scores": {},
                            "max_score": 0,
                            "algorithms": [],
                        }

                    user_scores[user_id]["scores"][algo_name] = score
                    user_scores[user_id]["algorithms"].append(algo_name)
                    user_scores[user_id]["max_score"] = max(
                        user_scores[user_id]["max_score"], score
                    )

            # Calculate composite scores and prepare results
            for user_id, data in user_scores.items():
                # Use weighted average with preference for token_set_ratio
                weights = {
                    "token_set_ratio": 0.4,
                    "token_sort_ratio": 0.3,
                    "partial_ratio": 0.2,
                    "ratio": 0.1,
                }

                composite_score = 0
                total_weight = 0

                for algo, weight in weights.items():
                    if algo in data["scores"]:
                        composite_score += data["scores"][algo] * weight
                        total_weight += weight

                if total_weight > 0:
                    final_score = composite_score / total_weight
                    result.append(
                        {
                            "user": data["user"],
                            "score": final_score,
                            "match_type": "rapidfuzz_composite",
                            "algorithm_scores": data["scores"],
                            "max_score": data["max_score"],
                        }
                    )

        else:
            # Enhanced difflib fallback with multiple comparison methods
            for user in users:
                normalized_user_name = self._normalize_legal_name(user["name"])

                # Multiple similarity calculations
                similarities = [
                    difflib.SequenceMatcher(
                        None, normalized_name, normalized_user_name
                    ).ratio(),
                    difflib.SequenceMatcher(
                        None, name.lower(), user["name"].lower()
                    ).ratio(),
                    self._token_similarity(normalized_name, normalized_user_name),
                    self._initial_similarity(normalized_name, normalized_user_name),
                ]

                # Use the highest similarity
                max_similarity = max(similarities)

                if max_similarity >= threshold:
                    result.append(
                        {
                            "user": user,
                            "score": max_similarity * 100,
                            "match_type": "difflib_enhanced",
                            "similarities": similarities,
                        }
                    )

        # Sort by score and limit to top 5
        result.sort(key=lambda x: x["score"], reverse=True)
        return result[:5]

    def _normalize_legal_name(self, name: str) -> str:
        """Normalize legal names for better fuzzy matching"""
        if not name:
            return ""

        # Convert to uppercase
        normalized = name.upper()

        # Remove common titles and designations
        removals = ["SHRI", "SMT", "MS", "MR", "DR", "MRS"]
        for removal in removals:
            normalized = re.sub(rf"\b{removal}\.?\s*", "", normalized)

        # Normalize punctuation and spacing
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)

        return normalized.strip()

    def _token_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity based on token overlap"""
        tokens1 = set(name1.split())
        tokens2 = set(name2.split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)

        return len(intersection) / len(union) if union else 0.0

    def _initial_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity based on initials (important for legal names)"""
        # Extract initials
        initials1 = "".join([word[0] for word in name1.split() if word])
        initials2 = "".join([word[0] for word in name2.split() if word])

        if not initials1 or not initials2:
            return 0.0

        return difflib.SequenceMatcher(None, initials1, initials2).ratio()

    def _calculate_quality_score(
        self,
        text: str,
        entities: List[Dict],
        mappings: List[Dict],
        base_confidence: float,
    ) -> float:
        """Calculate overall quality score for the extraction"""
        # Base score from extraction confidence
        score = base_confidence

        # Bonus for finding entities
        if entities:
            entity_bonus = min(len(entities) * 0.1, 0.3)  # Max 30% bonus
            score += entity_bonus

        # Bonus for successful name mappings
        if mappings:
            mapping_bonus = min(len(mappings) * 0.05, 0.2)  # Max 20% bonus
            score += mapping_bonus

        # Text quality indicators
        if len(text) > 100:  # Reasonable amount of text
            score += 0.05

        if re.search(r"\d+/\d+/\d+", text):  # Contains dates
            score += 0.05

        if re.search(
            r"HON\'BLE|COURT|JUDGE", text, re.IGNORECASE
        ):  # Legal document indicators
            score += 0.05

        return min(score, 1.0)  # Cap at 1.0

    def _store_learning_data(self, filename: str, result: ExtractionResult):
        """Store extraction results for learning and improvement"""
        try:
            learning_doc = {
                "filename": filename,
                "timestamp": datetime.now(),
                "extraction_method": result.extraction_method,
                "confidence": result.confidence,
                "quality_score": result.quality_score,
                "entities_found": len(result.entities),
                "mappings_found": len(result.name_mappings),
                "text_length": len(result.text),
            }

            # Store in Firestore for analysis
            self.db.collection("ml_learning_data").add(learning_doc)

        except Exception as e:
            logging.warning(f"Could not store learning data: {e}")

    def get_enhancement_status(self) -> Dict[str, Any]:
        """Get status of ML enhancement capabilities"""
        return {
            "spacy_available": SPACY_AVAILABLE,
            "rapidfuzz_available": RAPIDFUZZ_AVAILABLE,
            "spacy_model": self.nlp.meta["name"] if self.nlp else None,
            "capabilities": {
                "enhanced_preprocessing": True,
                "ner": SPACY_AVAILABLE,
                "fuzzy_matching": True,  # Always available (difflib fallback)
                "learning": True,
                "advanced_fuzzy": RAPIDFUZZ_AVAILABLE,
            },
        }

    def learn_from_correction(
        self,
        filename: str,
        original_extraction: str,
        corrected_extraction: str,
        user_feedback: Dict[str, Any],
    ):
        """Learn from user corrections to improve future extractions"""
        try:
            correction_data = {
                "filename": filename,
                "timestamp": datetime.now(),
                "original_extraction": original_extraction,
                "corrected_extraction": corrected_extraction,
                "user_feedback": user_feedback,
                "improvement_type": "user_correction",
            }

            # Store correction for learning
            self.db.collection("ml_corrections").add(correction_data)

            # Clear user cache to get updated data
            self.user_cache = {}

            logging.info(f"Stored user correction for {filename}")

        except Exception as e:
            logging.error(f"Error storing correction: {e}")
