import logging
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
import pdfplumber
from fastapi import HTTPException
from firebase_admin import firestore

try:
    from case_data_store import CaseDataStore
except ImportError:
    from .case_data_store import CaseDataStore

try:
    from UserMatterMatcher import any_name_matches
except ImportError:
    from .UserMatterMatcher import any_name_matches

# Import ML Enhanced Parser
try:
    from ml_enhanced_parser import MLEnhancedParser

    ML_PARSER_AVAILABLE = True
except ImportError:
    try:
        from .ml_enhanced_parser import MLEnhancedParser

        ML_PARSER_AVAILABLE = True
    except ImportError:
        ML_PARSER_AVAILABLE = False
        logging.warning(
            "ML Enhanced Parser not available - continuing with standard parsing"
        )


# Lifecycle states that mean the pipeline could not complete on its own and a
# human may need to act.  Mirrors the 'warning'/'error' groups in the frontend's
# lifecycleUtils config so the Search Orders status filter and the status chips
# always agree.  Everything not listed here and not "analysed" counts as pending.
FAILED_LIFECYCLE_STATES = {
    "fetch_failed_retryable",
    "fetch_failed_terminal",
    "analysis_failed_retryable",
    "analysis_failed_terminal",
    "manual_review_required",
}

# The 13 lifecycle states collapsed into the four buckets users actually see.
# Mirrors getSimpleStatus() in billingonaire-ui/src/lib/lifecycleUtils.js — keep
# the two in step, they are the contract for the Search Orders status filter.
SIMPLE_STATUS_KEYS = ("waiting", "working", "ready", "attention")

_WAITING_STATES = {"board_ingested", "fetch_not_due", "fetch_queued", "not_linked"}
_WORKING_STATES = {
    "fetch_in_progress",
    "fetch_succeeded",
    "analysis_queued",
    "analysis_in_progress",
    "linked",
    "manually_uploaded",
}

# Older filter values still accepted so existing links keep working.
_LEGACY_STATUS_FILTERS = {
    "analysed": "ready",
    "pending": "waiting",
    "failed": "attention",
}


def simple_status_for(lifecycle_status: str) -> str:
    """Collapse a lifecycle state into one of SIMPLE_STATUS_KEYS."""
    status = lifecycle_status or "board_ingested"
    if status == "analysed":
        return "ready"
    if status in FAILED_LIFECYCLE_STATES or status in {
        "fetch_failed",
        "analysis_failed",
        "order_failed",
        "order_analysis_failed",
    }:
        return "attention"
    if status in _WORKING_STATES:
        return "working"
    if status in _WAITING_STATES:
        return "waiting"
    return "waiting"


# Pattern for initials-based GP/AGP names used in modern Bombay HC boards.
# Matches 2-4 single uppercase letters separated by spaces, followed by a
# comma and a government role keyword.
# Examples: "N S B, GP"  "G R R , AGP"  "K B D, ADDL GP"  "S M, B'PNL"
_GP_INITIALS_PATTERN = re.compile(
    r"(?<![/\w])([A-Z](?:\s+[A-Z]){1,3})(?!\w)\s*,\s*(ADDL\s*GP|AGP|B['\s]P\s*N?\s*L|GP)",
    re.IGNORECASE,
)


