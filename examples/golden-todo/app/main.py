"""Golden Todo API — FastAPI application factory."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import models


def _env(name, default=""):
    return os.getenv(name, default)


def build_settings():
    return {
        "database_url": _env(
            "DATABASE_URL", "postgresql+psycopg://todo:todo@localhost:5432/todo"
        ),
        "jwt_secret": _env("JWT_SECRET", "dev-only-insecure-secret"),
        "jwt_algorithm": _env("JWT_ALGORITHM", "HS256"),
        "token_expire_minutes": int(_env("TOKEN_EXPIRE_MINUTES", "60")),
    }


settings = build_settings()
engine = create_engine(settings["database_url"], pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

bearer = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    completed: bool = False


class TodoOut(BaseModel):
    id: int
    title: str
    completed: bool
    owner_id: int


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Golden Todo API", version="1.0.0", lifespan=lifespan)


@app.get("/livez")
def livez():
    return {"status": "LIVE"}


@app.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    from . import security

    existing = db.query(models.User).filter(models.User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=409, detail="USERNAME_TAKEN")
    user = models.User(
        username=body.username,
        password_hash=security.hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = security.create_token(user.id, settings)
    return TokenOut(access_token=token)


@app.post("/auth/login", response_model=TokenOut)
def login(body: RegisterIn, db: Session = Depends(get_db)):
    from . import security

    user = db.query(models.User).filter(models.User.username == body.username).first()
    if not user or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    token = security.create_token(user.id, settings)
    return TokenOut(access_token=token)


def _current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings["jwt_secret"],
            algorithms=[settings["jwt_algorithm"]],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")
    user = db.get(models.User, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")
    return user


@app.get("/todos", response_model=list[TodoOut])
def list_todos(user: models.User = Depends(_current_user), db: Session = Depends(get_db)):
    rows = db.query(models.Todo).filter(models.Todo.owner_id == user.id).order_by(models.Todo.id).all()
    return rows


@app.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
def create_todo(
    body: TodoIn,
    user: models.User = Depends(_current_user),
    db: Session = Depends(get_db),
):
    row = models.Todo(title=body.title, completed=body.completed, owner_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.put("/todos/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: int,
    body: TodoIn,
    user: models.User = Depends(_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.Todo).filter(models.Todo.id == todo_id, models.Todo.owner_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="TODO_NOT_FOUND")
    row.title = body.title
    row.completed = body.completed
    db.commit()
    db.refresh(row)
    return row


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, user: models.User = Depends(_current_user), db: Session = Depends(get_db)):
    row = db.query(models.Todo).filter(models.Todo.id == todo_id, models.Todo.owner_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="TODO_NOT_FOUND")
    db.delete(row)
    db.commit()
    return None