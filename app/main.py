"""Каталог машин на FastAPI.

Что было не так:
- /add-car/ вызывал сам себя (функция называлась так же, как функция БД) — бесконечная рекурсия;
- GET и DELETE читали JSON из тела запроса, id не проверялся;
- добавлять и удалять машины мог кто угодно;
- год выпуска не сохранялся (функция БД не принимала year);
- строка подключения с паролем была в коде (и в публичной истории git).
"""
import hmac
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import DateTime, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    database_url: str = "sqlite:///./cars.db"
    # Ключ для изменения каталога. Пустой — изменение отключено
    admin_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


class Base(DeclarativeBase):
    pass


class Car(Base):
    __tablename__ = "cars"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    year: Mapped[int | None] = mapped_column(Integer)
    reg_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


_url = get_settings().database_url
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DbSession = Annotated[Session, Depends(get_db)]


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().admin_api_key
    if not expected or not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен заголовок X-API-Key")


class CarIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int | None = Field(default=None, ge=1886, le=datetime.now().year + 1)


class CarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    model: str
    year: int | None
    reg_date: datetime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Каталог машин", lifespan=lifespan)


@app.get("/cars", response_model=list[CarOut])
def list_cars(db: DbSession, q: str | None = Query(None, max_length=100),
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = select(Car).order_by(Car.id)
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(func.lower(Car.name).like(pattern) | func.lower(Car.model).like(pattern))
    return db.scalars(query.limit(limit).offset(offset)).all()


@app.get("/car/{car_id}", response_model=CarOut)
def get_exact_car_info(car_id: int, db: DbSession):
    car = db.get(Car, car_id)
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    return car


@app.post("/add-car", response_model=CarOut, status_code=status.HTTP_201_CREATED,
          dependencies=[Depends(require_admin)])
def add_car(data: CarIn, db: DbSession):
    car = Car(**data.model_dump())
    db.add(car)
    db.commit()
    return car


@app.delete("/car/{car_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_car(car_id: int, db: DbSession):
    car = db.get(Car, car_id)
    if car is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    db.delete(car)
    db.commit()
