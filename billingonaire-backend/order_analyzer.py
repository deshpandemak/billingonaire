"""
Order Document Analysis System
=============================

This module provides machine learning capabilities for analyzing court order documents:
1. Classification of orders as ADJOURNED, HEARD & ADJOURNED, or DISPOSED OFF
2. Entity extraction for petitioners, respondents, AGP names, and dates
3. Integration with existing ML-enhanced parser infrastructure

Author: Billingonaire Legal Billing System
Date: September 2025
"""

import logging
import re
import io
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import json

# Basic libraries
import pdfplumber

# Advanced ML libraries (optional)
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

# Firebase imports
from firebase_admin import firestore
from fastapi import HTTPException

# Import existing ML parser for base functionality
from ml_enhanced_parser import MLEnhancedParser, ExtractionResult


@dataclass
class OrderAnalysisResult:
    """Result from order document analysis"""
    order_category: str  # ADJOURNED, HEARD_AND_ADJOURNED, DISPOSED_OFF
    category_confidence: float
    petitioners: List[Dict[str, Any]]
    respondents: List[Dict[str, Any]]
    agp_names: List[Dict[str, Any]]
    dates: List[Dict[str, Any]]
    order_text: str
    key_phrases: List[str]
    next_hearing_date: Optional[str]
    disposal_reason: Optional[str]


