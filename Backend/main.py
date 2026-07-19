import fastapi
import enum

import pydantic
import bcrypt
import jwt
import os
import uuid
from typing import Literal
import datetime
import random
from dotenv import load_dotenv
import mysql.connector as sql
from mysql.connector.pooling import MySQLConnectionPool
from fastapi import Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set - add it to .env before starting, otherwise JWTs would be forgeable")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
if not GOOGLE_CLIENT_ID:
    raise RuntimeError("GOOGLE_CLIENT_ID is not set - add it to .env before starting, otherwise Google sign-in cannot verify tokens")
db_password = os.getenv("DB_PASSWORD")

# Local dev's MySQL account is provisioned for mysql_native_password. Most
# managed MySQL hosts (Railway, PlanetScale, etc.) default to
# caching_sha2_password instead, so this is overridable per-environment -
# set DB_AUTH_PLUGIN="" in production to let the server pick automatically.
_db_auth_plugin = os.getenv("DB_AUTH_PLUGIN", "mysql_native_password")
_pool_kwargs = dict(
    pool_name="main_pool",
    pool_size=5,
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "python_user"),
    password=db_password,
    database=os.getenv("DB_NAME", "suku"),
)
if _db_auth_plugin:
    _pool_kwargs["auth_plugin"] = _db_auth_plugin
pool = MySQLConnectionPool(**_pool_kwargs)
def get_db():
    con = pool.get_connection()
    cur = con.cursor()
    try:
        yield con, cur
    finally:
        cur.close()
        con.close()
class CHAPTER(str,enum.Enum):
    Differentiation="Differentiation"
    limits="Limits and Continuity"
    AOD="Applications of Differentiation"
    II="Indefinite Integrals"
    DI="Definite Integrals"
    AI="Applications of Integration"
    DE="Differential Equations"
    SS="Sequence & Series"
    FN="Functions"
class QuestionIn(pydantic.BaseModel):
    ID:str
    Chapter:str
    Grade:int
    Question:str
    option1:str
    option2:str
    option3:str
    option4:str
    Graph:str|None=None
class QuizPayload(pydantic.BaseModel):
    questions:list[QuestionIn]
    calculatorCount:int
    nonCalculatorCount:int
class QuestionOut(pydantic.BaseModel):
    ID:str
    Chapter:str
    Topic:str
    Grade:int
    Type:Literal["Calculator-Section","Non-Calculator-Section"]
    Question:str
    Answer:str
    Solution:str
class FRQ(pydantic.BaseModel):
    ID:str
    Chapter:str
    Topic:str
    Grade:int
    Type:Literal["Calculator-Section","Non-Calculator-Section"]
    PartA:str
    PartB:str
    PartC:str
    PartD:str
    AnswerPartA:str
    AnswerPartB:str
    AnswerPartC:str
    AnswerPartD:str
    Graph:str|None=None

class FRQIN(pydantic.BaseModel):
    ID:str
    Chapter:str
    Topic:str
    Grade:int
    Type:Literal["Calculator-Section","Non-Calculator-Section"]
    PartA:str
    PartB:str
    PartC:str
    PartD:str
    Graph:str|None=None

class FRQOUT(pydantic.BaseModel):
    ID:str
    Chapter:str
    Topic:str
    Grade:int
    Type:Literal["Calculator-Section","Non-Calculator-Section"]
    AnswerPartA:str
    AnswerPartB:str
    AnswerPartC:str
    AnswerPartD:str



class Question(pydantic.BaseModel):
    ID: str
    Chapter: str
    Topic: str
    Grade: int
    Type: Literal["Calculator-Section", "Non-Calculator-Section"]
    Question: str
    option1: str
    option2: str
    option3: str
    option4: str
    Answer: str
    Solution: str
    Graph:str|None=None
class UserRegister(pydantic.BaseModel):
    name: str = pydantic.Field(min_length=1, max_length=100)
    email: pydantic.EmailStr
    password: str = pydantic.Field(min_length=8, max_length=72)
class GRADE(int,enum.Enum):
    one=1
    two=2
    three=3
    four=4
    five=5
class UserLogin(pydantic.BaseModel):
    email: pydantic.EmailStr
    password: str = pydantic.Field(min_length=1, max_length=72)
