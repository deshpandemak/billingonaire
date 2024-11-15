import re
import pdfplumber
import pandas as pd
import logging
from operator import itemgetter
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import HTTPException


class Board:

    def __init__(self):
        self.matter_dict = dict()
        self.matter_list = list()
        self.judge_pattern = '.*(IN THE.*|BEFORE.*)'
        self.judge_pattern2 = '.*(AND HON\'BLE.*)'
        self.date_pattern = '.*(\d *\d */ *\d\d/\d\d\d *\d)'
        self.court_room_no = '.*C\.R\..*No: *(\d+).*I *D *: *(\d+)'
        self.court_room_no1 = '.*C\.R\..*No: *(\d+ *Annex).*I *D *: *(\d+)'
        self.stage = '.*\*(.*)\*.*'
        self.case_pattern='^(\d+) +(.*/\d+/\d+)(.*)(SMT.*|SHRI.*|MS.*)'
        # case_pattern5='^(\d+) +(.* \d+/\d+)(.*)(SMT.*|SHRI.*|MS.*)'
        self.case_pattern2='(.*/\d+/\d+)+ *(WITH SMT.*|WITH SHRI.*|WITH MS.*)'
        self.case_pattern3 = '(.*/\d+/\d+)+'
        self.case_pattern4 = '.*(WITH SMT.*|WITH SHRI.*|WITH MS.*)'
        # pooja1 = '.*P.* *M.* *J.* *DESHPANDE'
        # pooja2 = '.*P.* *M.* *JOSHI'
        # df_filter_column = ['respondent_advocate', 'additional_respondent_advocate']
        # filter_agp_name_pattern = [pooja1, pooja2]

        self.patterns = {self.judge_pattern: {1: 'judge_name1'}, 
                        self.judge_pattern2: {1: 'judge_name2'}, 
                        self.date_pattern: {1: 'date'}, 
                        self.court_room_no1: {1: 'court_room_no', 2: 'bench_id'}, 
                        self.court_room_no: {1: 'court_room_no', 2: 'bench_id'}, 
                        self.stage: {1: 'stage'}, 
                        self.case_pattern: {1: 'serial_no', 2: 'case_no', 3: 'petitioner_advocate', 4: 'respondent_advocate'}, 
                        self.case_pattern2: {1: 'linked_cases', 2: 'additional_respondent_advocate'},
                        self.case_pattern3: {1: 'linked_cases'},
                        self.case_pattern4: {1: 'additional_respondent_advocate'}
                    }
        cred = credentials.Certificate("./firebase/credentials.json")
        firebase_admin.initialize_app(cred)
        self.db = firestore.client()


    def readFile(self, file):
        logging.info("Reading file")
        df = self.read_board(file)
        logging.info("Finished reading file")
        return df
    
    def copy(self, new_dict, old_dict, dict_keys):
        for key, value in dict_keys.items():
            if value in old_dict.keys():
                new_dict[value] = old_dict[value]

        
    def clean(self, dict_keys):
        for key, value in dict_keys.items():
            self.matter_dict[value] = ''
    
    def copy_data(self):
        new_dict = dict()
        self.copy(new_dict, self.matter_dict, self.patterns[self.judge_pattern])
        self.copy(new_dict, self.matter_dict, self.patterns[self.judge_pattern2])
        self.copy(new_dict, self.matter_dict, self.patterns[self.date_pattern])
        self.copy(new_dict, self.matter_dict, self.patterns[self.stage])
        self.copy(new_dict, self.matter_dict, self.patterns[self.court_room_no])
        self.matter_dict = new_dict

    def extract_board_data(self, lines, filename):
        logging.info("Extracting board data")
        for line in lines:
            logging.debug(f"Processing line: {line}")
            
            for pattern, group_details in self.patterns.items():
                match = re.match(pattern, line)
                if match:
                    if pattern == self.case_pattern:
                        if len(self.matter_dict) > 0:
                            self.matter_list.append(self.matter_dict)
                            self.copy_data()
                    
                    if pattern == self.stage:
                        if len(self.matter_dict) > 0:
                            self.matter_list.append(self.matter_dict)
                            self.copy_data()
                            self.clean(self.patterns[self.stage])     

                    if pattern == self.judge_pattern:
                        if len(self.matter_dict) > 0:
                            self.matter_list.append(self.matter_dict)
                            self.matter_dict = dict()
                            # copy_data()

                    for group_count, key in group_details.items():
                        if key in self.matter_dict.keys():
                            if key == 'date':
                                continue
                            self.matter_dict[key] = self.matter_dict[key] + ' ' + match.group(group_count).strip()
                        else:
                            self.matter_dict[key] = match.group(group_count).strip()
                    # self.matter_dict['filename'] = filename
                    break

    
    def read_board(self, file):
        df = None

        logging.info('Reading File')
        need_ocr = False
        with pdfplumber.open(file) as reader:
            number_of_pages = len(reader.pages)
            logging.info(f"Number of pages: {number_of_pages}")
            text = None
            for i in range(number_of_pages):
                page = reader.pages[i]
                page_text = page.extract_text()
                lines = page_text.splitlines()
                if len(lines) == 1:
                    need_ocr = True
                    # break
                    if text is None:
                        text = page_text
                    else:
                        text = text + page_text
                else:    
                    self.extract_board_data(lines, file)
            if need_ocr:
                self.read_page(text, file)

        if len(self.matter_list) > 0:
            matter_df = pd.DataFrame(self.matter_list)
            matter_df = matter_df[matter_df['serial_no'].notna()]
            
            matter_df['date'] = matter_df['date'].str.replace(' ', '')
            matter_df['date'] = pd.to_datetime(matter_df['date'], format = '%d/%m/%Y')

        return matter_df


    def read_page(self, page_txt, filename):
        logging.info("Reading page")
        logging.debug(page_txt)
        data_list = list()
        single_txt_judge_pattern = '(IN THE[\w\s.:\']*|BEFORE[\w\s.:\']*)[\w\s-]*(\d\d/\d\d/\d\d\d\d) *C\.R\. *No: *(\d+)[\s\w,:]*( *\d+ *)'
        
        matches = re.finditer(single_txt_judge_pattern, page_txt)
        for m in matches:
            data_list.append({'start': m.start(), 'end': m.end(), 
                    'pattern': single_txt_judge_pattern,
                    'judge_name1': m.group(1),
                    'date': m.group(2),
                    'court_room_no': m.group(3),
                    'bench_id': m.group(4)})

        single_txt_stage_pattern = '\*([\s\w()\d\.]+)\*'
        matches = re.finditer(single_txt_stage_pattern, page_txt)
        for m in matches:
            data_list.append({'start': m.start(), 'end': m.end(),
                    'pattern': single_txt_stage_pattern, 
                    'stage': m.group(1)})

        single_txt_case_pattern = ' (\d+)\.? *([\w\s()]*(\/| )\d+\/\d+) *([\w\s.]+)?(SMT[\w\s.,]+ (GP |AGP )|SHRI[\w\s.,]* *(GP |AGP )|MS[\w\s.,]+ (GP |AGP ))'
        matches = re.finditer(single_txt_case_pattern, page_txt)
        for m in matches:
            data_list.append({'start': m.start(), 'end': m.end(),
                    'pattern': single_txt_case_pattern, 
                    'serial_no': m.group(1),
                    'case_no': m.group(2),
                    'petitioner_advocate': m.group(4),
                    'respondent_advocate': m.group(5)})
        
        new_list = sorted(data_list, key=itemgetter('start'))
        judge_name1 = None
        date = None
        judge_name2 = ''
        court_room_no = None
        bench_id = None
        stage = None
        serial_no = None
        case_no = None
        petitioner_advocate = None
        respondent_advocate = None
        linked_cases = None
        additional_respondent_advocate = None
        for data_dict in new_list:
            if data_dict['pattern'] == single_txt_judge_pattern:
                judge_name1 = data_dict['judge_name1']
                date = data_dict['date']
                court_room_no = data_dict['court_room_no']
                bench_id = data_dict['bench_id']
            if data_dict['pattern'] == single_txt_stage_pattern:
                stage = data_dict['stage']
            if data_dict['pattern'] == single_txt_case_pattern:
                serial_no = data_dict['serial_no']
                case_no = data_dict['case_no']
                petitioner_advocate = data_dict['petitioner_advocate']
                respondent_advocate = data_dict['respondent_advocate']
            self.matter_dict = dict()
            self.matter_dict['judge_name1'] = judge_name1
            self.matter_dict['judge_name2'] = judge_name2
            self.matter_dict['date'] = date
            self.matter_dict['court_room_no'] = court_room_no
            self.matter_dict['bench_id'] = bench_id
            self.matter_dict['stage'] = stage
            self.matter_dict['serial_no'] = serial_no
            self.matter_dict['case_no'] = case_no
            self.matter_dict['petitioner_advocate'] = petitioner_advocate
            self.matter_dict['respondent_advocate'] = respondent_advocate
            self.matter_dict['linked_cases'] = linked_cases
            self.matter_dict['additional_respondent_advocate'] = additional_respondent_advocate
            self.matter_dict['filename'] = filename
            self.matter_list.append(self.matter_dict)

    def saveData(self, df):
        logging.info("Saving data")
        records = df.to_dict(orient="records")
        logging.debug(f"Records type: {type(records)}")
        for row in records:
            logging.debug(f"Row: {row}")
            formatted_date = row['date'].strftime('%Y/%m/%d')
            document_key = f"{formatted_date}/{row['case_no']}"
            doc_ref = self.db.collection("dataframes").document(document_key)
            doc_ref.set(row)
        logging.info("Data saved successfully")

    def getData(self, search_criteria):
        logging.info("Fetching data based on search criteria")
        
        if not any(search_criteria.values()):
            logging.error("Validation failed: At least one search criteria must be populated")
            raise HTTPException(status_code=400, detail="At least one search criteria must be populated")

        query = self.db.collection("dataframes")

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

        logging.info("Data fetched successfully")
        return data
