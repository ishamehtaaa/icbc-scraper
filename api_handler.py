import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from models import (
    AppointmentSlot,
    BookAppointment,
    BookDrvrDriver,
    BookPayload,
    ConfirmationPayload,
    Location,
    OtpPayload,
    VerifyOtpPayload,
)


class ICBCApiClient:
    """Client for interacting with ICBC appointment booking API endpoints."""

    def __init__(self, settings, detailed: bool = False):
        self.log = logging.getLogger(__name__)
        self.settings = settings
        self.session = requests.Session()
        self.last_name = os.getenv("LAST_NAME")
        self.license_number = os.getenv("LICENSE_NUMBER")
        self.keyword = os.getenv("KEYWORD")
        self.driver_id = settings.driver_id
        self.detailed = detailed
        self.location_cache: Dict[int, Location] = {}

        # Set default headers
        self.session.headers.update(settings.sharedHeaders)

        # Get and set authorization token
        self.update_token()

    def _make_request(
        self, endpoint_name: str, payload: Dict[str, Any]
    ) -> Optional[requests.Response]:
        """
        Make a request to a specific API endpoint.

        Args:
            endpoint_name: Name of the endpoint in settings
            payload: Request payload

        Returns:
            Response object if successful, None otherwise
        """
        endpoint = self.settings.endpoints.get(endpoint_name)
        if not endpoint:
            self.log.error(f"Endpoint '{endpoint_name}' not found.")
            return None

        try:
            json_payload = json.dumps(payload, separators=(",", ":"))

            if self.detailed:
                self.log.debug(f"\n{'='*80}")
                self.log.debug(f"API REQUEST: {endpoint_name}")
                self.log.debug(f"{'='*80}")
                self.log.debug(f"Method: {endpoint.method}")
                self.log.debug(f"URL: {endpoint.url}")
                self.log.debug(f"\nHeaders:")
                self.log.debug(json.dumps(dict(self.session.headers), indent=2))
                self.log.debug(f"\nPayload:")
                self.log.debug(json.dumps(payload, indent=2))
                self.log.debug(f"{'='*80}\n")

            response = self.session.request(
                method=endpoint.method, url=endpoint.url, data=json_payload, timeout=20
            )

            if self.detailed:
                self.log.debug(f"\n{'='*80}")
                self.log.debug(f"API RESPONSE: {endpoint_name}")
                self.log.debug(f"{'='*80}")
                self.log.debug(f"Status Code: {response.status_code}")
                self.log.debug(f"\nResponse Body:")
                try:
                    # Try to parse and pretty-print JSON response
                    response_json = response.json()
                    self.log.debug(json.dumps(response_json, indent=2))
                except (json.JSONDecodeError, ValueError):
                    # If not JSON, just print the raw text
                    self.log.debug(response.text)
                self.log.debug(f"{'='*80}\n")

            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            self.log.error(f"HTTP error for {endpoint.url}: {e}")
            if e.response.status_code == 401:
                self.log.critical(
                    "Authorization failed (401). Your token may have expired or credentials are wrong."
                )
            return None
        except requests.exceptions.RequestException as e:
            self.log.error(f"Request error for {endpoint.url}: {e}")
            return None

    def update_token(self) -> Optional[int]:
        """
        Request and set a new authorization bearer token.

        Returns:
            The driver ID if it was found in the response, None otherwise
        """
        self.log.info("Requesting new bearer token...")
        payload = {
            "drvrLastName": self.last_name,
            "licenceNumber": self.license_number,
            "keyword": self.keyword,
        }
        response = self._make_request("updateToken", payload)

        if not response:
            self.log.critical(
                "Failed to get a response from the token endpoint. Halting."
            )
            raise SystemExit("Could not obtain an authorization token.")

        auth_header = response.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            bearer_token = auth_header.removeprefix("Bearer ")
            self.log.info("✅ Successfully obtained and set new bearer token.")
            self.session.headers["Authorization"] = f"Bearer {bearer_token}"

            # Try to extract driver ID from response
            try:
                response_data = response.json()
                if "drvrId" in response_data:
                    driver_id = int(response_data["drvrId"])
                    self.log.info(f"✅ Found driver ID: {driver_id}")
                    # Update the instance driver_id and settings
                    self.driver_id = driver_id
                    if hasattr(self.settings, "driver_id"):
                        self.settings.driver_id = driver_id
                    return driver_id
            except (json.JSONDecodeError, ValueError) as e:
                self.log.warning(
                    f"Could not extract driver ID from response: {e}")

            return None
        else:
            self.log.critical(
                "❌ Did not find a bearer token in the response. Check your credentials."
            )
            raise SystemExit("Authorization failed.")

    def refresh_token(self) -> Optional[str]:
        """
        Request a new bearer token from the API.

        Returns:
            The new bearer token string, or None if the request fails.
        """
        try:
            # Update token and extract from session headers
            self.update_token()
            auth_header = self.session.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                return auth_header.removeprefix("Bearer ")
            return None
        except Exception as e:
            self.log.error(f"Error refreshing token: {e}")
            return None

    def fetch_locations(self) -> bool:
        """
        Fetch and cache test location information.

        Returns:
            True if successful, False otherwise
        """
        self.log.info("Fetching testing locations to build cache...")
        crit = self.settings.search_criteria
        payload = {
            "lng": crit.longitude,
            "lat": crit.latitude,
            "examType": crit.examType,
            "startDate": crit.examDate,
        }

        response = self._make_request("getNearestPos", payload)
        if not response:
            self.log.error("Failed to fetch location data. Aborting.")
            return False

        try:
            locations_data = response.json()
            if not isinstance(locations_data, list):
                self.log.error(
                    f"Expected a list of locations, but got: {type(locations_data)}"
                )
                return False
        except json.JSONDecodeError:
            self.log.error(
                "Failed to decode JSON from location data response.")
            return False

        for item in locations_data:
            try:
                pos_data = Location.parse_obj(item.get("pos"))
                self.location_cache[pos_data.posId] = pos_data
            except Exception as e:
                self.log.warning(f"Could not parse a location item: {e}")

        self.log.info(
            f"Location cache populated with {len(self.location_cache)} entries."
        )
        return True

    def fetch_all_locations(self) -> List[Location]:
        """
        Fetch all available locations for the specified exam type.

        Returns:
            List of Location objects representing all available locations
        """
        crit = self.settings.search_criteria
        payload = {"examType": crit.examType, "startDate": crit.examDate}

        response = self._make_request("listLocations", payload)
        if not response:
            self.log.error("Failed to fetch all locations. Aborting.")
            return []

        try:
            locations_data = response.json()
            location_list = [Location(**loc) for loc in locations_data]
            return location_list
        except json.JSONDecodeError:
            self.log.error(
                "Failed to decode JSON from all locations response.")
            return []

    def get_appointments(self, pos_id: int) -> Optional[List[AppointmentSlot]]:
        """
        Get available appointments for a specific location.

        Args:
            pos_id: Location ID to check

        Returns:
            List of available appointment slots, or None if request failed
        """
        crit = self.settings.search_criteria
        self.log.info(f"Checking for appointments at location ID {pos_id}...")

        payload = {
            "aPosID": pos_id,
            "examType": crit.examType,
            "examDate": crit.examDate,
            "prfDaysOfWeek": json.dumps(crit.prfDaysOfWeek, separators=(",", ":")),
            "prfPartsOfDay": json.dumps(crit.prfPartsOfDay, separators=(",", ":")),
            "lastName": self.last_name,
            "licenseNumber": self.license_number,
        }

        response = self._make_request("getAppointments", payload)
        if not response:
            return None

        try:
            slots_data = response.json()
            if isinstance(slots_data, list):
                result = []
                for slot_dict in slots_data:
                    try:
                        result.append(AppointmentSlot.parse_obj(slot_dict))
                    except Exception as e:
                        self.log.warning(
                            f"Could not parse an appointment slot: {e}")
                return result
            else:
                self.log.warning(
                    f"Expected a list of appointments, but got: {type(slots_data)}"
                )
                return []
        except json.JSONDecodeError:
            self.log.warning(
                "Could not decode JSON from getAppointments response.")
            return None

    def get_all_appointments(self) -> Optional[List[AppointmentSlot]]:
        """
        Check for appointments across all configured locations.

        Returns:
            Combined list of all available appointment slots
        """
        all_found_slots = []

        for pos_id in self.settings.search_criteria.aPosID:
            slots = self.get_appointments(pos_id)
            if slots:
                all_found_slots.extend(slots)

            # Add delay between requests to avoid rate limiting
            time.sleep(random.uniform(0.5, 1.5))

        return all_found_slots

    def lock_appointment(self, payload: ConfirmationPayload) -> Optional[Dict]:
        """
        Lock an appointment slot.

        Args:
            payload: Appointment confirmation payload

        Returns:
            Response data if successful, None otherwise
        """
        self.log.info("Attempting to lock appointment...")
        response = self._make_request("lockAppointment", payload.model_dump())
        return response.json() if response else None

    def send_otp(self, booked_ts: str) -> Optional[Dict]:
        """
        Request a one-time password for appointment confirmation.

        Args:
            booked_ts: Booking timestamp string

        Returns:
            Response data if successful, None otherwise
        """
        self.log.info("Requesting OTP for the booked appointment...")
        payload = OtpPayload(
            bookedTs=booked_ts, drvrID=self.driver_id, method="S"  # "S" for SMS
        )
        response = self._make_request("sendOTP", payload.model_dump())
        return response.json() if response else None

    def verify_otp(self, booked_ts: str, otp_code: str) -> Optional[Dict]:
        """
        Verify the one-time password.

        Args:
            booked_ts: Booking timestamp string
            otp_code: OTP code received from user

        Returns:
            Response data if successful, None otherwise
        """
        self.log.info("Verifying OTP code...")
        payload = VerifyOtpPayload(
            bookedTs=booked_ts, drvrID=self.driver_id, code=otp_code.strip()
        )
        response = self._make_request("verifyOTP", payload.model_dump())
        return response.json() if response else None

    def confirm_booking(self) -> Optional[Dict]:
        """
        Send final booking confirmation.

        Returns:
            Response data if successful, None otherwise
        """
        self.log.info("Sending final booking confirmation...")
        payload = BookPayload(
            userId=f"WEBD:{self.driver_id}",
            appointment=BookAppointment(
                drvrDriver=BookDrvrDriver(drvrId=self.driver_id)
            ),
        )
        response = self._make_request("book", payload.model_dump())
        return response.json() if response else None