class OrderDocumentAnalyzer:
    """
    Specialized analyzer for court order documents
    Extends ML-enhanced parser for order-specific analysis
    """
    
    def __init__(self):
        """Initialize Order Document Analyzer"""
        self.db = firestore.client()
        self.ml_parser = MLEnhancedParser()
        
        # Order classification patterns
        self.order_patterns = self._create_order_patterns()
        
        # Entity extraction patterns
        self.entity_patterns = self._create_entity_patterns()
        
        # Date extraction patterns
        self.date_patterns = self._create_date_patterns()
        
        logging.info("Order Document Analyzer initialized successfully")
    
    def _create_order_patterns(self) -> Dict[str, List[str]]:
        """Create patterns for order classification"""
        return {
            'DISPOSED_OFF': [
                # Direct disposal phrases
                r'\bdisposed?\s+off?\b',
                r'\bdisposal\b',
                r'\binfructuous\b',
                r'\bwithdrawn?\b',
                r'\bdismissed?\b',
                r'\ballowed?\s+and\s+disposed?\s+off?\b',
                r'\bfinal\s+disposal\b',
                r'\bpetitions?\s+(?:are\s+)?disposed?\s+off?\b',
                r'\bmatter\s+(?:is\s+)?disposed?\s+off?\b',
                r'\bcase\s+(?:is\s+)?disposed?\s+off?\b',
                # Final orders
                r'\bfinal\s+order\b',
                r'\bfinal\s+judgment\b',
                r'\bsuit\s+dismissed?\b',
                r'\bpetition\s+dismissed?\b',
                r'\bwrit\s+dismissed?\b'
            ],
            'ADJOURNED': [
                # Adjournment phrases
                r'\bstand\s+over\s+to\b',
                r'\badjourned?\s+to\b',
                r'\blist(?:ed)?\s+(?:the\s+same\s+)?on\b',
                r'\bnext\s+(?:date|hearing)\s+(?:of|on)\b',
                r'\bpost(?:poned?)?\s+to\b',
                r'\breschedule[d]?\s+(?:to|for)\b',
                r'\bdeferred?\s+to\b',
                # Administrative adjournments
                r'\bwrongly\s+on\s+board\b',
                r'\bremove\s+from\s+(?:the\s+)?board\b',
                r'\bpaucity\s+of\s+time\b',
                r'\bcould\s+not\s+be\s+taken\s+up\b',
                r'\btime\s+(?:sought|requested)\b',
                r'\bseeks?\s+time\b',
                r'\btake\s+instructions\b',
                # Future hearing indicators
                r'\bto\s+be\s+listed\s+on\b',
                r'\bfor\s+(?:final\s+)?hearing\s+(?:at|on)\b',
                r'\bnext\s+date\s+(?:is\s+)?fixed\b',
                r'\binterim\s+order.*?to\s+continue\b'
            ],
            'HEARD_AND_ADJOURNED': [
                # Partial hearing phrases
                r'\bheard?\s+and\s+adjourned?\b',
                r'\bpartly\s+heard?\b',
                r'\bpartial\s+hearing\b',
                r'\bheard?\s+partially\b',
                r'\barguments?\s+(?:heard?|concluded?)\s+(?:and\s+)?adjourned?\b',
                r'\bafter\s+hearing.*?adjourned?\b',
                r'\bmatter\s+heard?\s+and\s+(?:kept\s+for|posted\s+to)\b',
                r'\bheard?\s+(?:the\s+)?(?:parties?|counsel)\s+and\s+adjourned?\b'
            ]
        }
    
    def _create_entity_patterns(self) -> Dict[str, List[str]]:
        """Create patterns for entity extraction"""
        return {
            'PETITIONER': [
                # Standard petitioner patterns
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s*\.{3,}\s*)?\.{3,}\s*Petitioners?',
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s*\.{3,}\s*)?\.{3,}\s*Applicants?',
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s*\.{3,}\s*)?\.{3,}\s*Appellants?',
                # Multiple petition formats
                r'Petitioners?\s*:\s*([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)',
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s+vs?\.|\s+versus)',
                # Alternative formats
                r'([A-Z][a-zA-Z\s\.]+)\s+\.{3,}\s*PETITIONER',
                r'In\s+the\s+matter\s+of\s*:?\s*([A-Z][a-zA-Z\s\.]+)'
            ],
            'RESPONDENT': [
                # Standard respondent patterns
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s*\.{3,}\s*)?\.{3,}\s*Respondents?',
                r'([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)(?:\s*\.{3,}\s*)?\.{3,}\s*Defendants?',
                r'The\s+State\s+Of\s+Maharashtra.*?\.{3,}\s*Respondents?',
                # Versus patterns
                r'(?:vs?\.|\bversus\b)\s*([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)',
                # State patterns
                r'(The\s+State\s+Of\s+Maharashtra[^\.]*?)(?:\s*\.{3,}\s*)?\.{3,}\s*Respondents?',
                r'Respondents?\s*:\s*([A-Z][a-zA-Z\s\.]+(?:\s+And\s+Ors\.?)?)'
            ],
            'AGP_ENHANCED': [
                # Enhanced AGP patterns building on existing parser
                r'(?:Smt\.?|Shri\.?|Ms\.?|Mr\.?)\s+([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+\.?)\s*,?\s*AGP',
                r'(?:Smt\.?|Shri\.?|Ms\.?|Mr\.?)\s+([A-Z][a-zA-Z\s\.]+),?\s*AGP',
                r'([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+\.?)\s*,?\s*AGP',
                r'AGP\s+([A-Z][a-zA-Z\s\.]+)',
                # Additional patterns for GP
                r'(?:Smt\.?|Shri\.?|Ms\.?|Mr\.?)\s+([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+\.?)\s*,?\s*(?:Addl\.?\s*)?GP',
                r'([A-Z]\.?\s*[A-Z]\.?\s*[A-Za-z]+\.?)\s*,?\s*(?:Addl\.?\s*)?GP'
            ]
        }
    
    def _create_date_patterns(self) -> List[str]:
        """Create patterns for date extraction"""
        return [
            # Standard date formats
            r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})\b',
            r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',
            r'\b(\d{1,2})-(\d{1,2})-(\d{4})\b',
            r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b',
            # Legal document specific date formats
            r'\bDATE\s*:\s*(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})',
            r'\bon\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})',
            r'\bto\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})',
            # Numeric formats
            r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b',
            r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b'
        ]
    
    def analyze_order_document(self, filename: str, file_content: bytes) -> OrderAnalysisResult:
        """
        Main method to analyze order document
        
        Args:
            filename: Name of the PDF file
            file_content: Raw PDF file content
            
        Returns:
            OrderAnalysisResult with comprehensive analysis
        """
        logging.info(f"Starting order document analysis for {filename}")
        
        # First, extract text using existing ML parser
        extraction_result = self.ml_parser.enhance_pdf_extraction(filename, file_content)
        
        if not extraction_result or not extraction_result.text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from order document"
            )
        
        text = extraction_result.text
        
        # 1. Classify order category
        order_category, category_confidence = self._classify_order(text)
        
        # 2. Extract entities
        petitioners = self._extract_petitioners(text)
        respondents = self._extract_respondents(text)
        agp_names = self._extract_agp_names(text, extraction_result.entities)
        
        # 3. Extract dates
        dates = self._extract_dates(text)
        
        # 4. Extract key phrases and specific information
        key_phrases = self._extract_key_phrases(text, order_category)
        next_hearing_date = self._extract_next_hearing_date(text)
        disposal_reason = self._extract_disposal_reason(text) if order_category == 'DISPOSED_OFF' else None
        
        result = OrderAnalysisResult(
            order_category=order_category,
            category_confidence=category_confidence,
            petitioners=petitioners,
            respondents=respondents,
            agp_names=agp_names,
            dates=dates,
            order_text=text,
            key_phrases=key_phrases,
            next_hearing_date=next_hearing_date,
            disposal_reason=disposal_reason
        )
        
        logging.info(f"Order analysis completed. Category: {order_category}, Confidence: {category_confidence:.2f}")
        return result
    
    def _classify_order(self, text: str) -> Tuple[str, float]:
        """Classify order into categories with confidence score"""
        scores = {}
        
        for category, patterns in self.order_patterns.items():
            score = 0
            matches = 0
            
            for pattern in patterns:
                regex_matches = re.findall(pattern, text, re.IGNORECASE)
                if regex_matches:
                    matches += len(regex_matches)
                    # Weight certain patterns higher
                    if 'disposed' in pattern.lower():
                        score += len(regex_matches) * 2
                    elif 'stand over' in pattern.lower():
                        score += len(regex_matches) * 1.5
                    else:
                        score += len(regex_matches)
            
            scores[category] = {
                'score': score,
                'matches': matches,
                'confidence': min(score / 10.0, 1.0)  # Normalize to 0-1
            }
        
        # Determine best category
        if not any(scores[cat]['score'] > 0 for cat in scores):
            return 'ADJOURNED', 0.5  # Default assumption
        
        best_category = max(scores.keys(), key=lambda x: scores[x]['score'])
        confidence = scores[best_category]['confidence']
        
        # Boost confidence for clear indicators
        if best_category == 'DISPOSED_OFF' and scores[best_category]['score'] >= 2:
            confidence = min(confidence * 1.2, 1.0)
        
        return best_category, confidence
    
    def _extract_petitioners(self, text: str) -> List[Dict[str, Any]]:
        """Extract petitioner names and information"""
        petitioners = []
        
        for pattern in self.entity_patterns['PETITIONER']:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    name = match.group(1).strip() if match.groups() else match.group().strip()
                    # Clean up the name
                    name = re.sub(r'\s+', ' ', name)
                    name = re.sub(r'^(Shri\.?|Smt\.?|Ms\.?|Mr\.?)\s+', '', name, flags=re.IGNORECASE)
                    
                    if name and len(name) > 2:
                        petitioners.append({
                            'name': name,
                            'type': 'PETITIONER',
                            'raw_text': match.group(),
                            'start': match.start(),
                            'end': match.end(),
                            'confidence': 0.9
                        })
                except IndexError:
                    logging.warning(f"Pattern {pattern} matched but has no capturing groups")
                    continue
        
        return self._deduplicate_entities(petitioners)
    
    def _extract_respondents(self, text: str) -> List[Dict[str, Any]]:
        """Extract respondent names and information"""
        respondents = []
        
        for pattern in self.entity_patterns['RESPONDENT']:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    name = match.group(1).strip() if match.groups() else match.group().strip()
                    # Clean up the name
                    name = re.sub(r'\s+', ' ', name)
                    name = re.sub(r'^(The\s+)?State\s+Of\s+Maharashtra.*', 'State Of Maharashtra', name, flags=re.IGNORECASE)
                    
                    if name and len(name) > 2:
                        respondents.append({
                            'name': name,
                            'type': 'RESPONDENT',
                            'raw_text': match.group(),
                            'start': match.start(),
                            'end': match.end(),
                            'confidence': 0.9
                        })
                except IndexError:
                    logging.warning(f"Pattern {pattern} matched but has no capturing groups")
                    continue
        
        return self._deduplicate_entities(respondents)
    
    def _extract_agp_names(self, text: str, existing_entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract AGP names using enhanced patterns and existing ML results"""
        agp_names = []
        
        # Use existing ML parser results
        for entity in existing_entities:
            if entity.get('label') in ['AGP', 'GP', 'AG', 'ADDL_GP', 'B_PNL']:
                agp_names.append({
                    'name': entity.get('text', ''),
                    'type': entity.get('label', 'AGP'),
                    'raw_text': entity.get('text', ''),
                    'start': entity.get('start', 0),
                    'end': entity.get('end', 0),
                    'confidence': entity.get('confidence', 0.8),
                    'source': 'ml_parser'
                })
        
        # Enhance with additional patterns
        for pattern in self.entity_patterns['AGP_ENHANCED']:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                name = match.group(1).strip()
                # Clean up the name
                name = re.sub(r'\s+', ' ', name)
                
                if name and len(name) > 1:
                    agp_names.append({
                        'name': name,
                        'type': 'AGP',
                        'raw_text': match.group(),
                        'start': match.start(),
                        'end': match.end(),
                        'confidence': 0.85,
                        'source': 'enhanced_patterns'
                    })
        
        return self._deduplicate_entities(agp_names)
    
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
                    dates.append({
                        'raw_date': raw_date,
                        'normalized_date': normalized_date,
                        'start': match.start(),
                        'end': match.end(),
                        'confidence': 0.9
                    })
        
        return self._deduplicate_dates(dates)
    
    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize date string to standard format"""
        try:
            # Common date format patterns
            patterns = [
                r'(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})',
                r'(\d{1,2})/(\d{1,2})/(\d{4})',
                r'(\d{1,2})-(\d{1,2})-(\d{4})',
                r'(\d{4})-(\d{1,2})-(\d{1,2})'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, date_str, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        # Handle different formats
                        if groups[1].isalpha():  # Month name format
                            month_map = {
                                'january': '01', 'february': '02', 'march': '03',
                                'april': '04', 'may': '05', 'june': '06',
                                'july': '07', 'august': '08', 'september': '09',
                                'october': '10', 'november': '11', 'december': '12'
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
        
        if order_category == 'DISPOSED_OFF':
            disposal_phrases = [
                r'disposed?\s+off?\s+as\s+[^.]*',
                r'petition\s+is\s+dismissed?[^.]*',
                r'final\s+disposal[^.]*',
                r'matter\s+(?:is\s+)?disposed?\s+off?[^.]*'
            ]
            for pattern in disposal_phrases:
                matches = re.findall(pattern, text, re.IGNORECASE)
                key_phrases.extend(matches)
        
        elif order_category == 'ADJOURNED':
            adjournment_phrases = [
                r'stand\s+over\s+to\s+[^.]*',
                r'list(?:ed)?\s+(?:the\s+same\s+)?on\s+[^.]*',
                r'next\s+(?:date|hearing)\s+[^.]*',
                r'interim\s+order[^.]*to\s+continue[^.]*'
            ]
            for pattern in adjournment_phrases:
                matches = re.findall(pattern, text, re.IGNORECASE)
                key_phrases.extend(matches)
        
        return [phrase.strip() for phrase in key_phrases if phrase.strip()]
    
    def _extract_next_hearing_date(self, text: str) -> Optional[str]:
        """Extract next hearing date if mentioned"""
        next_date_patterns = [
            r'stand\s+over\s+to\s+([^.]+)',
            r'list(?:ed)?\s+(?:the\s+same\s+)?on\s+([^.]+)',
            r'next\s+(?:date|hearing)\s+(?:is\s+)?(?:fixed\s+)?(?:on\s+)?([^.]+)',
            r'to\s+be\s+listed\s+on\s+([^.]+)'
        ]
        
        for pattern in next_date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                # Clean up the date string
                date_str = re.sub(r'[,.].*$', '', date_str)  # Remove trailing content
                normalized = self._normalize_date(date_str)
                return normalized if normalized else date_str
        
        return None
    
    def _extract_disposal_reason(self, text: str) -> Optional[str]:
        """Extract reason for disposal if order is disposed off"""
        disposal_patterns = [
            r'disposed?\s+off?\s+as\s+([^.]+)',
            r'dismissed?\s+as\s+([^.]+)',
            r'petition\s+(?:is\s+)?dismissed?\s+([^.]*)',
            r'withdrawn\s+([^.]*)'
        ]
        
        for pattern in disposal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                reason = match.group(1).strip()
                # Clean up the reason
                reason = re.sub(r'^being\s+', '', reason, flags=re.IGNORECASE)
                return reason if reason else None
        
        return None
    
    def _deduplicate_entities(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate entities based on name similarity"""
        if not entities:
            return entities
        
        unique_entities = []
        seen_names = set()
        
        for entity in entities:
            name_key = entity['name'].lower().strip()
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
            date_key = date_info.get('normalized_date') or date_info.get('raw_date')
            if date_key and date_key not in seen_dates:
                seen_dates.add(date_key)
                unique_dates.append(date_info)
        
        return unique_dates
    
    def save_analysis_result(self, filename: str, analysis_result: OrderAnalysisResult) -> str:
        """Save analysis result to Firestore"""
        try:
            # Prepare data for storage
            result_data = {
                'filename': filename,
                'order_category': analysis_result.order_category,
                'category_confidence': analysis_result.category_confidence,
                'petitioners': analysis_result.petitioners,
                'respondents': analysis_result.respondents,
                'agp_names': analysis_result.agp_names,
                'dates': analysis_result.dates,
                'key_phrases': analysis_result.key_phrases,
                'next_hearing_date': analysis_result.next_hearing_date,
                'disposal_reason': analysis_result.disposal_reason,
                'analysis_timestamp': datetime.now().isoformat(),
                'text_length': len(analysis_result.order_text)
            }
            
            # Save to Firestore
            doc_ref = self.db.collection('order_analysis').add(result_data)
            doc_id = doc_ref[1].id
            
            logging.info(f"Order analysis saved with ID: {doc_id}")
            return doc_id
            
        except Exception as e:
            logging.error(f"Error saving analysis result: {e}")
            raise HTTPException(status_code=500, detail="Failed to save analysis result")