class GoogleAuth(pydantic.BaseModel):
    credential: str
class answer(pydantic.BaseModel):
    ID:str
    Answer:str
def _load_questions() -> list[Question]:
    con = pool.get_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT ID,Chapter,Topic,Grade,Type,Question,option1,option2,option3,option4,Answer,Solution,Graph FROM questions")
        rows = cur.fetchall()
        if not rows:
            print("WARNING: questions table is empty. Run migrate_questions.py first.")
        return [Question(ID=r[0],Chapter=r[1],Topic=r[2],Grade=r[3],Type=r[4],Question=r[5],option1=r[6],option2=r[7],option3=r[8],option4=r[9],Answer=r[10],Solution=r[11],Graph=r[12]) for r in rows]
    finally:
        cur.close()
        con.close()
QO:list[Question]=_load_questions()
def _load_samplepapers() -> list:
    con = pool.get_connection()
    cur = con.cursor()
    try:
        cur.execute(
            "SELECT ID,QType,Chapter,Topic,Grade,Type,Question,option1,option2,option3,option4,"
            "Answer,Solution,PartA,PartB,PartC,PartD,AnswerPartA,AnswerPartB,AnswerPartC,AnswerPartD,Graph "
            "FROM samplepaper"
        )
        rows = cur.fetchall()
        if not rows:
            print("WARNING: samplepaper table is empty. Run migrate_samplepaper.py first.")
        result:list=[]
        for r in rows:
            if r[1]=="MCQ":
                result.append(Question(ID=r[0],Chapter=r[2],Topic=r[3],Grade=r[4],Type=r[5],Question=r[6],option1=r[7],option2=r[8],option3=r[9],option4=r[10],Answer=r[11],Solution=r[12],Graph=r[21]))
            else:
                result.append(FRQ(ID=r[0],Chapter=r[2],Topic=r[3],Grade=r[4],Type=r[5],PartA=r[13],PartB=r[14],PartC=r[15],PartD=r[16],AnswerPartA=r[17],AnswerPartB=r[18],AnswerPartC=r[19],AnswerPartD=r[20],Graph=r[21]))
        return result
    finally:
        cur.close()
        con.close()
SS:list=_load_samplepapers()
def _load_frq() -> list[FRQ]:
    con = pool.get_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT ID,Chapter,Topic,Grade,Type,PartA,PartB,PartC,PartD,AnswerPartA,AnswerPartB,AnswerPartC,AnswerPartD,Graph FROM frq")
        rows = cur.fetchall()
        if not rows:
            print("WARNING: frq table is empty. Run migrate_frq.py first.")
        return [FRQ(ID=r[0],Chapter=r[1],Topic=r[2],Grade=r[3],Type=r[4],PartA=r[5],PartB=r[6],PartC=r[7],PartD=r[8],AnswerPartA=r[9],AnswerPartB=r[10],AnswerPartC=r[11],AnswerPartD=r[12],Graph=r[13]) for r in rows]
    finally:
        cur.close()
        con.close()
FR:list[FRQ]=_load_frq()
def genQ(chap:str,grade:int):
    filtered:list[Question]=[]
    if grade is not None:
        for i in QO:
            if i.Chapter==chap and i.Grade==grade :
                filtered.append(i)
        if not filtered:
            raise fastapi.HTTPException(status_code=404, detail="No question found")
        return random.choice(filtered)
    if grade is None:
        for i in QO:
            if i.Chapter==chap:
                filtered.append(i)
        if not filtered:
            raise fastapi.HTTPException(status_code=404, detail="No question found")
        return random.choice(filtered)
def resolve_answer(q):
    ans = q.Answer.strip()
    if ans.lower() in ("option1", "option2", "option3", "option4"):
        return getattr(q, ans.lower())
    return ans
app=fastapi.FastAPI()

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# comma-separated: lets both a production domain and a Vercel preview URL work at once
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGIN", "http://127.0.0.1:5500").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

# jti -> token expiry (unix time); purged once the token would have expired anyway
revoked_tokens:dict[str,float] = {}
def _purge_revoked():
    now = datetime.datetime.utcnow().timestamp()
    for jti in [j for j, exp in revoked_tokens.items() if exp < now]:
        revoked_tokens.pop(jti, None)
