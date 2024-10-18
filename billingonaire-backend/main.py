from fastapi import FastAPI, File, UploadFile
import pandas as pd
import pdfplumber

app = FastAPI()

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

    return df.to_json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
