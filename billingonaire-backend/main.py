from fastapi import FastAPI, File, UploadFile, Depends, Request, HTTPException, Form
import pandas as pd
from fastapi.responses import RedirectResponse, JSONResponse
import logging
from fastapi.middleware.cors import CORSMiddleware
from Board import Board
from firebase_admin import auth, firestore
from BombayHighCourt import BombayHighCourt

app = FastAPI(
    title="Billingonaire API",
    description="API for Billingonaire application",
    version="1.0.0",
    openapi_tags=[
        {"name": "Root", "description": "Root endpoint"},
        {"name": "PDF Upload", "description": "Upload PDF and extract data"},
        {"name": "Data Retrieval", "description": "Retrieve stored data"},
        {"name": "Authentication", "description": "User authentication"},
        {"name": "Case Status", "description": "Retrieve case status from Bombay High Court"},
        {"name": "Case Orders", "description": "Retrieve case orders from Bombay High Court"}
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_session(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        return None
    return session_token

def require_login(session_token: str = Depends(get_session)):
    if not session_token:
        return RedirectResponse(url="/login")

def check_user_role(session_token: str, required_role: str):
    try:
        decoded_claims = auth.verify_session_cookie(session_token, check_revoked=True)
        user_role = decoded_claims.get("role")
        if user_role != required_role:
            raise HTTPException(status_code=403, detail="Access forbidden: insufficient permissions")
    except Exception as e:
        raise HTTPException(status_code=403, detail="Access forbidden: insufficient permissions")

def require_role(required_role: str):
    def role_decorator(func):
        def wrapper(*args, **kwargs):
            session_token = get_session(args[0])
            check_user_role(session_token, required_role)
            return func(*args, **kwargs)
        return wrapper
    return role_decorator

def store_user_role(uid: str, role: str):
    db = firestore.client()
    doc_ref = db.collection("roles").document(uid)
    doc_ref.set({"role": role})

@app.post("/login", tags=["Authentication"])
async def login(request: Request):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")

    logging.debug(f"Login attempt for email: {email}")

    try:
        user = auth.get_user_by_email(email)
        auth.verify_password(password, user.password_hash)
        
        # Retrieve user role from Firestore
        db = firestore.client()
        doc_ref = db.collection("roles").document(user.uid)
        doc = doc_ref.get()
        if doc.exists:
            user_role = doc.to_dict().get("role")
        else:
            user_role = "user"
        
        # Set custom claims for roles
        auth.set_custom_user_claims(user.uid, {"role": user_role})
        
        session_cookie = auth.create_session_cookie(user.uid)
        response = JSONResponse(content={"message": "Login successful"})
        response.set_cookie(key="session", value=session_cookie, httponly=True)
        logging.info(f"Login successful for email: {email}")
        return response
    except Exception as e:
        logging.error(f"Login failed for email: {email}, error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid credentials")

@app.post("/logout", tags=["Authentication"])
async def logout(request: Request):
    response = JSONResponse(content={"message": "Logout successful"})
    response.delete_cookie("session")
    return response

@app.get("/", tags=["Root"], dependencies=[Depends(require_login)])
def read_root():
    return {"message": "Hello, World!"}

@app.post("/upload-pdf", tags=["PDF Upload"], dependencies=[Depends(require_login), Depends(require_role("admin"))])
async def upload_pdf(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files are allowed.")
    
    try:
        board = Board()
        df = board.readFile(file.file)

        # Call the saveBoardData method of the Board class to save the dataframe to Firestore
        board.saveData(df)
        return {"message": "Upload successful"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-data", tags=["Data Retrieval"], dependencies=[Depends(require_login), Depends(require_role("admin"))])
async def get_data(request: Request):
    try:
        search_criteria = await request.json()
        board = Board()
        data = board.getData(search_criteria)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/case-status/{case_type}/{case_number}/{year}", tags=["Case Status"], dependencies=[Depends(require_login), Depends(require_role("admin"))])
async def get_case_status(case_type: str, case_number: str, year: int):
    try:
        bombay_high_court = BombayHighCourt()
        case_status = bombay_high_court.get_case_status(case_type, case_number, year)
        return case_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/case-orders/{case_type}/{case_number}/{year}", tags=["Case Orders"], dependencies=[Depends(require_login), Depends(require_role("admin"))])
async def get_case_orders(case_type: str, case_number: str, year: int):
    try:
        bombay_high_court = BombayHighCourt()
        case_orders = bombay_high_court.get_case_orders(case_type, case_number, year)
        return case_orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