_security=HTTPBearer()
def get_current_user(credentials:HTTPAuthorizationCredentials=Depends(_security)):
    try:
        payload = jwt.decode(credentials.credentials,SECRET_KEY,algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise fastapi.HTTPException(status_code=401,detail="Token expired")
    except jwt.InvalidTokenError:
        raise fastapi.HTTPException(status_code=401,detail="Invalid token")
    if payload.get("jti") in revoked_tokens:
        raise fastapi.HTTPException(status_code=401,detail="Token has been revoked")
    return payload
@app.post("/register")
@limiter.limit("3/minute")
async def register(request: Request, data: UserRegister,db=Depends(get_db)):
    con,cur=db
    hashed = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt())
    try:
        cur.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
            (data.name, data.email, hashed.decode())
        )
        con.commit()
        return {"Message": "Account created"}
    except sql.IntegrityError:
        raise fastapi.HTTPException(status_code=400, detail="Email already exists")
_DUMMY_HASH = bcrypt.hashpw(uuid.uuid4().bytes, bcrypt.gensalt())
@app.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, data: UserLogin,db=Depends(get_db)):
    con,cur=db
    cur.execute("SELECT id, name, password FROM users WHERE email = %s", (data.email,))
    user = cur.fetchone()
    if not user or not user[2]:
        # burn the same bcrypt cost as a real check so response timing
        # can't reveal whether the email has an account
        bcrypt.checkpw(data.password.encode(), _DUMMY_HASH)
        raise fastapi.HTTPException(status_code=401, detail="Invalid email or password")
    if not bcrypt.checkpw(data.password.encode(), user[2].encode()):
        raise fastapi.HTTPException(status_code=401, detail="Invalid email or password")
    token = jwt.encode({
        "user_id": user[0],
        "name": user[1],
        "jti": str(uuid.uuid4()),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, SECRET_KEY, algorithm="HS256")
    return {"token": token, "name": user[1]}

@app.post("/auth/google")
@limiter.limit("10/minute")
async def google_auth(request: Request, data: GoogleAuth, db=Depends(get_db)):
    con,cur=db
    try:
        idinfo = google_id_token.verify_oauth2_token(data.credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError:
        raise fastapi.HTTPException(status_code=401, detail="Invalid Google token")
    if not idinfo.get("email_verified"):
        raise fastapi.HTTPException(status_code=401, detail="Google email not verified")
    email = idinfo["email"]
    name = (idinfo.get("name") or email.split("@")[0])[:100]
    cur.execute("SELECT id, name FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    if user:
        user_id, user_name = user
    else:
        cur.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, None))
        con.commit()
        user_id, user_name = cur.lastrowid, name
    token = jwt.encode({
        "user_id": user_id,
        "name": user_name,
        "jti": str(uuid.uuid4()),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, SECRET_KEY, algorithm="HS256")
    return {"token": token, "name": user_name}

@app.post("/logout")
async def logout(user=Depends(get_current_user)):
    _purge_revoked()
    jti = user.get("jti")
    if jti:
        revoked_tokens[jti] = float(user.get("exp", 0)) or (
            datetime.datetime.utcnow() + datetime.timedelta(days=7)
        ).timestamp()
    return {"Message": "Logged out"}
@app.get("/generateQuestion",response_model=QuestionIn)
async def generate(chapter:CHAPTER,grade:GRADE|None=None,db=Depends(get_db),user=Depends(get_current_user)):
    return genQ(chapter.value,grade.value if grade is not None else None)

@app.get('/generateQuiz',response_model=QuizPayload)
async def GENERATEQUIZ(chap:CHAPTER,db=Depends(get_db),user=Depends(get_current_user)):
    filtered:list[Question]=[]
    y:list[Question]=[]
    x:list[Question]=[]
    for f in QO:
        if f.Chapter==chap.value and f.Type=="Calculator-Section":
            filtered.append(f)
    calc_picked = random.sample(filtered,min(8,len(filtered)))
    x.extend(calc_picked)
    for q in QO:
        if q.Chapter==chap.value and q.Type=="Non-Calculator-Section":
            y.append(q)
    noncalc_picked = random.sample(y,min(7,len(y)))
    x.extend(noncalc_picked)
    random.shuffle(x)
    return {"questions": x, "calculatorCount": len(calc_picked), "nonCalculatorCount": len(noncalc_picked)}
@app.post('/AnswerQuiz')
async def checkQuiz(ans:list[answer],db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    wrong=[]
    right=[]
    details=[]
    for i in QO:
        for k in ans:
            if i.ID==k.ID:
                correct_text = resolve_answer(i)
                if correct_text.strip().lower()==k.Answer.strip().lower():
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],i.ID, i.Chapter, i.Topic, i.Grade, i.Type, i.Question,k.Answer, correct_text,"Correct")
                    )
                    con.commit()
                    right.append(k.ID)
                    details.append({"ID":i.ID,"Correct":True,"CorrectAnswer":correct_text,"Solution":i.Solution})
                if correct_text.strip().lower()!=k.Answer.strip().lower():
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],i.ID, i.Chapter, i.Topic, i.Grade, i.Type, i.Question,k.Answer, correct_text,"Wrong")
                    )
                    con.commit()
                    wrong.append(k.ID)
                    details.append({"ID":i.ID,"Correct":False,"CorrectAnswer":correct_text,"Solution":i.Solution})
    total=len(ans)
    if len(right)==total:
        return {"Message":"All are right","Score":"{}/{}".format(total,total),"Details":details}
    else:
        return {"Score":"{}/{}".format(len(right),total),"Wrong Question ID":"{}".format(wrong),"Details":details}
