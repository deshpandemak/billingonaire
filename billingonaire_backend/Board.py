import logging
import re
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd
import pdfplumber
from fastapi import HTTPException
from firebase_admin import firestore

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
        # Updated: removed [\d ]+ to \d+ to prevent greedy matching with spaces
        case_pattern = r"\s+(\d+)\s+([A-Za-z()]+/\s*\d+/\d+)"

        # Extract board date
        date = re.findall(date_pattern, text)
        date_common = Counter(date).most_common(1)
        board_date = ""
        for x in date_common:
            board_date = datetime.strptime(x[0], "%d/%m/%Y").strftime("%Y-%m-%d")

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
                # Check if this is a serial number followed by case number
                if (
                    i + 2 < len(result)
                    and re.match(r"^\s*\d+\s*$", data.strip())
                    and re.match(
                        r"^[A-Za-z()]+/\s*\d+/\d+$", result[i + 1].strip()
                    )
                ):

                    # Extract case details (normalize spaces for consistency)
                    serial_no = data.strip()
                    case_data = result[i + 1].replace(" ", "").split("/")
                    case_type = case_data[0].strip()
                    case_no = case_data[1].strip()
                    case_year = case_data[2].strip()

                    # Get court/lawyer details from the next part
                    court_details = (
                        result[i + 2].strip() if i + 2 < len(result) else ""
                    )

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
                    # Handle standalone patterns
                    if re.match(r"^\s*\d+\s*$", data.strip()):
                        serial_no = data.strip()
                    elif re.match(r"^[A-Za-z()]+/\s*\d+/\d+$", data.strip()):
                        case_no_year = data.strip().split("/")
                        case_type = case_no_year[0].strip()
                        case_no = case_no_year[1].strip()
                        case_year = case_no_year[2].strip()
                    i += 1

        # Create DataFrame and remove duplicates for consistency with standard parsing
        matter_df = pd.DataFrame(matter_list)

        # Drop duplicates excluding list columns which are unhashable
        if not matter_df.empty:
            # Get all columns except those containing lists
            hashable_columns = []
            for col in matter_df.columns:
                # Check if the column contains lists by looking at the first non-null value
                first_value = (
                    matter_df[col].dropna().iloc[0]
                    if not matter_df[col].dropna().empty
                    else None
                )
                if not isinstance(first_value, list):
                    hashable_columns.append(col)

            # Drop duplicates based only on hashable columns
            if hashable_columns:
                matter_df = matter_df.drop_duplicates(subset=hashable_columns)

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
        else:
            petitioner_lawyer = court_data
            respondent_lawyer = ""
        # if court_data.startswith("SMT") or court_data.startswith("SHRI") or court_data.startswith("MS"):
        #     petitioner_lawyer = ""
        #     respondent_lawyer = lawyers[0]
        # else:
        #     if len(lawyers) < 2:
        #         petitioner_lawyer = lawyers[0]
        #         respondent_lawyer = ""
        #     else:
        #         petitioner_lawyer = lawyers[0]
        #         respondent_lawyer = lawyers[1]
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
            additional_respondent_lawyers = [
                lawyer.strip() for lawyer in lawyers_list if lawyer.strip()
            ]

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
            # Drop duplicates based on case identifiers only (not array columns)
            # Arrays (additional_cases, additional_respondent_lawyers) can't be hashed
            matter_df = matter_df.drop_duplicates(
                subset=[
                    "file_name",
                    "case_type",
                    "case_no",
                    "case_year",
                    "serial_number",
                ]
            )

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

            # Convert date strings to datetime objects
            for record in records:
                if "board_date" in record and isinstance(record["board_date"], str):
                    record["board_date"] = datetime.strptime(
                        record["board_date"], "%Y-%m-%d"
                    ).strftime("%Y-%m-%d")
            for row in records:
                formatted_date = row["board_date"]
                row["board_date"] = datetime.strptime(row["board_date"], "%Y-%m-%d")
                document_key = f"{formatted_date}-{row['case_type']}-{row['case_no']}-{row['case_year']}"

                # Set initial order status
                row["order_status"] = "not_linked"
                row["order_status_updated_at"] = datetime.now().isoformat()

                doc_ref = self.db.collection("daily-boards").document(document_key)
                doc_ref.set(row)
        except Exception as e:
            logging.error(f"Error saving data: {str(e)}")
            raise HTTPException(status_code=500, detail="Error saving data")

    def getData(self, search_criteria, agp_filter=None):
        # SECURITY: Removed debug logging to prevent data leakage
        logging.info("Processing search request")

        try:
            # First, check total documents in collection
            all_docs = list(self.db.collection("daily-boards").limit(5).stream())
            logging.info(f"Database query returned {len(all_docs)} documents")

            if not all_docs:
                logging.warning("No documents found in database")

            if not any(search_criteria.values()):
                # If no search criteria, return first 10 records
                logging.info("No search criteria provided, returning first 10 records")
                query = self.db.collection("daily-boards").limit(10)
            else:
                query = self.db.collection("daily-boards")

            # Apply AGP filter if user is restricted to specific AGPs
            if agp_filter:
                logging.info("Applying AGP access filter")
                if isinstance(agp_filter, list):
                    # Handle multiple AGP names - use 'in' operator
                    query = query.where("respondent_lawyer", "in", agp_filter)
                else:
                    # Handle single AGP name (backward compatibility)
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
            # Note: Firestore requires composite indexes for order_status + board_date
            # To avoid index requirements, apply client-side when date filters present
            order_status = search_criteria.get("orderStatus") or search_criteria.get(
                "order_status"
            )
            has_date_filter = start_date or end_date
            if order_status:
                if not has_date_filter:
                    # Safe to use server-side filter when no date filter
                    logging.info(
                        f"FILTERING BY ORDER STATUS (server-side): {order_status} (field: order_status)"
                    )
                    query = query.where("order_status", "==", order_status)
                else:
                    # Will filter client-side to avoid index requirement
                    logging.info(
                        "ORDER STATUS FILTER: Will apply client-side due to "
                        "Firestore index limitations (field: order_status)"
                    )

            # Apply order category filter (from ML analysis)
            # Same index limitation applies for order_category + board_date
            order_category = search_criteria.get(
                "orderCategory"
            ) or search_criteria.get("order_category")
            if order_category:
                if not has_date_filter:
                    # Safe to use server-side filter when no date filter
                    logging.info(
                        f"FILTERING BY ORDER CATEGORY (server-side): {order_category} (field: order_category)"
                    )
                    query = query.where("order_category", "==", order_category)
                else:
                    # Will filter client-side to avoid index requirement
                    logging.info(
                        "ORDER CATEGORY FILTER: Will apply client-side due to "
                        "Firestore index limitations (field: order_category)"
                    )

            docs = query.stream()
            data = []
            sample_dates = []

            # Check which filters need to be applied client-side (when date filters present)
            apply_advocate_filter_client_side = advocate_name and has_date_filter
            apply_order_status_filter_client_side = order_status and has_date_filter
            apply_order_category_filter_client_side = order_category and has_date_filter

            for doc in docs:
                doc_data = doc.to_dict()

                # Apply client-side advocate name filter if needed
                if apply_advocate_filter_client_side:
                    respondent_lawyer = doc_data.get("respondent_lawyer", "").lower()
                    if advocate_name.lower() not in respondent_lawyer:
                        continue  # Skip this document

                # Apply client-side order status filter if needed
                if apply_order_status_filter_client_side:
                    doc_order_status = doc_data.get("order_status", "")
                    if doc_order_status != order_status:
                        continue  # Skip this document

                # Apply client-side order category filter if needed
                if apply_order_category_filter_client_side:
                    doc_order_category = doc_data.get("order_category", "")
                    if doc_order_category != order_category:
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

                # Include order status fields for UI (these are already in the document from order processing)
                # Fields: order_downloaded, order_link, order_filename, order_analysis_completed, order_category
                # If not present, they will be None/undefined in the response

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
            return data
        except Exception as e:
            logging.error(f"Error getting data: {str(e)}")
            logging.error("Stack trace:", exc_info=True)
            raise HTTPException(status_code=500, detail="Error getting data")


# Remove DashboardData and dashboard router from this file, now in Dashboard.py
