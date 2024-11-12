from fastapi import FastAPI, File, UploadFile, Depends, Request, HTTPException
import pandas as pd
import pdfplumber
import firebase_admin
from firebase_admin import credentials, firestore, auth
from fastapi.responses import RedirectResponse, JSONResponse

app = FastAPI(
    title="Billingonaire API",
    description="API for Billingonaire application",
    version="1.0.0",
    openapi_tags=[
        {"name": "Root", "description": "Root endpoint"},
        {"name": "PDF Upload", "description": "Upload PDF and extract data"},
        {"name": "Data Retrieval", "description": "Retrieve stored data"},
        {"name": "Authentication", "description": "User authentication"}
    ]
)

cred = credentials.Certificate("./firebase/credentials.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

def get_session(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return None
    return session_token

def require_login(session_token: str = Depends(get_session)):
    if not session_token:
        return RedirectResponse(url="/login")

@app.post("/login", tags=["Authentication"])
async def login(request: Request):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")

    try:
        user = auth.get_user_by_email(email)
        auth.verify_password(password, user.password_hash)
        session_cookie = auth.create_session_cookie(user.uid)
        response = JSONResponse(content={"message": "Login successful"})
        response.set_cookie(key="session", value=session_cookie, httponly=True)
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid credentials")

@app.post("/logout", tags=["Authentication"])
async def logout(request: Request):
    response = JSONResponse(content={"message": "Logout successful"})
    response.delete_cookie("session")
    return response

@app.get("/", tags=["Root"], dependencies=[Depends(require_login)])
def read_root():
    return {"message": "Hello, World!"}

@app.post("/upload-pdf", tags=["PDF Upload"], dependencies=[Depends(require_login)])
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

@app.get("/get-data", tags=["Data Retrieval"], dependencies=[Depends(require_login)])
def get_data():
    docs = db.collection("dataframes").stream()
    data = []
    for doc in docs:
        data.extend(doc.to_dict())
    return data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
