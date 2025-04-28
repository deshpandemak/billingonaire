from collections import Counter
import re
import pdfplumber
import pandas as pd
import logging
from operator import itemgetter
from firebase_admin import firestore
from fastapi import HTTPException
from datetime import datetime
import numpy as np

class Board:

    def __init__(self):
        self.db = firestore.client()


    def readFile(self, filename, file):
        logging.info("Reading file")
        try:
            df = self.read_board(filename, file)
            # Replace NaN and infinite values
            df = df.replace([np.nan, np.inf, -np.inf], None)

            # print(df)
            return df
        except Exception as e:
            logging.error(f"Error reading file: {str(e)}")
            raise HTTPException(status_code=500, detail="Error reading file")

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
            # case_pattern = r"\s{1,}(\d+)\s+([A-Za-z()]*/\s*\d+/[\d ]+)"
            case_pattern = r"\s+(\d+)\s+([A-Za-z()]*/\s*\d+/[\d ]+)"
            case_no_pattern = r"([A-Za-z()]*/\s*\d+/[\d ]+)"
            
            with pdfplumber.open(file) as reader:
                number_of_pages = len(reader.pages)
                text = ""
                for i in range(number_of_pages):
                    page = reader.pages[i]
                    page_text = page.extract_text()
                    text += page_text.replace("\n", " ")

                date = re.findall(date_pattern, text)
                date_common = Counter(date).most_common(1)
                board_date = ""
                for x in date_common:
                    board_date = datetime.strptime(x[0], "%y/%d/%Y").strftime("%Y-%m-%d")

                result = re.split(case_pattern, text)
                count = 0
                case_type = ""
                case_no = ""
                case_year = ""
                serial_no = ""
                for data in result:
                    if "HON'BLE" in data:
                        court_details = re.match(court_pattern, data)
                        if court_details.group(1) is None:  
                            continue
                        if count > 0:
                            matter_list.append(self.create_record(court_details=court_details.group(1).strip(), file_name=filename,
                                        board_date=board_date, serial_no=serial_no, case_type=case_type, case_no=case_no, case_year=case_year))
                        else:
                            count = count + 1
                    elif " * " in data:
                        stage = re.findall(case_stage1_pattern, data)

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
            raise HTTPException(status_code=500, detail="Error reading board")

    def saveData(self, df):
        logging.info("Saving data")
        try:
            records = df.to_dict(orient="records")
            for row in records:
                formatted_date = row['board_date']
                row['board_date'] = datetime.strptime(row['board_date'], '%Y-%m-%d')
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
