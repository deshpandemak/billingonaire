from fastapi import FastAPI, File, UploadFile
import pandas as pd
import pdfplumber
import firebase_admin
from firebase_admin import credentials, firestore

app = FastAPI()

cred = credentials.Certificate("path/to/your/firebase/credentials.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    with pdfplumber.open(file.file) as pdf:
        first_page = pdf.pages[0]
        text = first_page.extract_text()

    # Assuming the PDF contains tabular data
    data = [line.split() for line in text.split('\n') if line]
    df = pd.DataFrame(data[1:], columns=data[0])

    # Store dataframe in Firestore
    doc_ref = db.collection("dataframes").document()
    doc_ref.set(df.to_dict(orient="records"))

    return df.to_json()

@app.get("/get-data")
def get_data():
    docs = db.collection("dataframes").stream()
    data = []
    for doc in docs:
        data.extend(doc.to_dict())
    return data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
