import os
import json
import logging
import colorlog
from typing import List, Dict, Optional
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

class TokenPayload(BaseModel):
    drvrLastName: str
    # UPDATED: Using 'licenceNumber' to match the token API
    licenceNumber: str
    keyword: str

class Pos(BaseModel):
    posId: int
    agency: str
    city: str

# ... rest of the file is unchanged ...
class AppointmentDateTime(BaseModel):
    date: str
    dayOfWeek: str

class AppointmentSlot(BaseModel):
    appointmentDt: AppointmentDateTime
    startTm: str
    endTm: str
    posId: int
    resourceId: int
    signature: str

class ConfirmationDlExam(BaseModel):
    code: str
    description: str

class ConfirmationDrvrDriver(BaseModel):
    drvrId: str

class ConfirmationPayload(BaseModel):
    appointmentDt: AppointmentDateTime
    dlExam: ConfirmationDlExam
    drvrDriver: ConfirmationDrvrDriver
    bookedTs: str
    startTm: str
    endTm: str
    posId: int
    resourceId: int
    signature: str

class SearchCriteria(BaseModel):
    aPosID: List[int]
    examType: str
    prfDaysOfWeek: List[int]
    prfPartsOfDay: List[int]
    examDate: str
    latitude: float
    longitude: float

class Endpoint(BaseModel):
    url: str
    method: str

class Polling(BaseModel):
    baseIntervalSeconds: int
    randomJitterSeconds: int

class Settings(BaseModel):
    sharedHeaders: Dict[str, str]
    search_criteria: SearchCriteria
    endpoints: Dict[str, Endpoint]
    polling: Polling

def setup_logging(level=logging.INFO):
    log = logging.getLogger()
    if log.handlers:
        return
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
        log_colors={
            'DEBUG': 'cyan', 'INFO': 'white', 'WARNING': 'green',
            'ERROR': 'red', 'CRITICAL': 'bold_red',
        }))
    log.addHandler(handler)
    log.setLevel(level)

def format_appointment_message(slot: AppointmentSlot, location_cache: Dict[int, Pos]) -> str:
    location_info = location_cache.get(slot.posId)
    location_name = f"{location_info.agency} ({location_info.city})" if location_info else f"ID: {slot.posId}"
    return (f"APPOINTMENT FOUND! 🥳\n"
            f"  - Location: {location_name}\n"
            f"  - Date: {slot.appointmentDt.date} ({slot.appointmentDt.dayOfWeek})\n"
            f"  - Time: {slot.startTm}")

def load_settings(filepath: str) -> Optional[Settings]:
    log = logging.getLogger()
    load_dotenv()
    # This remains 'LICENSE_NUMBER' as it's just the key for the .env file
    required_credentials = ["LAST_NAME", "LICENSE_NUMBER", "KEYWORD"]
    if not all(os.getenv(cred) for cred in required_credentials):
        log.critical(f"One or more required environment variables are missing.")
        log.critical(f"Please ensure {', '.join(required_credentials)} are set in your .env file.")
        return None
    try:
        if not os.path.exists(filepath):
            log.critical(f"Configuration file '{filepath}' not found.")
            return None
        with open(filepath, 'r') as f:
            config_data = json.load(f)
        return Settings.parse_obj(config_data)
    except (ValidationError, json.JSONDecodeError) as e:
        log.critical(f"Configuration error in '{filepath}': {e}")
        return None