@app.post("/answerQuestion")
async def Ques(data: answer,db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    for i in QO:
        if i.ID == data.ID:
            correct_text = resolve_answer(i)
            if correct_text.strip().lower() == data.Answer.strip().lower():
                cur.execute(
                    "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user["user_id"],i.ID, i.Chapter, i.Topic, i.Grade, i.Type, i.Question,data.Answer, correct_text, "Correct")
                )
                con.commit()
                return {"Correct": True, "CorrectAnswer": correct_text, "Solution": i.Solution}
            else:
                cur.execute(
                    "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user["user_id"],i.ID, i.Chapter, i.Topic,i.Grade,i.Type ,i.Question, data.Answer, correct_text, "Wrong")
                )
                con.commit()
                return {"Correct": False, "CorrectAnswer": correct_text, "Solution": i.Solution}
    raise fastapi.HTTPException(status_code=404, detail="Question not found")

class ReportIn(pydantic.BaseModel):
    QuestionID:str
    Chapter:str
    Reason:Literal["Question is wrong","All the options are wrong","Question leaks the answer","Other"]
    Details:str=""
@app.post('/ReportQuestion')
@limiter.limit("20/minute")
async def ReportQuestion(request:Request, data:ReportIn, db=Depends(get_db), user=Depends(get_current_user)):
    con,cur=db
    if data.Reason=="Other" and not data.Details.strip():
        raise fastapi.HTTPException(status_code=400, detail="Please describe the issue")
    cur.execute(
        "INSERT INTO report (QuestionID,Chapter,Reason,Details,UserID) VALUES (%s,%s,%s,%s,%s)",
        (data.QuestionID, data.Chapter, data.Reason, data.Details.strip(), str(user["user_id"]))
    )
    con.commit()
    return {"Message":"Report submitted"}

@app.get('/getHistory')
async def history(db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    cur.execute("SELECT * FROM calculusbc WHERE user_id = %s",(user["user_id"],))
    rows = cur.fetchall()
    return [
        {
            "QuestionID": r[1],
            "Chapter": r[2],
            "Grade": r[4],
            "Question": r[6],
            "Answer": r[7],
            "Correct_Answer": r[8],
            "status": r[9]
        }
        for r in rows
    ]

@app.get('/getStats')
async def stats(chapter: CHAPTER,db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    cur.execute("SELECT * FROM calculusbc WHERE CHAPTER = %s AND USER_ID = %s", (chapter.value,user["user_id"]))
    l = cur.fetchall()
    if not l:
        return {"Accuracy": 0}
    crct = [i for i in l if i[9] == "Correct"]
    return {"Accuracy": round((len(crct) / len(l)) * 100, 1)}
class Cal(enum.Enum):
    calc="Calculator-Section"
    ncalc="Non-Calculator-Section"
@app.get('/CalcSection',response_model=list[QuestionIn])
async def Calc(c:Cal,chap:CHAPTER|None=None,db=Depends(get_db),user=Depends(get_current_user)):
    filtered:list[Question]=[]
    for i in QO:
        if chap is None:
            if i.Type==c.value:
                filtered.append(i)
        else:
            if i.Type==c.value and i.Chapter==chap.value:
                filtered.append(i)
    if not filtered:
        raise fastapi.HTTPException(status_code=404, detail="No questions found")
    return random.sample(filtered,min(10,len(filtered)))

@app.post('/AnswerCalcSection')
async def ansCalc(ans:list[answer],db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    crcans=[]
    wrgans=[]
    for f in QO:
        for i in ans:
            if i.ID==f.ID:
                correct_text = resolve_answer(f)
                if correct_text.strip().lower()==i.Answer.strip().lower():
                    crcans.append(i.ID)
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],f.ID, f.Chapter, f.Topic, f.Grade, f.Type, f.Question,i.Answer, correct_text, "Correct")
                    )
                    con.commit()
                elif correct_text.strip().lower()!=i.Answer.strip().lower():
                    wrgans.append(i.ID)
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],f.ID, f.Chapter, f.Topic, f.Grade, f.Type, f.Question,i.Answer, correct_text, "Wrong")
                    )
                    con.commit()
    total=len(ans)
    if len(crcans)==total:
        return{"Score":"{}/{}".format(total,total),"Message":"All correct"}
    else:
        return {"Score":"{}/{}".format(len(crcans),total),"Wrong Question ID":wrgans}
