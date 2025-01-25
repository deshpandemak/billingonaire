import re
import pdfplumber
import pandas as pd
import logging
from operator import itemgetter
from firebase_admin import firestore
from fastapi import HTTPException


class Board:

    def __init__(self):
        self.db = firestore.client()


    def readFile(self, file, date):
        logging.info("Reading file")
        try:
            df = self.read_board(file, date)
            return df
        except Exception as e:
            logging.error(f"Error reading file: {str(e)}")
            raise HTTPException(status_code=500, detail="Error reading file")

    def create_record(self, court_details, file_name, board_date, serial_no, case_number):
        court_data = court_details.strip()
        lawyers = re.split("\s{3,}", court_data)
        remaining_data = ""
        additional_cases = re.findall(r"([A-Za-z()]*/\s*\d+/[\d ]+)", court_data)
        if court_data.startswith("SMT") or court_data.startswith("SHRI") or court_data.startswith("MS"):
            petitioner_lawyer = ""
            respondent_lawyer = lawyers[0]
        else:
            if len(lawyers) < 2:
                petitioner_lawyer = lawyers[0]
                respondent_lawyer = ""
            else:
                petitioner_lawyer = lawyers[0]
                respondent_lawyer = lawyers[1]
        court_data = court_data.replace(petitioner_lawyer, "")
        court_data = court_data.replace(respondent_lawyer, "")
        court_data = court_data.replace("WITH", "")
        court_data = court_data.replace("with", "")
        court_data = court_data.replace("IN", "")
        court_data = court_data.replace("in", "")
        court_data = re.sub(r"([A-Za-z()]*/\s*\d+/[\d ]+)", "", court_data)
        court_data = court_data.strip()
        return {"file_name": file_name, "board_date": board_date,
                "case_number": case_number, "serial_number": serial_no,
                "petitioner_lawyer": petitioner_lawyer, "respondent_lawyer": respondent_lawyer,
                "additional_cases": ",".join(c.strip() for c in additional_cases), "additional_respondent_lawyers": court_data}

    def read_board(self, file, date):
        logging.info("Reading board")
        try:
            matter_list = list()
            court_pattern = r"(.*?)I\s*N\s*TH\s*E\s*CO\s*U\s*RT\s*OF.*|(.*?)BEFORE\s*THE\s*.*|(.*?)\s*THE\s*CO\s*U\s*RT\s*OF\s*.*"
            case_stage1_pattern = r"(.*?)\s*\*\s*(.*?)\s*\*\s*"
            case_pattern = r"\s{2,}(\d+)\s+([A-Za-z()]*/\s*\d+/[\d ]+)"
            case_no_pattern = r"([A-Za-z()]*/\s*\d+/[\d ]+)"
            
            with pdfplumber.open(file) as reader:
                number_of_pages = len(reader.pages)
                text = ""
                for i in range(number_of_pages):
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    text += page_text.replace("\n", "")

                result = re.split(case_pattern, text)
                count = 0
                case_number = ""
                serial_no = ""
                for data in result:
                    if "HON'BLE" in data:
                        court_details = re.findall(court_pattern, data)
                        if count > 0:
                            matter_list.append(self.create_record(court_details=court_details[0][0].strip(), file_name=file,
                                        board_date=date, serial_no=serial_no, case_number=case_number))
                        else:
                            count = count + 1
                    elif " * " in data:
                        stage = re.findall(case_stage1_pattern, data)

                        matter_list.append(self.create_record(court_details=stage[0][0].strip(), 
                                           file_name=file, board_date=date,
                                           serial_no=serial_no, case_number=case_number))
                        
                    elif data.isnumeric():
                        serial_no = data
                    elif re.match(case_no_pattern, data):
                        case_number = data
                    else:
                        matter_list.append(self.create_record(court_details=data.strip(), 
                                           file_name=file, board_date=date, 
                                           serial_no=serial_no, case_number=case_number))

            matter_df = pd.DataFrame(matter_list)
            matter_df = matter_df.drop_duplicates()

            return matter_df
        except Exception as e:
            logging.error(f"Error reading board: {str(e)}")
            raise HTTPException(status_code=500, detail="Error reading board")

    def saveData(self, df):
        logging.info("Saving data")
        try:
            records = df.to_dict(orient="records")
            for row in records:
                formatted_date = row['date'].strftime('%Y-%m-%d')
                document_key = f"{formatted_date}-{row['case_type']}-{row['case_no']}-{row['case_year']}"
                
                doc_ref = self.db.collection("daily-boards").document(document_key)
                doc_ref.set(row)
        except Exception as e:
            logging.error(f"Error saving data: {str(e)}")
            raise HTTPException(status_code=500, detail="Error saving data")

    def getData(self, search_criteria):
        logging.info("Getting data")
        try:
            if not any(search_criteria.values()):
                raise HTTPException(status_code=400, detail="At least one search criteria must be populated")

            query = self.db.collection("daily-boards")

            if search_criteria.get("case_number"):
                query = query.where("case_no", "==", search_criteria["case_number"])
            
            if search_criteria.get("start_date"):
                query = query.where("date", ">=", search_criteria["start_date"])
            
            if search_criteria.get("end_date"):
                query = query.where("date", "<=", search_criteria["end_date"])

            if search_criteria.get("advocate_name"):
                query = query.where("respondent_advocate", "==", search_criteria["advocate_name"])

            if search_criteria.get("case_type"):
                case_type = search_criteria["case_type"]
                if search_criteria.get("case_stage") == "Stamp":
                    case_type += "(ST)"
                query = query.where("case_type", "==", case_type)

            if search_criteria.get("case_year"):
                query = query.where("case_year", "==", search_criteria["case_year"])

            docs = query.stream()
            data = [doc.to_dict() for doc in docs]

            return data
        except Exception as e:
            logging.error(f"Error getting data: {str(e)}")
            raise HTTPException(status_code=500, detail="Error getting data")
