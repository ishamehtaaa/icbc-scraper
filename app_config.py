import json
import logging
import os
from typing import Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


# Configuration models
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
    driver_id: Optional[int] = None
    sharedHeaders: Dict[str, str]
    search_criteria: SearchCriteria
    endpoints: Dict[str, Endpoint]
    polling: Polling


def setup_logging(level=logging.INFO):
    """Setup logging with thread names in the format."""
    log = logging.getLogger()
    if log.handlers:
        return

    try:
        import colorlog

        handler = colorlog.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter(
                "%(log_color)s%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s",
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "white",
                    "WARNING": "green",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
            )
        )
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s"
            )
        )

    log.addHandler(handler)
    log.setLevel(level)


def load_settings(filepath: str) -> Optional[Settings]:
    """
    Load application settings from JSON file and validate required environment variables.

    Args:
        filepath: Path to the configuration JSON file

    Returns:
        Settings object if successful, None otherwise
    """
    log = logging.getLogger()
    load_dotenv()

    # Check if .env file exists with required credentials
    required_credentials = ["LAST_NAME", "LICENSE_NUMBER", "KEYWORD"]
    if not all(os.getenv(cred) for cred in required_credentials):
        log.critical(
            f"One or more required environment variables are missing.")
        log.critical(
            f"Please ensure {', '.join(required_credentials)} are set in your .env file."
        )
        return None

    try:
        if not os.path.exists(filepath):
            log.critical(f"Configuration file '{filepath}' not found.")
            return None

        with open(filepath, "r") as f:
            config_data = json.load(f)

        # If driver_id not set in config, try to set it from environment
        if "driver_id" not in config_data or not config_data["driver_id"]:
            driver_id_env = os.getenv("DRIVER_ID")
            if driver_id_env:
                try:
                    config_data["driver_id"] = int(driver_id_env)
                except ValueError:
                    log.warning(
                        "DRIVER_ID environment variable is not a valid integer."
                    )

        return Settings.parse_obj(config_data)
    except (ValidationError, json.JSONDecodeError) as e:
        log.critical(f"Configuration error in '{filepath}': {e}")
        return None


def format_appointment_message(slot_data, location_cache):
    """
    Format a user-friendly message about an available appointment.

    Args:
        slot_data: AppointmentSlot object
        location_cache: Dictionary of location information

    Returns:
        Formatted message string
    """
    from models import AppointmentSlot

    # Convert to AppointmentSlot if it's a dict
    if isinstance(slot_data, dict):
        slot = AppointmentSlot.parse_obj(slot_data)
    else:
        slot = slot_data

    location_info = location_cache.get(slot.posId)
    location_name = (
        f"{location_info.agency} ({location_info.city})"
        if location_info
        else f"ID: {slot.posId}"
    )

    return (
        f"APPOINTMENT FOUND! 🥳\n"
        f"  - Location: {location_name}\n"
        f"  - Date: {slot.appointmentDt.date} ({slot.appointmentDt.dayOfWeek})\n"
        f"  - Time: {slot.startTm}"
    )
