import requests
import time
import random
import json
import logging
import os
from typing import List, Dict, Any, Optional
from app_config import Settings, AppointmentSlot, ConfirmationPayload, Pos

log = logging.getLogger()

class APIHandler:
    def __init__(self, settings: Settings, detailed: bool = False):
        self.settings = settings
        self.session = requests.Session()
        self.last_name = os.getenv("LAST_NAME")
        self.license_number = os.getenv("LICENSE_NUMBER") # Reads from .env
        self.keyword = os.getenv("KEYWORD")
        self.detailed = detailed
        self.location_cache: Dict[int, Pos] = {}

        self.session.headers.update(settings.sharedHeaders)
        self.update_token()

    def _make_request(self, endpoint_name: str, payload: Dict[str, Any]) -> Optional[requests.Response]:
        endpoint = self.settings.endpoints.get(endpoint_name)
        if not endpoint:
            log.error(f"Endpoint '{endpoint_name}' not found.")
            return None
        try:
            json_payload = json.dumps(payload, separators=(',', ':'))

            if self.detailed:
                log.debug(f"--- REQUEST [{endpoint.method}] -> {endpoint.url} ---")
                log.debug(f"Headers: {self.session.headers}")
                log.debug(f"Payload: {json_payload}")

            response = self.session.request(
                method=endpoint.method,
                url=endpoint.url,
                data=json_payload,
                timeout=20
            )

            if self.detailed:
                log.debug(f"--- RESPONSE [{response.status_code}] <---")
                log.debug(f"Body: {response.text}")

            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            log.error(f"HTTP error for {endpoint.url}: {e}")
            if e.response.status_code == 401:
                log.critical("Authorization failed (401). Your token may have expired or credentials are wrong.")
            return None
        except requests.exceptions.RequestException as e:
            log.error(f"Request error for {endpoint.url}: {e}")
            return None

    def update_token(self) -> None:
        log.info("Requesting new bearer token...")
        # UPDATED: Using 'licenceNumber' for the token endpoint
        payload = {"drvrLastName": self.last_name, "licenceNumber": self.license_number, "keyword": self.keyword}
        response = self._make_request("updateToken", payload)
        if not response:
            log.critical("Failed to get a response from the token endpoint. Halting.")
            raise SystemExit("Could not obtain an authorization token.")
        auth_header = response.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            bearer_token = auth_header.removeprefix('Bearer ')
            log.info("✅ Successfully obtained and set new bearer token.")
            self.session.headers['Authorization'] = f"Bearer {bearer_token}"
        else:
            log.critical("❌ Did not find a bearer token in the response. Check your credentials.")
            raise SystemExit("Authorization failed.")

    def fetch_and_cache_locations(self) -> bool:
        log.info("Fetching nearby testing locations to build cache...")
        crit = self.settings.search_criteria
        payload = {"lng": crit.longitude, "lat": crit.latitude, "examType": crit.examType, "startDate": crit.examDate}
        response = self._make_request("getNearestPos", payload)
        if not response:
            log.error("Failed to fetch location data. Aborting.")
            return False
        try:
            locations_data = response.json()
            if not isinstance(locations_data, list):
                log.error(f"Expected a list of locations, but got: {type(locations_data)}")
                return False
        except json.JSONDecodeError:
            log.error("Failed to decode JSON from location data response.")
            return False
        for item in locations_data:
            try:
                pos_data = Pos.parse_obj(item.get('pos'))
                self.location_cache[pos_data.posId] = pos_data
            except Exception as e:
                log.warning(f"Could not parse a location item: {e}")
        log.info(f"Location cache populated with {len(self.location_cache)} entries.")
        return True

    def get_all_appointments(self) -> Optional[List[AppointmentSlot]]:
        crit = self.settings.search_criteria
        all_found_slots = []
        for pos_id in crit.aPosID:
            log.info(f"Checking for appointments at location ID {pos_id}...")
            payload = {
                "aPosID": pos_id,
                "examType": crit.examType,
                "examDate": crit.examDate,
                "prfDaysOfWeek": json.dumps(crit.prfDaysOfWeek, separators=(',', ':')),
                "prfPartsOfDay": json.dumps(crit.prfPartsOfDay, separators=(',', ':')),
                "lastName": self.last_name,
                # UPDATED: Using 'licenseNumber' for the appointments endpoint
                "licenseNumber": self.license_number
            }
            response = self._make_request("getAppointments", payload)
            if response:
                try:
                    slots_data = response.json()
                    if isinstance(slots_data, list):
                        for slot_dict in slots_data:
                            try:
                                all_found_slots.append(AppointmentSlot.parse_obj(slot_dict))
                            except Exception as e:
                                log.warning(f"Could not parse an appointment slot: {e}")
                except json.JSONDecodeError:
                    log.warning("Could not decode JSON from getAppointments response.")
            time.sleep(random.uniform(0.5, 1.5))
        return all_found_slots

    def lock_appointment(self, payload: ConfirmationPayload) -> Optional[Dict]:
        log.info("Attempting to lock appointment...")
        response = self._make_request("lockAppointment", payload.model_dump())
        return response.json() if response else None
