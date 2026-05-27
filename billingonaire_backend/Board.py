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
        # Updated pattern to stop at page header markers and case references
        # Stops at: WITH, IN THE COURT, IN CASE/, Page:, C.R. No:, * (section markers)
        # This prevents capturing page header content in respondent_lawyer field
        lawyers = re.match(
            r"(.*?)(SHRI.*?|SMT.*?|MS.*?)(WITH|IN THE COURT|IN \w+/|Page:|C\.R\. No:|\*|$)",
            court_data,
        )
        # Updated pattern: removed spaces from year part ([\d ]+) -> (\d+)
        # This prevents greedy matching like "IA/1808/2025 11" instead of "IA/1808/2025"
        additional_cases = re.findall(r"([A-Za-z()]+/\s*\d+/\d+)", court_data)
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
            record["lifecycle_status"] = "board_ingested"
            record["lifecycle_status_updated_at"] = None
            record["lifecycle_timeline"] = []

            case_ref = record.get("case_ref")
            case_detail = case_details_by_ref.get(case_ref)
            if not case_detail:
                continue

            orders = case_detail.get("orders") or []
            latest_order = orders[-1] if orders and isinstance(orders[-1], dict) else {}

            record["order_link"] = case_detail.get(
                "latest_order_link"
            ) or latest_order.get("order_link")
            record["order_status"] = (
                case_detail.get("latest_order_status")
                or latest_order.get("order_status")
                or "not_linked"
            )
            record["order_category"] = case_detail.get(
                "latest_order_category"
            ) or latest_order.get("order_category")
            record["order_date"] = case_detail.get(
                "latest_order_date"
            ) or latest_order.get("order_date")

            record["order_petitioner"] = case_detail.get("petitioner")
            record["order_respondent"] = case_detail.get("respondent")
            record["government_pleader"] = case_detail.get("government_pleader", [])

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

    def _record_matches_agp(self, record: Dict, agp_name_variations: List[str]) -> bool:
        """
        Check whether a hydrated record belongs to any of the given AGP name variations.

        Uses the same priority order as bill generation:
          1. government_pleader (from order analysis – most accurate)
          2. respondent_lawyer  (from board data)
          3. additional_respondent_lawyers (from board data)

        Only multi-token variations (at least two space-separated words) are used
        for matching.  Single-token variants such as a bare first name or last name
        are intentionally skipped to prevent over-broad matches that could expose
        cases belonging to a different government pleader who happens to share one
        name token.

        Returns:
            bool: True if the record matches any AGP name variation, False otherwise.
        """
        if not agp_name_variations:
            return True

        # Only keep multi-token variations to avoid false positives from
        # single-word variants (e.g. "Pooja" or "Deshpande" matching unrelated
        # lawyers).  Variations with at least two space-separated words are
        # specific enough to be used safely.  If the list contains no multi-token
        # entry, return False rather than falling back to single-token matching.
        safe_variations = [
            v.lower().strip() for v in agp_name_variations if v and len(v.split()) >= 2
        ]
        if not safe_variations:
            return False

        def _name_matches(candidate: str) -> bool:
            if not candidate:
                return False
            candidate_lower = candidate.lower().strip()
            for variation in safe_variations:
                # Only check whether the variation appears inside the candidate.
                # The reverse direction (candidate inside variation) is intentionally
                # omitted to prevent short/partial candidate strings from matching.
                if variation and variation in candidate_lower:
                    return True
            return False

        # Priority 1: government_pleader (list or string from case-details)
        government_pleader = record.get("government_pleader") or []
        if isinstance(government_pleader, str):
            government_pleader = [government_pleader]
        for gp in government_pleader:
            if _name_matches(str(gp)):
                return True

        # Priority 2: respondent_lawyer (string from board data)
        if _name_matches(record.get("respondent_lawyer", "")):
            return True

        # Priority 3: additional_respondent_lawyers (list from board data)
        additional = record.get("additional_respondent_lawyers") or []
        if isinstance(additional, str):
            additional = [additional]
        for lawyer in additional:
            if _name_matches(str(lawyer)):
                return True

        return False

    def getData(self, search_criteria, agp_filter=None, agp_name_variations=None):
        # SECURITY: Removed debug logging to prevent data leakage
        logging.info("Processing search request")

        try:
            # First, check total documents in collection
            all_docs = list(self.db.collection("daily-boards").limit(5).stream())
            logging.info(f"Database query returned {len(all_docs)} documents")

            if not all_docs:
                logging.warning("No documents found in database")

            if not any(search_criteria.values()) and not agp_filter:
                # No criteria at all and no access restriction: return first 10 records
                logging.info("No search criteria provided, returning first 10 records")
                query = self.db.collection("daily-boards").limit(10)
            else:
                query = self.db.collection("daily-boards")

            # Apply AGP filter if user is restricted to specific AGPs.
            # When agp_name_variations are provided, the access control check is
            # applied Python-side after hydration (so that government_pleader and
            # additional_respondent_lawyers are also considered — matching the
            # bill-generation algorithm).  No Firestore pre-filter is pushed in
            # that path; the full collection is fetched and then filtered.
            if agp_filter and not agp_name_variations:
                # Legacy path: exact/list match on respondent_lawyer only
                logging.info("Applying AGP access filter (exact, legacy)")
                if isinstance(agp_filter, list):
                    query = query.where("respondent_lawyer", "in", agp_filter)
                else:
                    query = query.where("respondent_lawyer", "==", agp_filter)

            # Apply search criteria - this should work for ALL users, not just those with AGP filters
            # Handle both camelCase (frontend) and snake_case (legacy) field names
            case_number = search_criteria.get("caseNumber") or search_criteria.get(
                "case_number"
            )
            if case_number:
                query = query.where("case_no", "==", case_number)

            start_date = search_criteria.get("startDate") or search_criteria.get(
                "start_date"
            )
            if start_date:
                # Convert date to datetime object to match database storage (datetime objects)
                if isinstance(start_date, str):
                    if "T" in start_date:
                        # Handle ISO date-time format (e.g., "2025-01-01T00:00:00")
                        start_date = start_date.split("T")[0]
                    # Convert string to datetime object
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                elif not hasattr(start_date, "strftime"):
                    # If not a string or datetime, try to parse as string
                    start_date = datetime.strptime(str(start_date), "%Y-%m-%d")
                logging.info(
                    f"FILTERING BY START DATE: {start_date} (converted to datetime object) (field: board_date)"
                )
                query = query.where("board_date", ">=", start_date)

            end_date = search_criteria.get("endDate") or search_criteria.get("end_date")
            if end_date:
                # Convert date to datetime object to match database storage (datetime objects)
                if isinstance(end_date, str):
                    if "T" in end_date:
                        # Handle ISO date-time format (e.g., "2025-01-01T23:59:59")
                        end_date = end_date.split("T")[0]
                    # Convert string to datetime object - set to end of day
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                    # Add 23:59:59 to include the entire end date
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                elif not hasattr(end_date, "strftime"):
                    # If not a string or datetime, try to parse as string
                    end_date = datetime.strptime(str(end_date), "%Y-%m-%d")
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                logging.info(
                    f"FILTERING BY END DATE: {end_date} (converted to datetime object) (field: board_date)"
                )
                query = query.where("board_date", "<=", end_date)

            advocate_name = search_criteria.get("advocateName") or search_criteria.get(
                "advocate_name"
            )
            if advocate_name:
                # Note: Using range query for advocate name conflicts with date range in Firestore
                # If date filters are present, we skip the advocate filter and apply it client-side
                has_date_filter = start_date or end_date
                if not has_date_filter:
                    # Safe to use range query when no date filter
                    query = query.where("respondent_lawyer", ">=", advocate_name)
                    query = query.where(
                        "respondent_lawyer", "<=", advocate_name + "\uf8ff"
                    )
                else:
                    # Will filter client-side after query
                    logging.info(
                        "ADVOCATE FILTER: Will apply client-side due to Firestore "
                        "limitations (field: respondent_lawyer)"
                    )

            case_type = search_criteria.get("caseType") or search_criteria.get(
                "case_type"
            )
            if case_type:
                case_stage = search_criteria.get("caseStage") or search_criteria.get(
                    "case_stage"
                )
                if case_stage == "Stamp":
                    case_type += "(ST)"
                query = query.where("case_type", "==", case_type)

            case_year = search_criteria.get("caseYear") or search_criteria.get(
                "case_year"
            )
            if case_year:
                # Convert to string if it's a number
                if isinstance(case_year, (int, float)):
                    case_year = str(int(case_year))
                print(f"FILTERING BY CASE YEAR: {case_year} (field: case_year)")
                logging.info(f"FILTERING BY CASE YEAR: {case_year} (field: case_year)")
                query = query.where("case_year", "==", case_year)

            # Apply order status filter
            order_status = search_criteria.get("orderStatus") or search_criteria.get(
                "order_status"
            )

            # Apply order category filter (from ML analysis)
            order_category = search_criteria.get(
                "orderCategory"
            ) or search_criteria.get("order_category")

            docs = query.stream()
            data = []
            sample_dates = []

            # Check which filters need to be applied client-side (when date filters present)
            apply_advocate_filter_client_side = advocate_name and has_date_filter

            for doc in docs:
                doc_data = doc.to_dict()

                # Apply client-side advocate name filter if needed
                if apply_advocate_filter_client_side:
                    respondent_lawyer = doc_data.get("respondent_lawyer", "").lower()
                    if advocate_name.lower() not in respondent_lawyer:
                        continue  # Skip this document

                # Add document ID for reference
                doc_data["id"] = doc.id

                # Log sample board_date values for debugging
                if "board_date" in doc_data and len(sample_dates) < 3:
                    sample_dates.append(
                        f"{doc_data['board_date']} (type: {type(doc_data['board_date'])})"
                    )
                # Convert datetime objects to strings for JSON serialization
                if "board_date" in doc_data and hasattr(
                    doc_data["board_date"], "strftime"
                ):
                    doc_data["board_date"] = doc_data["board_date"].strftime("%Y-%m-%d")

                data.append(doc_data)

            # Log sample dates for debugging
            if sample_dates:
                logging.info(f"SAMPLE BOARD_DATE VALUES: {sample_dates}")
            else:
                # Get a few sample documents to see what dates look like
                sample_query = self.db.collection("daily-boards").limit(3)
                sample_docs = sample_query.stream()
                sample_dates = []
                for doc in sample_docs:
                    doc_data = doc.to_dict()
                    if "board_date" in doc_data:
                        sample_dates.append(
                            f"{doc_data['board_date']} (type: {type(doc_data['board_date'])})"
                        )
                logging.info(f"SAMPLE BOARD_DATE VALUES FROM DB: {sample_dates}")

            logging.info(f"Search query returned {len(data)} records")

            if not data:
                logging.warning("No records matched search criteria")

            hydrated_data = self._hydrate_with_case_details(data)

            # Apply AGP filter Python-side after hydration when name variations
            # are provided.  This matches the bill-generation algorithm: it
            # checks government_pleader (order analysis), respondent_lawyer
            # (board data) and additional_respondent_lawyers (board data) in
            # priority order.
            if agp_filter and agp_name_variations:
                logging.info(
                    "Applying AGP filter post-hydration with %d name variations",
                    len(agp_name_variations),
                )
                hydrated_data = [
                    row
                    for row in hydrated_data
                    if self._record_matches_agp(row, agp_name_variations)
                ]
                logging.info("AGP filter retained %d records", len(hydrated_data))

            if order_status:
                hydrated_data = [
                    row
                    for row in hydrated_data
                    if (row.get("order_status") or "not_linked") == order_status
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