class TYPE(enum.Enum):
    calc="Calculator-Section"
    ncalc="Non-Calculator-Section"

@app.get('/getTopics')
async def getTopics(chap:CHAPTER,user=Depends(get_current_user)):
    return {"topics": sorted({i.Topic for i in QO if i.Chapter==chap.value})}

@app.get('/AdvancedCusQuestions',response_model=list[QuestionIn])
async def AdvancedQues(chap:CHAPTER,n:int=fastapi.Query(..., ge=1, le=50),grad:GRADE|None=None,type:TYPE|None=None,topic:str|None=None,db=Depends(get_db),user=Depends(get_current_user)):
    if topic is not None:
        valid_topics = {i.Topic for i in QO if i.Chapter==chap}
        if topic not in valid_topics:
            raise fastapi.HTTPException(status_code=400, detail="Invalid topic for this chapter")
    filtered:list[Question]=[]
    if chap is not None and grad is None and type is None and topic is None:
        for i in QO:
            if i.Chapter==chap.value:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is not None and type is None and topic is None:
        for i in QO:
            if i.Chapter==chap.value and i.Grade==grad.value:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is not None and type is not None and topic is None:
        for i in QO:
            if i.Chapter==chap.value and i.Grade==grad.value and i.Type==type.value:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is not None and type is not None and topic is not None:
        for i in QO:
            if i.Chapter==chap.value and i.Grade==grad.value and i.Type==type.value and i.Topic==topic:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is None and topic is not None and type is not None:
        for i in QO:
            if i.Chapter==chap.value and i.Type==type.value and i.Topic==topic:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is not None and type is None and topic is not None:
        for i in QO:
            if i.Chapter==chap.value and i.Grade==grad.value and i.Topic==topic:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is None and type is None and topic is not None:
        for i in QO:
            if i.Chapter==chap.value and i.Topic==topic:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
    if chap is not None and grad is None and type is not None and topic is None:
        for i in QO:
            if i.Chapter==chap.value and i.Type==type.value:
                filtered.append(i)
        return random.sample(filtered,min(n,len(filtered)))