class Board:
    def __init__(self):
        self.db = firestore.client()
        self.case_store = CaseDataStore(self.db)

        # Initialize ML Enhanced Parser if available
        self.ml_parser = None
        if ML_PARSER_AVAILABLE:
            try:
                self.ml_parser = MLEnhancedParser(fallback_parser=self)
                logging.info("ML Enhanced Parser initialized successfully")
            except Exception as e:
                logging.warning(f"Could not initialize ML Enhanced Parser: {e}")
                self.ml_parser = None

    def readFile(self, filename, file):
        logging.info(f"Reading file: {filename}")

        # Try ML Enhanced parsing first if available
        if self.ml_parser:
            try:
                return self.readFileWithML(filename, file)
            except Exception as e:
                logging.warning(
                    f"ML parsing failed, falling back to standard parsing: {e}"
                )

        # Fallback to standard parsing
        try:
            df = self.read_board(filename, file)
            # Replace NaN and infinite values
            df = df.replace([np.nan, np.inf, -np.inf], None)

            return df
        except Exception as e:
            logging.error(f"Error reading file: {str(e)}")
            raise HTTPException(status_code=500, detail="Error reading file")

    def readFileWithML(self, filename, file):
        """Enhanced file reading with ML processing"""
        logging.info(f"Processing {filename} with ML enhancements")

        # Read file content
        file_content = file.read()
        file.seek(0)  # Reset file pointer for fallback

        # Use ML Enhanced Parser
        if self.ml_parser:
            ml_result = self.ml_parser.enhance_pdf_extraction(filename, file_content)
        else:
            # Fallback if ML parser failed to initialize
            raise Exception("ML parser not available")

        # Process the enhanced text with existing logic
        df = self.process_enhanced_text(filename, ml_result)

        # Replace NaN and infinite values
        df = df.replace([np.nan, np.inf, -np.inf], None)

        # Log ML enhancement results
        logging.info(
            f"ML Enhancement Results - Method: {ml_result.extraction_method}, "
            f"Quality: {ml_result.quality_score:.2f}, "
            f"Entities: {len(ml_result.entities)}, "
            f"Mappings: {len(ml_result.name_mappings)}"
        )

        return df

    def process_enhanced_text(self, filename, ml_result):
        """Process ML-enhanced text extraction results"""
        text = ml_result.text

        # Use existing parsing logic but with enhanced text
        matter_list = []
        date_pattern = r"(\d+/\d+/\d+)"
        court_pattern = (
            r"(.*?)I\s*N\s*TH\s*E\s*CO\s*U\s*R\s*T\s*O\s*F.*|"
            r"(.*?)BEFORE\s*THE\s*.*|(.*?)\s*THE\s*CO\s*U\s*RT\s*OF\s*.*"
        )
        # Updated pattern to match standard parsing: handle start of string and optional dots
        case_pattern = r"(?:\s+|^)(\d+)\.?\s+([A-Za-z()]+/\s*\d+/\d+)"

        # Extract board date
        date = re.findall(date_pattern, text)
        date_common = Counter(date).most_common(1)
        board_date = ""
        for x in date_common:
            board_date = datetime.strptime(x[0], "%d/%m/%Y").strftime("%Y-%m-%d")
        if not board_date:
            raise ValueError(f"No board date (dd/mm/yyyy) found in PDF: {filename}")

        # Process cases with enhanced text
        result = re.split(case_pattern, text)
        count = 0
        case_type = ""
        case_no = ""
        case_year = ""
        serial_no = ""

        i = 0
        while i < len(result):
            data = result[i]

            # Handle court header detection
            if "HON'BLE" in data:
                court_details = re.match(court_pattern, data)
                if court_details is None or court_details.group(1) is None:
                    i += 1
                    continue
                if count > 0:
                    # Create record with ML enhancements
                    record = self.create_enhanced_record(
                        court_details=court_details.group(1).strip(),
                        file_name=filename,
                        board_date=board_date,
                        serial_no=serial_no,
                        case_type=case_type,
                        case_no=case_no,
                        case_year=case_year,
                        ml_result=ml_result,
                    )
                    matter_list.append(record)
                else:
                    count = count + 1
                i += 1
            elif " * " in data:
                # Skip stage headers to avoid creating unnecessary records
                # Stage headers like "* FOR SPEAKING TO THE MINUTES *" don't represent actual cases
                i += 1
            else:
                # Define case_no_pattern for validation (matches standard parsing)
                case_no_pattern = r"([A-Za-z()]+/\s*\d+/\d+)"

                # Check if this is a serial number followed by case number
                if (
                    i + 2 < len(result)
                    and data.strip().isnumeric()
                    and re.match(case_no_pattern, result[i + 1])
                ):
                    # Extract case details (matches standard parsing exactly)
                    serial_no = data.strip()
                    case_data = result[i + 1].replace(" ", "").split("/")
                    case_type = case_data[0]
                    case_no = case_data[1]
                    case_year = case_data[2]

                    # Get court/lawyer details from the next part
                    court_details = result[i + 2].strip() if i + 2 < len(result) else ""

                    # Create record for this case
                    if serial_no and case_type and case_no and case_year:
                        record = self.create_enhanced_record(
                            court_details=court_details,
                            file_name=filename,
                            board_date=board_date,
                            serial_no=serial_no,
                            case_type=case_type,
                            case_no=case_no,
                            case_year=case_year,
                            ml_result=ml_result,
                        )
                        matter_list.append(record)

                    i += 3  # Skip the next 2 parts as they've been processed
                else:
                    # Handle standalone patterns (matches standard parsing)
                    if data.isnumeric():
                        serial_no = data
                    elif re.match(case_no_pattern, data):
                        data = data.replace(" ", "")
                        case_number = data.split("/")
                        case_type = case_number[0]
                        case_no = case_number[1]
                        case_year = case_number[2]
                    else:
                        # Only create records for meaningful content (matches standard parsing)
                        if data.strip() and len(data.strip()) > 3:
                            record = self.create_enhanced_record(
                                court_details=data.strip(),
                                file_name=filename,
                                board_date=board_date,
                                serial_no=serial_no,
                                case_type=case_type,
                                case_no=case_no,
                                case_year=case_year,
                                ml_result=ml_result,
                            )
                            matter_list.append(record)
                    i += 1

        # Create DataFrame and remove duplicates (matches standard parsing exactly)
        matter_df = pd.DataFrame(matter_list)

        # Drop duplicates based on case identifiers only (not array columns)
        # Arrays (additional_cases, additional_respondent_lawyers) can't be hashed
        # NOTE: Some boards may not have serial numbers for every entry. If
        # serial numbers are empty for many rows, including them in the
        # deduplication subset will collapse distinct records into one.
        # Include 'serial_number' in the subset only when it contains
        # meaningful (non-empty) values.
        subset_fields = ["file_name", "case_type", "case_no", "case_year"]
        if (
            "serial_number" in matter_df.columns
            and not matter_df["serial_number"].dropna().empty
            and any(str(x).strip() for x in matter_df["serial_number"].dropna())
        ):
            subset_fields.append("serial_number")

        matter_df = matter_df.drop_duplicates(subset=subset_fields)

        return matter_df

    def create_enhanced_record(
        self,
        court_details,
        file_name,
        board_date,
        serial_no,
        case_type,
        case_no,
        case_year,
        ml_result,
    ):
        """Create record with ML enhancements"""
        # Start with standard record creation
        base_record = self.create_record(
            court_details,
            file_name,
            board_date,
            serial_no,
            case_type,
            case_no,
            case_year,
        )

        # Enhance with ML results
        enhanced_record = base_record.copy()

        # Add ML-enhanced lawyer name matching
        if ml_result.name_mappings:
            enhanced_record["ml_name_mappings"] = []
            enhanced_record["ml_confidence_scores"] = []

            for mapping in ml_result.name_mappings:
                if mapping["matched_users"]:
                    best_match = mapping["matched_users"][0]
                    enhanced_record["ml_name_mappings"].append(
                        {
                            "extracted_name": mapping["extracted_name"],
                            "matched_user": best_match["user"],
                            "confidence": best_match["score"],
                            "match_type": best_match["match_type"],
                        }
                    )

        # Add extraction quality metrics
        enhanced_record["ml_extraction_method"] = ml_result.extraction_method
        enhanced_record["ml_quality_score"] = ml_result.quality_score
        enhanced_record["ml_entities_found"] = len(ml_result.entities)

        return enhanced_record

    def create_record(
        self,
        court_details,
        file_name,
        board_date,
        serial_no,
        case_type,
        case_no,
        case_year,
    ):
        court_data = court_details.strip()
        # Updated pattern: removed spaces from year part ([\d ]+) -> (\d+)
        # This prevents greedy matching like "IA/1808/2025 11" instead of "IA/1808/2025"
        additional_cases = re.findall(r"([A-Za-z()]+/\s*\d+/\d+)", court_data)

        # New: detect initials-based GP/AGP names (modern board format).
        # When government lawyers appear as single-letter initials followed by a
        # role keyword (e.g. "N S B, GP", "G R R , AGP", "K B D, ADDL GP"),
        # use those markers to split petitioner from government lawyers and return
        # early.  Falls through to the legacy SHRI/SMT/MS logic when absent.
        gp_matches = list(_GP_INITIALS_PATTERN.finditer(court_data))
        if gp_matches:
            first_gp = gp_matches[0]
            petitioner_lawyer = court_data[: first_gp.start()].strip()
            # Strip trailing column-layout artifacts ("WITH", "IN") but keep
            # "AND" since it appears in law firm names (e.g. "MEHTA AND PARTNERS")
            petitioner_lawyer = re.sub(
                r"\s+(?:WITH|IN)\s*$",
                "",
                petitioner_lawyer,
                flags=re.IGNORECASE,
            ).strip()
            # Only the initials (group 1) are kept; the role keyword (group 2 —
            # GP / ADDL GP / AGP / B'PNL) is deliberately discarded. Billing is
            # for appearing, whatever the designation, so the names are pooled.
            #
            # Read the two fields below literally:
            #   respondent_lawyer            = the government lawyer printed
            #                                  FIRST — may be any of the roles.
            #   additional_respondent_lawyers = THE REMAINING government lawyers.
            # Neither is tied to the "Additional Government Pleader" role, despite
            # the unfortunate similarity to UserManager's
            # `additional_government_pleader` legal category.
            gov_lawyers = [m.group(1).strip() for m in gp_matches]
            return {
                "file_name": file_name,
                "board_date": board_date,
                "case_type": case_type,
                "case_no": case_no,
                "case_year": case_year,
                "serial_number": serial_no,
                "petitioner_lawyer": petitioner_lawyer,
                "respondent_lawyer": gov_lawyers[0] if gov_lawyers else "",
                "additional_cases": [c.strip() for c in additional_cases],
                "additional_respondent_lawyers": gov_lawyers[1:],
            }

        # Legacy: title-based parsing for boards where the respondent lawyer's
        # name starts with a salutation (SHRI / SMT / MS).
        # Stops at: WITH, IN THE COURT, IN CASE/, Page:, C.R. No:, * (section markers)
        # This prevents capturing page header content in respondent_lawyer field
        lawyers = re.match(
            r"(.*?)(SHRI.*?|SMT.*?|MS.*?)(WITH|IN THE COURT|IN \w+/|Page:|C\.R\. No:|\*|$)",
            court_data,
        )
        # print(str(court_data))
        # print(str(lawyers.group(1)))
        # print(str(lawyers.group(2)))
        if lawyers:
            petitioner_lawyer = lawyers.group(1) if lawyers.group(1) else ""
            respondent_lawyer = lawyers.group(2) if lawyers.group(2) else ""
            # When court_data starts with a title (SHRI/SMT/MS), group 1 is empty
            # and group 2 holds the whole string.  Split group 2 at the second
            # title occurrence to recover the petitioner's name.
            if not petitioner_lawyer and respondent_lawyer:
                second_title = re.search(
                    r"(?<=\w)\s+((?:SHRI|SMT|MS)(?:\b|\.|,))",
                    respondent_lawyer,
                    re.IGNORECASE,
                )
                if second_title:
                    petitioner_lawyer = respondent_lawyer[
                        : second_title.start()
                    ].strip()
                    respondent_lawyer = respondent_lawyer[
                        second_title.start() :
                    ].strip()
                else:
                    petitioner_lawyer = respondent_lawyer
                    respondent_lawyer = ""
        else:
            petitioner_lawyer = court_data
            respondent_lawyer = ""
        # Clean up respondent lawyer (remove case references and IN keyword)
        respondent_lawyer_raw = respondent_lawyer
        respondent_lawyer = respondent_lawyer.replace("IN", "")
        respondent_lawyer = respondent_lawyer.replace("in", "")
        for case in additional_cases:
            respondent_lawyer = respondent_lawyer.replace(case, "")
        respondent_lawyer = respondent_lawyer.strip()

        # Remove extracted parts from court_data to get additional lawyers
        # Use the raw respondent_lawyer for removal to ensure exact match
        court_data = court_data.replace(petitioner_lawyer, "")
        court_data = court_data.replace(respondent_lawyer_raw, "")
        court_data = court_data.replace(
            "WITH", " "
        )  # Replace WITH with space for splitting
        court_data = court_data.replace("with", " ")
        court_data = court_data.replace("IN", "")
        court_data = court_data.replace("in", "")
        court_data = court_data.replace("*", "")
        # Updated: removed [\d ]+ to \d+ to prevent greedy matching
        court_data = re.sub(r"([A-Za-z()]+/\s*\d+/\d+)", "", court_data)

        # Remove page header content before splitting lawyers
        # Stop at any of these markers: IN THE COURT, Page:, C.R. No:, Bench ID:, HEADER NOTE, etc.
        header_match = re.search(
            r"(THE COURT|Page:|C\.R\. No:|Bench ID:|HEADER NOTE|APPELLATE SIDE|BEFORE THE)",
            court_data,
            re.IGNORECASE,
        )
        if header_match:
            # Keep only text before the header marker
            court_data = court_data[: header_match.start()]

        court_data = court_data.strip()

        # Parse additional respondent lawyers into array
        additional_respondent_lawyers = []
        if court_data:
            # Split on:
            # 1. Two or more spaces before lawyer titles (handles "GP      SMT" pattern)
            # 2. Comma before lawyer titles (handles "AGP, SHRI" pattern)
            lawyers_list = re.split(
                r"(?:\s{2,}(?=(?:SHRI|SMT|MS|MR|DR|PROF)\.)|"
                r",\s*(?=(?:SHRI|SMT|MS|MR|DR|PROF)\.))",
                court_data,
            )

            # Filter out section markers and clean each lawyer name
            for lawyer in lawyers_list:
                lawyer = lawyer.strip()
                if not lawyer:
                    continue

                # Remove section markers (FOR ADMISSION, FOR ORDERS, etc.) and dashes
                # These are board section headers, not lawyer names
                # Handle patterns like "FOR HEARG", "FOR FAL HEARG", "FOR FINAL DISPOSAL", etc.
                lawyer = re.sub(
                    r"\s*FOR\s+(ADMISSION|CIRCULATION|ORDERS|HEARING|HEARG|FINAL|FAL)(\s+(AND|DISPOSAL|HEARG|HEARING))?.*$",
                    "",
                    lawyer,
                    flags=re.IGNORECASE,
                )
                lawyer = re.sub(
                    r"\s*DUE\s+(ADMISSION|ORDERS|MATTERS).*$",
                    "",
                    lawyer,
                    flags=re.IGNORECASE,
                )
                lawyer = re.sub(
                    r"\s*\([^)]*(?:DUE\s+)?MATTERS[^)]*\)",
                    "",
                    lawyer,
                    flags=re.IGNORECASE,
                )  # Remove (DUE MATTERS) or (MATTERS)
                lawyer = re.sub(r"\s*-{2,}.*$", "", lawyer)  # Remove trailing dashes
                lawyer = re.sub(
                    r"\s*\d+\s*$", "", lawyer
                )  # Remove trailing numbers (like " 1", " - 1")
                # Remove any leftover parentheses or brackets
                lawyer = re.sub(r"[()[\]]", "", lawyer)
                # Remove standalone section markers
                lawyer = re.sub(
                    r"^\s*(?:MATTERS|ADMISSION|ORDERS|HEARING|HEARG|DISPOSAL)\s*$",
                    "",
                    lawyer,
                    flags=re.IGNORECASE,
                )
                lawyer = lawyer.strip()

                # Only add if there's meaningful content left (lawyer name)
                if lawyer and len(lawyer) > 5:  # Minimum reasonable lawyer name length
                    additional_respondent_lawyers.append(lawyer)

        return {
            "file_name": file_name,
            "board_date": board_date,
            "case_type": case_type,
            "case_no": case_no,
            "case_year": case_year,
            "serial_number": serial_no,
            "petitioner_lawyer": petitioner_lawyer,
            "respondent_lawyer": respondent_lawyer,
            "additional_cases": [c.strip() for c in additional_cases],
            "additional_respondent_lawyers": additional_respondent_lawyers,
        }

    def read_board(self, filename, file):
        logging.info("Reading board")
        try:
            matter_list = list()
            date_pattern = r"(\d+/\d+/\d+)"
            court_pattern = (
                r"(.*?)I\s*N\s*TH\s*E\s*CO\s*U\s*R\s*T\s*O\s*F.*|"
                r"(.*?)BEFORE\s*THE\s*.*|(.*?)\s*THE\s*CO\s*U\s*RT\s*OF\s*.*"
            )
            # Updated pattern to handle both "54 WP/123/2024" and "54. WP/123/2024" formats
            # Also updated: removed [\d ]+ to \d+ to prevent greedy matching with spaces
            case_pattern = r"(?:\s+|^)(\d+)\.?\s+([A-Za-z()]+/\s*\d+/\d+)"
            case_no_pattern = r"([A-Za-z()]+/\s*\d+/\d+)"

            with pdfplumber.open(file) as reader:
                number_of_pages = len(reader.pages)
                text = ""
                for i in range(number_of_pages):
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        # Add space after page content to prevent concatenation issues
                        text += page_text.replace("\n", " ") + " "
                # Explicit error if no text extracted
                if not text.strip():
                    logging.error("No text could be extracted from the PDF file.")
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No text could be extracted from the PDF file. "
                            "Please check if the file is valid and not scanned as an image."
                        ),
                    )

                date = re.findall(date_pattern, text)
                date_common = Counter(date).most_common(1)
                board_date = ""
                for x in date_common:
                    board_date = datetime.strptime(x[0], "%d/%m/%Y").strftime(
                        "%Y-%m-%d"
                    )
                if not board_date:
                    raise ValueError(
                        f"No board date (dd/mm/yyyy) found in PDF: {filename}"
                    )

                result = re.split(case_pattern, text)
                count = 0
                case_type = ""
                case_no = ""
                case_year = ""
                serial_no = ""
                i = 0
                while i < len(result):
                    data = result[i]

                    if "HON'BLE" in data:
                        court_details = re.match(court_pattern, data)
                        if court_details is None or court_details.group(1) is None:
                            i += 1
                            continue
                        if count > 0:
                            matter_list.append(
                                self.create_record(
                                    court_details=court_details.group(1).strip(),
                                    file_name=filename,
                                    board_date=board_date,
                                    serial_no=serial_no,
                                    case_type=case_type,
                                    case_no=case_no,
                                    case_year=case_year,
                                )
                            )
                        else:
                            count = count + 1
                        i += 1
                    elif " * " in data:
                        # Skip stage headers to avoid creating unnecessary records
                        i += 1
                    else:
                        # Check if this is a serial number followed by case number
                        if (
                            i + 2 < len(result)
                            and data.strip().isnumeric()
                            and re.match(case_no_pattern, result[i + 1])
                        ):
                            # Extract case details
                            serial_no = data.strip()
                            case_data = result[i + 1].replace(" ", "").split("/")
                            case_type = case_data[0]
                            case_no = case_data[1]
                            case_year = case_data[2]

                            # Get court/lawyer details from the next part
                            court_details = (
                                result[i + 2].strip() if i + 2 < len(result) else ""
                            )

                            # Create record for this case
                            if serial_no and case_type and case_no and case_year:
                                matter_list.append(
                                    self.create_record(
                                        court_details=court_details,
                                        file_name=filename,
                                        board_date=board_date,
                                        serial_no=serial_no,
                                        case_type=case_type,
                                        case_no=case_no,
                                        case_year=case_year,
                                    )
                                )

                            i += 3  # Skip the next 2 parts as they've been processed
                        else:
                            # Handle standalone patterns
                            if data.isnumeric():
                                serial_no = data
                            elif re.match(case_no_pattern, data):
                                data = data.replace(" ", "")
                                case_number = data.split("/")
                                case_type = case_number[0]
                                case_no = case_number[1]
                                case_year = case_number[2]
                            else:
                                # Only create records for meaningful content
                                if data.strip() and len(data.strip()) > 3:
                                    matter_list.append(
                                        self.create_record(
                                            court_details=data.strip(),
                                            file_name=filename,
                                            board_date=board_date,
                                            serial_no=serial_no,
                                            case_type=case_type,
                                            case_no=case_no,
                                            case_year=case_year,
                                        )
                                    )
                            i += 1

            matter_df = pd.DataFrame(matter_list)
            # Normalise serial_number: replace empty strings with None so the
            # dedup check below treats missing and empty values consistently.
            if "serial_number" in matter_df.columns:
                matter_df["serial_number"] = matter_df["serial_number"].replace(
                    "", None
                )
            # Drop duplicates based on case identifiers only (not array columns)
            # Arrays (additional_cases, additional_respondent_lawyers) can't be hashed
            # NOTE: Some boards may not have serial numbers for every entry. If
            # serial numbers are empty for many rows, including them in the
            # deduplication subset will collapse distinct records into one.
            # Include 'serial_number' in the subset only when it contains
            # meaningful (non-empty) values.
            subset_fields = ["file_name", "case_type", "case_no", "case_year"]
            if (
                "serial_number" in matter_df.columns
                and not matter_df["serial_number"].dropna().empty
                and any(str(x).strip() for x in matter_df["serial_number"].dropna())
            ):
                subset_fields.append("serial_number")

            matter_df = matter_df.drop_duplicates(subset=subset_fields)

            return matter_df
        except Exception as e:
            logging.error(f"Error reading board: {str(e)}")
            logging.error("Stack trace:", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Error reading board: {str(e)}"
            )

    def saveData(self, df):
        logging.info("Saving data")
        try:
            records = df.to_dict(orient="records")
            if not records:
                raise HTTPException(status_code=400, detail="No data to save")

            for row in records:
                formatted_date = row["board_date"]
                row["board_date"] = datetime.strptime(row["board_date"], "%Y-%m-%d")
                document_key = f"{formatted_date}-{row['case_type']}-{row['case_no']}-{row['case_year']}"
                row["case_ref"] = self.case_store.build_case_ref(
                    row.get("case_type"), row.get("case_no"), row.get("case_year")
                )

                doc_ref = self.db.collection("daily-boards").document(document_key)
                doc_ref.set(row)

                case_row = dict(row)
                case_row["board_date"] = formatted_date
                self.case_store.upsert_from_board_entry(document_key, case_row)
        except Exception as e:
            logging.error(f"Error saving data: {str(e)}")
            raise HTTPException(status_code=500, detail="Error saving data")

    def _build_case_ref(self, record: Dict) -> str:
        return self.case_store.build_case_ref(
            record.get("case_type"), record.get("case_no"), record.get("case_year")
        )

    def _hydrate_with_case_details(self, records: List[Dict]) -> List[Dict]:
        if not records:
            return records

        case_refs = []
        for record in records:
            case_ref = record.get("case_ref") or self._build_case_ref(record)
            record["case_ref"] = case_ref
            case_refs.append(case_ref)

        case_details_by_ref = self.case_store.get_case_details_map(case_refs)

        for record in records:
            record["order_link"] = None
            record["order_status"] = "not_linked"
            record["order_category"] = None
            record["order_date"] = None
            record["order_petitioner"] = None
            record["order_respondent"] = None
            record["government_pleader"] = []
            record["assigned_government_pleaders"] = []
            record["order_history"] = []
            record["portal_case_status"] = None
            record["portal_disposal_date"] = None
            record["portal_checked_at"] = None
            record["portal_stage"] = None
            record["lifecycle_status"] = "board_ingested"
            record["lifecycle_status_updated_at"] = None
            record["lifecycle_timeline"] = []

            case_ref = record.get("case_ref")
            case_detail = case_details_by_ref.get(case_ref)
            if not case_detail:
                continue

            orders = case_detail.get("orders") or []

            # Find the order entry whose board_date matches this record's
            # board_date so Search Orders shows analysis for that specific
            # appearance, not always the latest order across all appearances.
            record_board_date = record.get("board_date")  # YYYY-MM-DD string
            date_matched_order = None
            if record_board_date:
                for o in reversed(orders):
                    if isinstance(o, dict) and o.get("board_date") == record_board_date:
                        date_matched_order = o
                        break

            if date_matched_order:
                record["order_link"] = date_matched_order.get("order_link")
                record["order_status"] = (
                    date_matched_order.get("order_status") or "not_linked"
                )
                record["order_category"] = date_matched_order.get("order_category")
                record["order_date"] = date_matched_order.get("order_date")
                record["government_pleader"] = (
                    date_matched_order.get("government_pleader") or []
                )
                record["portal_stage"] = date_matched_order.get("portal_stage")

            record["order_petitioner"] = case_detail.get("petitioner")
            record["order_respondent"] = case_detail.get("respondent")
            record["portal_case_status"] = case_detail.get("portal_case_status")
            record["portal_disposal_date"] = case_detail.get("portal_disposal_date")
            record["portal_checked_at"] = case_detail.get("portal_checked_at")

            record["assigned_government_pleaders"] = case_detail.get(
                "assigned_government_pleaders", []
            )
            record["order_history"] = orders
            record["lifecycle_status"] = (
                case_detail.get("lifecycle_status") or "board_ingested"
            )
            record["lifecycle_status_updated_at"] = case_detail.get(
                "lifecycle_status_updated_at"
            )
            record["lifecycle_timeline"] = case_detail.get("lifecycle_events") or []

        return records

    def _record_matches_agp(self, record: Dict, agp_filter: str) -> bool:
        """Check whether a hydrated record belongs to the given AGP.

        Matches against ALL available GP sources (union), mirroring bill generation:
          - government_pleader from case-details (order analysis) — names extracted
            from the actual court order PDF.  Present only after order analysis.
          - respondent_lawyer / additional_respondent_lawyers from daily-boards —
            the board-assigned GP for that hearing date.

        Bill generation reads government_pleader from daily-boards directly, which
        is never written by the analysis pipeline, so it always matches on
        respondent_lawyer.  Using a union here ensures search-orders and bill
        generation agree: a case is included if the AGP was assigned (board GP)
        OR if they appear in the court order (order GP).

        Matching uses score_name_match fuzzy logic (threshold 0.50).
        """
        if not agp_filter:
            return True

        # Order GP: from case-details, populated after order PDF analysis.
        gp_raw = record.get("government_pleader")
        gp_from_order: List[str] = (
            [gp_raw]
            if isinstance(gp_raw, str) and gp_raw
            else [str(g) for g in (gp_raw or []) if g]
        )

        # Board GP: respondent_lawyer and additional_respondent_lawyers from
        # daily-boards, set when the board PDF is uploaded.
        board_gp: List[str] = []
        rl = record.get("respondent_lawyer")
        if rl:
            board_gp.append(str(rl))
        additional = record.get("additional_respondent_lawyers") or []
        if isinstance(additional, str):
            additional = [additional]
        board_gp.extend(str(x) for x in additional if x)

        # Union: include the case if either source matches.
        return any_name_matches(agp_filter, gp_from_order + board_gp)

    # Maximum rows returned from a single search — prevents unbounded full-scans.
    _SEARCH_RESULT_LIMIT = 500

    def getData(
        self,
        search_criteria,
        agp_filter=None,
    ):
        logging.info("Processing search request")

        try:
            # --- Extract and normalise all criteria upfront ---
            case_number_raw = (
                search_criteria.get("caseNumber")
                or search_criteria.get("case_number")
                or ""
            )
            advocate_name = (
                search_criteria.get("advocateName")
                or search_criteria.get("advocate_name")
                or ""
            )
            case_type = (
                search_criteria.get("caseType")
                or search_criteria.get("case_type")
                or ""
            )
            case_year_raw = (
                search_criteria.get("caseYear")
                or search_criteria.get("case_year")
                or ""
            )
            case_stage = (
                search_criteria.get("caseStage")
                or search_criteria.get("case_stage")
                or ""
            )
            order_status = (
                search_criteria.get("orderStatus")
                or search_criteria.get("order_status")
                or ""
            )
            order_category = (
                search_criteria.get("orderCategory")
                or search_criteria.get("order_category")
                or ""
            )

            # Normalise case_year to string (frontend sends it as string from
            # <input type="number">, but guard against numeric JSON values too).
            case_year = (
                str(int(case_year_raw))
                if isinstance(case_year_raw, (int, float))
                else str(case_year_raw).strip()
            )

            # Parse case_number: accept full format "WP/4447/2018" and extract
            # the numeric case_no part; optionally override case_type / case_year
            # when the user typed the complete reference.
            case_number = case_number_raw.strip()
            if case_number and "/" in case_number:
                parts = [p.strip() for p in case_number.split("/")]
                if len(parts) >= 3:
                    if not case_type:
                        case_type = parts[0]
                    if not case_year:
                        case_year = parts[2]
                    case_number = parts[1]
                elif len(parts) == 2:
                    case_number = parts[0]

            # --- Parse date strings to datetime objects ---
            start_date = search_criteria.get("startDate") or search_criteria.get(
                "start_date"
            )
            if start_date:
                if isinstance(start_date, str):
                    if "T" in start_date:
                        start_date = start_date.split("T")[0]
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                elif not hasattr(start_date, "strftime"):
                    start_date = datetime.strptime(str(start_date), "%Y-%m-%d")

            end_date = search_criteria.get("endDate") or search_criteria.get("end_date")
            if end_date:
                if isinstance(end_date, str):
                    if "T" in end_date:
                        end_date = end_date.split("T")[0]
                    end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59
                    )
                elif not hasattr(end_date, "strftime"):
                    end_date = datetime.strptime(str(end_date), "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59
                    )

            has_date_filter = bool(start_date or end_date)

            no_criteria = (
                not any(
                    [
                        start_date,
                        end_date,
                        advocate_name,
                        case_number,
                        case_type,
                        case_year,
                        case_stage,
                        order_status,
                        order_category,
                    ]
                )
                and not agp_filter
            )

            if no_criteria:
                logging.info("No search criteria provided, returning first 10 records")
                query = self.db.collection("daily-boards").limit(10)
                data = []
                for doc in query.stream():
                    doc_data = doc.to_dict()
                    doc_data["id"] = doc.id
                    if "board_date" in doc_data and hasattr(
                        doc_data["board_date"], "strftime"
                    ):
                        doc_data["board_date"] = doc_data["board_date"].strftime(
                            "%Y-%m-%d"
                        )
                    data.append(doc_data)
                return self._hydrate_with_case_details(data)

            # --- Build Firestore query ---
            # Strategy: only push the date-range filter and the AGP legacy
            # equality filter to Firestore.  Everything else is applied
            # Python-side after the query returns.  This avoids requiring
            # composite indexes (e.g. board_date range + case_type equality)
            # which caused "requires index" 500 errors for combined filters.
            #
            # Exception: when there is NO date filter and the user supplied a
            # case_no or case_type, push that single equality to Firestore so
            # we avoid a full-collection scan.
            query = self.db.collection("daily-boards")

            # AGP filter is applied Python-side after hydration via _record_matches_agp
            # (fuzzy match against government_pleader / board GP fields).

            if has_date_filter:
                # Push only the range filter; equality filters go Python-side.
                if start_date:
                    logging.info("FILTERING BY START DATE: %s", start_date)
                    query = query.where("board_date", ">=", start_date)
                if end_date:
                    logging.info("FILTERING BY END DATE: %s", end_date)
                    query = query.where("board_date", "<=", end_date)
                # ORDER BY on the range field is required by Firestore.
                query = query.order_by("board_date", direction="DESCENDING")
            else:
                # No date range: use a single equality filter so Firestore can
                # use a single-field auto-index rather than scanning everything.
                if case_number:
                    query = query.where("case_no", "==", case_number)
                elif case_type:
                    expected_ct = case_type + ("(ST)" if case_stage == "Stamp" else "")
                    query = query.where("case_type", "==", expected_ct)

            # advocate_name / agp_filter can only be applied after hydration
            # (fuzzy matching needs government_pleader from case-details,
            # which Firestore can't filter on). Capping the raw fetch here
            # would silently drop candidate rows before the name filter ever
            # sees them -- e.g. a month with >500 board rows across all AGPs
            # would only ever inspect the newest 500, undercounting one
            # AGP's matters relative to an unbounded caller like bill
            # generation (which streams the full date range). Only skip the
            # cap when there's a date range to bound the scan by -- an
            # unfiltered full-collection scan still needs the safety limit.
            name_filter_pending = bool(advocate_name or agp_filter)
            if not (has_date_filter and name_filter_pending):
                query = query.limit(self._SEARCH_RESULT_LIMIT)

            # --- Compute expected case_type value for Python-side filter ---
            expected_case_type = ""
            if case_type:
                expected_case_type = (
                    case_type + "(ST)" if case_stage == "Stamp" else case_type
                )

            # --- Iterate docs and apply Python-side filters ---
            data = []
            for doc in query.stream():
                doc_data = doc.to_dict()

                # case_no exact match — always applied Python-side as a safety
                # net (Firestore equality pre-filter is a performance hint only).
                if case_number:
                    if str(doc_data.get("case_no", "")).strip() != case_number:
                        continue

                # case_type (and implicit Stamp/Registration stage) filter —
                # always applied Python-side; Firestore pre-filter is optional.
                if expected_case_type:
                    if doc_data.get("case_type", "") != expected_case_type:
                        continue

                # case_stage without case_type: filter by "(ST)" suffix presence.
                if case_stage and not case_type:
                    stored_ct = doc_data.get("case_type", "")
                    if case_stage == "Stamp" and not stored_ct.endswith("(ST)"):
                        continue
                    if case_stage == "Registration" and stored_ct.endswith("(ST)"):
                        continue

                # case_year: compare as strings to handle int/str storage variance.
                if case_year:
                    stored_year = str(doc_data.get("case_year", "")).strip()
                    if stored_year != case_year:
                        continue

                doc_data["id"] = doc.id
                if "board_date" in doc_data and hasattr(
                    doc_data["board_date"], "strftime"
                ):
                    doc_data["board_date"] = doc_data["board_date"].strftime("%Y-%m-%d")
                data.append(doc_data)

            logging.info("Search query returned %d records", len(data))
            if not data:
                logging.warning("No records matched search criteria")

            hydrated_data = self._hydrate_with_case_details(data)

            # advocate_name: applied post-hydration so that government_pleader
            # (written to case-details by order analysis, not to daily-boards)
            # is visible.  Pre-hydration the field is always [] in daily-boards.
            if advocate_name:

                def _row_matches_advocate(row: dict) -> bool:
                    # Priority 1: order-analysed GP (from case-details, most accurate).
                    gp_raw = row.get("government_pleader") or []
                    if isinstance(gp_raw, str):
                        gp_raw = [gp_raw]
                    order_gp = [str(g) for g in gp_raw if g]

                    # Priority 2: board-assigned GP — respondent_lawyer and
                    # additional_respondent_lawyers from daily-boards.
                    # Mirrors bill generation's source priority; petitioner_lawyer
                    # is excluded to avoid false positives.
                    board_gp: List[str] = []
                    rl = row.get("respondent_lawyer")
                    if rl:
                        board_gp.append(str(rl))
                    additional = row.get("additional_respondent_lawyers") or []
                    if isinstance(additional, str):
                        additional = [additional]
                    board_gp.extend(str(x) for x in additional if x)

                    return any_name_matches(advocate_name, order_gp + board_gp)

                hydrated_data = [
                    row for row in hydrated_data if _row_matches_advocate(row)
                ]
                logging.info(
                    "advocate_name filter '%s' retained %d records",
                    advocate_name,
                    len(hydrated_data),
                )

            # Apply AGP filter Python-side after hydration using the same
            # fuzzy matching as bill generation: order GP first, board GP fallback.
            if agp_filter:
                logging.info(
                    "Applying AGP filter post-hydration for agp_filter=%r",
                    agp_filter,
                )
                hydrated_data = [
                    row
                    for row in hydrated_data
                    if self._record_matches_agp(row, agp_filter)
                ]
                logging.info("AGP filter retained %d records", len(hydrated_data))

            if order_status:

                def _matches_lifecycle_status(row: dict, wanted: str) -> bool:
                    status = row.get("lifecycle_status") or "board_ingested"
                    bucket = simple_status_for(status)
                    # Legacy filter values kept working so old bookmarks and
                    # saved links do not silently return nothing.
                    wanted = _LEGACY_STATUS_FILTERS.get(wanted, wanted)
                    if wanted in SIMPLE_STATUS_KEYS:
                        return bucket == wanted
                    if "," in wanted:
                        # Comma-separated raw lifecycle_status values -- a
                        # precise subset filter for callers that need exactly
                        # a known set of states rather than a whole
                        # SIMPLE_STATUS bucket. Namely the Dashboard's "N
                        # cases could not be completed automatically" banner:
                        # its count is STUCK_LIFECYCLE_STATUSES specifically,
                        # narrower than the "attention" bucket (which also
                        # includes manual_review_required, a separate,
                        # working-as-intended queue) -- without this, "See
                        # which cases" could show more rows than the banner's
                        # own count.
                        wanted_statuses = {
                            s.strip() for s in wanted.split(",") if s.strip()
                        }
                        return status in wanted_statuses
                    return True

                hydrated_data = [
                    row
                    for row in hydrated_data
                    if _matches_lifecycle_status(row, order_status)
                ]

            if order_category:
                hydrated_data = [
                    row
                    for row in hydrated_data
                    if row.get("order_category") == order_category
                ]

            return hydrated_data
        except Exception as e:
            logging.error(f"Error getting data: {str(e)}")
            logging.error("Stack trace:", exc_info=True)
            raise HTTPException(status_code=500, detail="Error getting data")


# Remove DashboardData and dashboard router from this file, now in Dashboard.py
