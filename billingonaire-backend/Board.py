from collections import Counter
import re
import pdfplumber
import pandas as pd
import logging
from operator import itemgetter
from firebase_admin import firestore
from fastapi import HTTPException, APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import numpy as np

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
        logging.warning("ML Enhanced Parser not available - continuing with standard parsing")

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
                logging.warning(f"ML parsing failed, falling back to standard parsing: {e}")
        
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
        ml_result = self.ml_parser.enhance_pdf_extraction(filename, file_content)
        
        # Process the enhanced text with existing logic
        df = self.process_enhanced_text(filename, ml_result)
        
        # Replace NaN and infinite values
        df = df.replace([np.nan, np.inf, -np.inf], None)
        
        # Log ML enhancement results
        logging.info(f"ML Enhancement Results - Method: {ml_result.extraction_method}, "
                    f"Quality: {ml_result.quality_score:.2f}, "
                    f"Entities: {len(ml_result.entities)}, "
                    f"Mappings: {len(ml_result.name_mappings)}")
        
        return df
    
    def process_enhanced_text(self, filename, ml_result):
        """Process ML-enhanced text extraction results"""
        text = ml_result.text
        
        # Use existing parsing logic but with enhanced text
        matter_list = []
        date_pattern = r"(\d+/\d+/\d+)"
        court_pattern = r"(.*?)I\s*N\s*TH\s*E\s*CO\s*U\s*R\s*T\s*O\s*F.*|(.*?)BEFORE\s*THE\s*.*|(.*?)\s*THE\s*CO\s*U\s*RT\s*OF\s*.*"
        case_stage1_pattern = r"(.*?)\s*\*\s*(.*?)\s*\*\s*"
        case_pattern = r"\s+(\d+)\s+([A-Za-z()]*/\s*\d+/[\d ]+)"
        
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
        
        for data in result:
            if "HON'BLE" in data:
                court_details = re.match(court_pattern, data)
                if court_details is None or court_details.group(1) is None:  
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
                        ml_result=ml_result
                    )
                    matter_list.append(record)
                else:
                    count = count + 1
            elif " * " in data:
                stage = re.findall(case_stage1_pattern, data)
                if stage and len(stage) > 0 and len(stage[0]) > 0:
                    record = self.create_enhanced_record(
                        court_details=stage[0][0].strip(), 
                        file_name=filename, 
                        board_date=board_date,
                        serial_no=serial_no, 
                        case_type=case_type, 
                        case_no=case_no, 
                        case_year=case_year,
                        ml_result=ml_result
                    )
                    matter_list.append(record)
            else:
                if re.match(r"^\s*\d+\s*$", data.strip()):
                    serial_no = data.strip()
                elif re.match(r"^[A-Za-z()]*/\s*\d+/[\d ]+$", data.strip()):
                    case_no_year = data.strip().split("/")
                    case_type = case_no_year[0].strip()
                    case_no = case_no_year[1].strip()
                    case_year = case_no_year[2].strip()

        return pd.DataFrame(matter_list)
    
    def create_enhanced_record(self, court_details, file_name, board_date, serial_no, case_type, case_no, case_year, ml_result):
        """Create record with ML enhancements"""
        # Start with standard record creation
        base_record = self.create_record(court_details, file_name, board_date, serial_no, case_type, case_no, case_year)
        
        # Enhance with ML results
        enhanced_record = base_record.copy()
        
        # Add ML-enhanced lawyer name matching
        if ml_result.name_mappings:
            enhanced_record['ml_name_mappings'] = []
            enhanced_record['ml_confidence_scores'] = []
            
            for mapping in ml_result.name_mappings:
                if mapping['matched_users']:
                    best_match = mapping['matched_users'][0]
                    enhanced_record['ml_name_mappings'].append({
                        'extracted_name': mapping['extracted_name'],
                        'matched_user': best_match['user'],
                        'confidence': best_match['score'],
                        'match_type': best_match['match_type']
                    })
                    
        # Add extraction quality metrics
        enhanced_record['ml_extraction_method'] = ml_result.extraction_method
        enhanced_record['ml_quality_score'] = ml_result.quality_score
        enhanced_record['ml_entities_found'] = len(ml_result.entities)
        
        return enhanced_record

    def create_record(self, court_details, file_name, board_date, serial_no, case_type, case_no, case_year):
        court_data = court_details.strip()
        lawyers = re.match(r"(.*?)(SHRI.*?|SMT.*?|MS.*?)(WITH|$)", court_data)
        remaining_data = ""
        additional_cases = re.findall(r"([A-Za-z()]*/\s*\d+/[\d ]+)", court_data)
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
        respondent_lawyer = respondent_lawyer.replace("IN", "")
        respondent_lawyer = respondent_lawyer.replace("in", "")
        for case in additional_cases:
            respondent_lawyer = respondent_lawyer.replace(case, "")

        court_data = court_data.replace(petitioner_lawyer, "")
        court_data = court_data.replace(respondent_lawyer, "")
        court_data = court_data.replace("WITH", "")
        court_data = court_data.replace("with", "")
        court_data = court_data.replace("IN", "")
        court_data = court_data.replace("in", "")
        court_data = court_data.replace("*", "")
        court_data = re.sub(r"([A-Za-z()]*/\s*\d+/[\d ]+)", "", court_data)
        court_data = court_data.strip()
        return {"file_name": file_name, "board_date": board_date,
                "case_type": case_type, "case_no": case_no, "case_year": case_year, 
                "serial_number": serial_no,
                "petitioner_lawyer": petitioner_lawyer, "respondent_lawyer": respondent_lawyer,
                "additional_cases": ",".join(c.strip() for c in additional_cases), "additional_respondent_lawyers": court_data}

    def read_board(self, filename, file):
        logging.info("Reading board")
        try:
            matter_list = list()
            date_pattern = r"(\d+/\d+/\d+)"
            court_pattern = r"(.*?)I\s*N\s*TH\s*E\s*CO\s*U\s*R\s*T\s*O\s*F.*|(.*?)BEFORE\s*THE\s*.*|(.*?)\s*THE\s*CO\s*U\s*RT\s*OF\s*.*"
            case_stage1_pattern = r"(.*?)\s*\*\s*(.*?)\s*\*\s*"
            case_pattern = r"\s+(\d+)\s+([A-Za-z()]*/\s*\d+/[\d ]+)"
            case_no_pattern = r"([A-Za-z()]*/\s*\d+/[\d ]+)"
            
            with pdfplumber.open(file) as reader:
                number_of_pages = len(reader.pages)
                text = ""
                for i in range(number_of_pages):
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text.replace("\n", " ")
                # Explicit error if no text extracted
                if not text.strip():
                    logging.error("No text could be extracted from the PDF file.")
                    raise HTTPException(status_code=400, detail="No text could be extracted from the PDF file. Please check if the file is valid and not scanned as an image.")

                date = re.findall(date_pattern, text)
                date_common = Counter(date).most_common(1)
                board_date = ""
                for x in date_common:
                    board_date = datetime.strptime(x[0], "%d/%m/%Y").strftime("%Y-%m-%d")

                result = re.split(case_pattern, text)
                count = 0
                case_type = ""
                case_no = ""
                case_year = ""
                serial_no = ""
                for data in result:
                    if "HON'BLE" in data:
                        court_details = re.match(court_pattern, data)
                        if court_details is None or court_details.group(1) is None:  
                            continue
                        if count > 0:
                            matter_list.append(self.create_record(court_details=court_details.group(1).strip(), file_name=filename,
                                        board_date=board_date, serial_no=serial_no, case_type=case_type, case_no=case_no, case_year=case_year))
                        else:
                            count = count + 1
                    elif " * " in data:
                        stage = re.findall(case_stage1_pattern, data)
                        if stage and len(stage) > 0 and len(stage[0]) > 0:
                            matter_list.append(self.create_record(court_details=stage[0][0].strip(), 
                                           file_name=filename, board_date=board_date,
                                           serial_no=serial_no, case_type=case_type, case_no=case_no, case_year=case_year))
                        
                    elif data.isnumeric():
                        serial_no = data
                    elif re.match(case_no_pattern, data):
                        data = data.replace(" ", "")
                        case_number = data.split("/")
                        case_type = case_number[0]
                        case_no = case_number[1]
                        case_year = case_number[2]
                    else:
                        matter_list.append(self.create_record(court_details=data.strip(), 
                                       file_name=filename, board_date=board_date, 
                                       serial_no=serial_no, case_type=case_type, case_no=case_no, case_year=case_year))

            matter_df = pd.DataFrame(matter_list)
            matter_df = matter_df.drop_duplicates()

            return matter_df
        except Exception as e:
            
            logging.error(f"Error reading board: {str(e)}")
            logging.error("Stack trace:", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error reading board: {str(e)}")

    def saveData(self, df):
        logging.info("Saving data")
        try:
            records = df.to_dict(orient="records")
            if not records:
                raise HTTPException(status_code=400, detail="No data to save")
            
            # Convert date strings to datetime objects
            for record in records:
                if 'board_date' in record and isinstance(record['board_date'], str):
                    record['board_date'] = datetime.strptime(record['board_date'], '%Y-%m-%d').strftime('%Y-%m-%d')
            for row in records:
                formatted_date = row['board_date']
                row['board_date'] = datetime.strptime(row['board_date'], '%Y-%m-%d')
                document_key = f"{formatted_date}-{row['case_type']}-{row['case_no']}-{row['case_year']}"
                
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
            case_number = search_criteria.get("caseNumber") or search_criteria.get("case_number")
            if case_number:
                query = query.where("case_no", "==", case_number)
            
            start_date = search_criteria.get("startDate") or search_criteria.get("start_date")
            if start_date:
                # Convert date to datetime object to match database storage (datetime objects)
                if isinstance(start_date, str):
                    if 'T' in start_date:
                        # Handle ISO date-time format (e.g., "2025-01-01T00:00:00")
                        start_date = start_date.split('T')[0]
                    # Convert string to datetime object
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                elif not hasattr(start_date, 'strftime'):
                    # If not a string or datetime, try to parse as string
                    start_date = datetime.strptime(str(start_date), '%Y-%m-%d')
                logging.info(f"FILTERING BY START DATE: {start_date} (converted to datetime object) (field: board_date)")
                query = query.where("board_date", ">=", start_date)
            
            end_date = search_criteria.get("endDate") or search_criteria.get("end_date")
            if end_date:
                # Convert date to datetime object to match database storage (datetime objects)
                if isinstance(end_date, str):
                    if 'T' in end_date:
                        # Handle ISO date-time format (e.g., "2025-01-01T23:59:59")
                        end_date = end_date.split('T')[0]
                    # Convert string to datetime object - set to end of day
                    end_date = datetime.strptime(end_date, '%Y-%m-%d')
                    # Add 23:59:59 to include the entire end date
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                elif not hasattr(end_date, 'strftime'):
                    # If not a string or datetime, try to parse as string  
                    end_date = datetime.strptime(str(end_date), '%Y-%m-%d')
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                logging.info(f"FILTERING BY END DATE: {end_date} (converted to datetime object) (field: board_date)")
                query = query.where("board_date", "<=", end_date)

            advocate_name = search_criteria.get("advocateName") or search_criteria.get("advocate_name")
            if advocate_name:
                # Search in AGP name field, case-insensitive
                query = query.where("respondent_lawyer", ">=", advocate_name)
                query = query.where("respondent_lawyer", "<=", advocate_name + '\uf8ff')

            case_type = search_criteria.get("caseType") or search_criteria.get("case_type")
            if case_type:
                case_stage = search_criteria.get("caseStage") or search_criteria.get("case_stage")
                if case_stage == "Stamp":
                    case_type += "(ST)"
                query = query.where("case_type", "==", case_type)

            case_year = search_criteria.get("caseYear") or search_criteria.get("case_year")
            if case_year:
                # Convert to string if it's a number
                if isinstance(case_year, (int, float)):
                    case_year = str(int(case_year))
                print(f"FILTERING BY CASE YEAR: {case_year} (field: case_year)")
                logging.info(f"FILTERING BY CASE YEAR: {case_year} (field: case_year)")
                query = query.where("case_year", "==", case_year)

            docs = query.stream()
            data = []
            sample_dates = []
            for doc in docs:
                doc_data = doc.to_dict()
                # Log sample board_date values for debugging
                if 'board_date' in doc_data and len(sample_dates) < 3:
                    sample_dates.append(f"{doc_data['board_date']} (type: {type(doc_data['board_date'])})")
                # Convert datetime objects to strings for JSON serialization
                if 'board_date' in doc_data and hasattr(doc_data['board_date'], 'strftime'):
                    doc_data['board_date'] = doc_data['board_date'].strftime('%Y-%m-%d')
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
                    if 'board_date' in doc_data:
                        sample_dates.append(f"{doc_data['board_date']} (type: {type(doc_data['board_date'])})")
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
