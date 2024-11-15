import pdfplumber
import pandas as pd
from main import db

class Board:
    def readFile(self, file):
        with pdfplumber.open(file) as pdf:
            first_page = pdf.pages[0]
            text = first_page.extract_text()

        data = [line.split() for line in text.split('\n') if line]
        df = pd.DataFrame(data[1:], columns=data[0])

        return df

    def saveData(self, df):
        doc_ref = db.collection("dataframes").document()
        doc_ref.set(df.to_dict(orient="records"))