@app.post('/AnswerAdvancedQues')
async def answerAdvancedQues(ans:list[answer],db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    crcans=[]
    wrgans=[]
    for f in QO:
        for i in ans:
            if i.ID==f.ID:
                correct_text = resolve_answer(f)
                if correct_text.strip().lower()==i.Answer.strip().lower():
                    crcans.append(i.ID)
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],f.ID, f.Chapter, f.Topic, f.Grade, f.Type, f.Question,i.Answer, correct_text, "Correct")
                    )
                    con.commit()
                elif correct_text.strip().lower()!=i.Answer.strip().lower():
                    wrgans.append(i.ID)
                    cur.execute(
                        "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user["user_id"],f.ID, f.Chapter, f.Topic, f.Grade, f.Type, f.Question,i.Answer, correct_text, "Wrong")
                    )
                    con.commit()
    total=len(ans)
    if len(crcans)==total:
        return{"Score":"{}/{}".format(total,total),"Message":"All correct"}
    else:
        return {"Score":"{}/{}".format(len(crcans),total),"Wrong Question ID":wrgans}



@app.get('/ProgressRadar')
async def graph(db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    l=["Functions","Limits and Continuity","Differentiation","Applications of Differentiation","Indefinite Integrals","Definite Integrals","Applications of Integration","Differential Equations","Sequence & Series"]
    perc=[]
    for i in l:
        crcans=[]
        cur.execute("SELECT * FROM calculusbc WHERE CHAPTER=%s AND USER_ID=%s",(i,user["user_id"]))
        x=cur.fetchall()
        for v in x:
            if v[9]=='Correct':
                crcans.append(v)
        if len(x)==0:
            value=0
        else:
            value=(len(crcans)/len(x))*100
        perc.append(value)
    return perc

@app.get('/rank')
async def ShowRank(chap:CHAPTER,db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    cur.execute("SELECT * FROM calculusbc WHERE CHAPTER = %s AND USER_ID = %s", (chap.value,user["user_id"]))
    l = cur.fetchall()
    if l==[]:
        return 0
    crct = [i for i in l if i[9] == "Correct"]
    if  round((len(crct) / len(l)) * 100, 1)>=75:
        return 5
    elif  round((len(crct) / len(l)) * 100, 1)>=60 and  round((len(crct) / len(l)) * 100, 1)<75:
        return 4
    elif  round((len(crct) / len(l)) * 100, 1)>=40 and  round((len(crct) / len(l)) * 100, 1)<60:
        return 3
    elif  round((len(crct) / len(l)) * 100, 1)>=30 and  round((len(crct) / len(l)) * 100, 1)<40:
        return 2
    elif  round((len(crct) / len(l)) * 100, 1)<30:
        return 1

@app.get('/WeakAreas')
async def showweak(db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    cur.execute("select *from calculusbc where USER_ID=%s",(user["user_id"],))
    x=cur.fetchall()
    wrganst=[]
    for i in x:
        if i[9]=='Wrong':
            wrganst.append(i[3])
    topics=[]
    for i in reversed(wrganst):
        v=wrganst.pop(wrganst.index(i))
        if v in wrganst:
            continue
        else:
            topics.append(v)
    for i in x:
        if i[9]=='Wrong':
            wrganst.append(i[3])
    occurences=[]
    for i in topics:
        w=wrganst.count(i)
        occurences.append(w)
    ord=[]
    if len(occurences)>=3:
        for i in range(3):
            m=max(occurences)
            for i in topics:
                if wrganst.count(i)==m:
                    ord.append(i)
            occurences.pop(occurences.index(m))
        return ord
    elif len(occurences)==0:
        return {"Message":"No Topics Yet"}
    else:
        while occurences:
            m=max(occurences)
            for i in topics:
                if wrganst.count(i)==m:
                    ord.append(i)
            occurences.pop(occurences.index(m))
        return ord

class paper(enum.Enum):
    paper1='BC-EXAM1'
    paper2='BC-EXAM2'
    paper3='BC-EXAM3'
    paper4='BC-EXAM4'
    paper5='BC-EXAM5'
    paper6='BC-EXAM6'
    paper7='BC-EXAM7'
    paper8='BC-EXAM8'
    paper9='BC-EXAM9'
    paper10='BC-EXAM10'
class SamplePaperQuestionOut(pydantic.BaseModel):
    ID:str
    Chapter:str
    Grade:int
    Type:Literal["Calculator-Section","Non-Calculator-Section"]
    Question:str
    option1:str
    option2:str
    option3:str
    option4:str
    Graph:str|None=None
class SamplePaperOut(pydantic.BaseModel):
    mcq:list[SamplePaperQuestionOut]
    frq:list[FRQIN]
@app.get('/SamplePaper',response_model=SamplePaperOut)
async def GetSamplePaperFull(p:paper,user=Depends(get_current_user)):
    mcq=[i for i in SS if isinstance(i,Question) and i.ID.startswith(p.value+"-")]
    frq=[i for i in SS if isinstance(i,FRQ) and i.ID.startswith(p.value+"-")]
    if not mcq and not frq:
        raise fastapi.HTTPException(status_code=404, detail="Sample paper not found")
    return {"mcq":mcq,"frq":frq}

@app.get('/SamplePaperFRQAnswer',response_model=FRQOUT)
async def RevealSamplePaperFRQAnswer(id:str,user=Depends(get_current_user)):
    for i in SS:
        if isinstance(i,FRQ) and i.ID==id:
            return i
    raise fastapi.HTTPException(status_code=404, detail="FRQ not found")

class FRQSelfScore(pydantic.BaseModel):
    ID:str
    Score:int=pydantic.Field(ge=0,le=9)
class SamplePaperAnswer(pydantic.BaseModel):
    mcq:list[answer]=[]
    frq:list[FRQSelfScore]=[]
@app.post('/AnswerSamplePaper')
async def AnswerSamplePaper(payload:SamplePaperAnswer,db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    crcans=[]
    wrgans=[]
    mcq_details=[]
    for f in SS:
        if not isinstance(f,Question):
            continue
        for i in payload.mcq:
            if i.ID==f.ID:
                correct_text=resolve_answer(f)
                is_correct=correct_text.strip().lower()==i.Answer.strip().lower()
                status="Correct" if is_correct else "Wrong"
                (crcans if is_correct else wrgans).append(i.ID)
                mcq_details.append({"ID":f.ID,"Correct":is_correct,"YourAnswer":i.Answer,"CorrectAnswer":correct_text,"Solution":f.Solution})
                cur.execute(
                    "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user["user_id"],f.ID,f.Chapter,f.Topic,f.Grade,f.Type,f.Question,i.Answer,correct_text,status)
                )
                con.commit()
    frq_results=[]
    for f in SS:
        if not isinstance(f,FRQ):
            continue
        for i in payload.frq:
            if i.ID==f.ID:
                status="Correct" if i.Score>=5 else "Wrong"
                frq_results.append({"ID":f.ID,"Score":i.Score})
                cur.execute(
                    "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user["user_id"],f.ID,f.Chapter,f.Topic,f.Grade,f.Type,f.PartA,"{}/9".format(i.Score),"9/9",status)
                )
                con.commit()
    result:dict={"FRQ Self-Scores":frq_results}
    if payload.mcq:
        result["MCQ Score"]="{}/{}".format(len(crcans),len(payload.mcq))
        result["Wrong MCQ IDs"]=wrgans
        result["MCQ Details"]=mcq_details
    return result



@app.get('/FreeResponse',response_model=list[FRQIN])
async def GetFreeResponse(chap:CHAPTER,x:int=fastapi.Query(...,ge=1,le=20),user=Depends(get_current_user)):
    filtered:list[FRQ]=[i for i in FR if i.Chapter==chap.value]
    return random.sample(filtered,min(x,len(filtered)))

@app.get('/FreeResponseAnswer',response_model=FRQOUT)
async def RevealFreeResponseAnswer(id:str,user=Depends(get_current_user)):
    for i in FR:
        if i.ID==id:
            return i
    raise fastapi.HTTPException(status_code=404, detail="FRQ not found")

@app.post('/AnswerFreeResponse')
async def AnswerFreeResponse(ans:list[FRQSelfScore],db=Depends(get_db),user=Depends(get_current_user)):
    con,cur=db
    results=[]
    for f in FR:
        for i in ans:
            if i.ID==f.ID:
                status="Correct" if i.Score>=5 else "Wrong"
                results.append({"ID":f.ID,"Score":i.Score})
                cur.execute(
                    "INSERT INTO calculusbc VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user["user_id"],f.ID,f.Chapter,f.Topic,f.Grade,f.Type,f.PartA,"{}/9".format(i.Score),"9/9",status)
                )
                con.commit()
    return {"FRQ Self-Scores":results}



            



            

    












