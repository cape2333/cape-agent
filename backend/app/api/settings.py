import json
from fastapi import APIRouter, Depends
import aiosqlite

from app.models.database import get_db
from app.models.schemas import AppSettings

router = APIRouter(prefix="/api")

SETTINGS_KEY = "app_settings"


async def _load_settings(db: aiosqlite.Connection) -> AppSettings:
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,))
    row = await cursor.fetchone()
    if row:
        return AppSettings.model_validate_json(row[0])
    return AppSettings()


async def _save_settings(db: aiosqlite.Connection, settings: AppSettings):
    val = settings.model_dump_json()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (SETTINGS_KEY, val),
    )
    await db.commit()


@router.get("/settings")
async def get_settings(db: aiosqlite.Connection = Depends(get_db)):
    return await _load_settings(db)


@router.put("/settings")
async def update_settings(
    settings: AppSettings,
    db: aiosqlite.Connection = Depends(get_db),
):
    await _save_settings(db, settings)
    return settings
