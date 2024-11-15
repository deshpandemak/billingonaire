from fastapi import FastAPI, File, UploadFile, Depends, Request, HTTPException, Form
import pandas as pd
from fastapi.responses import RedirectResponse, JSONResponse
import logging
from fastapi.middleware.cors import CORSMiddleware
from Board import Board
from firebase_admin import auth

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

@app.post("/login", tags=["Authentication"])
async def login(request: Request):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")

    logging.debug(f"Login attempt for email: {email}")

    try:
        user = auth.get_user_by_email(email)
        auth.verify_password(password, user.password_hash)
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

@app.post("/upload-pdf", tags=["PDF Upload"], dependencies=[Depends(require_login)])
async def upload_pdf(file: UploadFile = File(...)):
    logging.debug(f"File upload attempt: {file.filename}")

    if file.content_type != "application/pdf":
        logging.error(f"Invalid file type: {file.content_type}")
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files are allowed.")
    
    try:
        board = Board()
        df = board.readFile(file.file)

        # Call the saveBoardData method of the Board class to save the dataframe to Firestore
        board.saveData(df)
        logging.info("Data saved")
        logging.info(f"File upload successful: {file.filename}")
        return {"message": "Upload successful"}
    except Exception as e:
        logging.error(f"File upload failed: {file.filename}, error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-data", tags=["Data Retrieval"], dependencies=[Depends(require_login)])
async def get_data(request: Request):
    logging.debug("Data retrieval attempt")

    try:
        search_criteria = await request.json()
        board = Board()
        data = board.getData(search_criteria)
        logging.info("Data retrieval successful")
        return data
    except Exception as e:
        logging.error(f"Data retrieval failed, error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
