import logging
import random
import time
from datetime import datetime, timedelta

from api_handler import ICBCApiClient
from booking import BookingService


class AppointmentPoller:
    """Service that polls the ICBC API for available appointments."""

    def __init__(self, settings, max_days_ahead=30, dry_run=False, detailed=False):
        self.log = logging.getLogger(__name__)
        self.settings = settings
        self.max_days_ahead = max_days_ahead
        self.dry_run = dry_run
        self.detailed = detailed

    def is_appointment_within_date_range(self, appointment_dt_str) -> bool:
        """
        Check if the appointment date is within the specified number of days from today.

        Args:
            appointment_dt_str: ISO format datetime string from appointmentDt

        Returns:
            True if appointment is within range, False otherwise
        """
        try:
            # Handle both string and dict types for appointmentDt
            if isinstance(appointment_dt_str, dict):
                appointment_dt_str = appointment_dt_str.get("date", "")

            appointment_date = datetime.fromisoformat(
                appointment_dt_str.replace("Z", "+00:00")
            ).date()
            max_date = (datetime.now() +
                        timedelta(days=self.max_days_ahead)).date()

            if appointment_date > max_date:
                self.log.debug(
                    f"Appointment on {appointment_date} is beyond max date {max_date}"
                )
                return False
            return True
        except Exception as e:
            self.log.error(f"Error parsing appointment date: {e}")
            return False

    def poll(self) -> None:
        """Main polling loop to check for available appointments."""
        # Initialize API client
        handler = ICBCApiClient(self.settings, detailed=self.detailed)

        # Initialize location cache
        if not handler.fetch_locations():
            self.log.error("Could not fetch initial location data. Exiting.")
            return

        self.log.info("🚀 Started polling for appointments")

        # Request counters for rate limiting
        request_count = 0
        total_request_count = 0
        max_requests = 60  # Max requests before cooling down
        timeout_duration = 120  # Cooldown period in seconds
        token_refresh_threshold = 300  # Refresh token after this many requests

        try:
            while True:
                # Check if we need to refresh the bearer token
                if total_request_count >= token_refresh_threshold:
                    self.log.warning(
                        f"Reached {token_refresh_threshold} requests. Refreshing bearer token..."
                    )
                    new_token = handler.refresh_token()
                    if not new_token:
                        self.log.error("Failed to refresh bearer token. Exiting.")
                        return

                    self.log.info("✅ Bearer token refreshed successfully. Resetting counters.")
                    total_request_count = 0
                    request_count = 0

                # Rate limiting check
                if request_count >= max_requests:
                    self.log.warning(
                        f"Rate limit reached ({max_requests} requests). "
                        f"Waiting {timeout_duration} seconds..."
                    )
                    time.sleep(timeout_duration)
                    request_count = 0
                    self.log.info("Rate limit timeout completed. Resuming requests.")

                # Increment request counter
                request_count += 1
                total_request_count += 1

                self.log.debug(
                    f"Request count: {total_request_count} (rate limit cycle: {request_count}/{max_requests})"
                )

                # Poll for appointments
                available_slots = handler.get_all_appointments()
                if available_slots is None:
                    self.log.error("Failed to retrieve appointments in this poll. Will try again.")
                elif available_slots:
                    # Filter appointments based on date range
                    filtered_slots = [
                        slot
                        for slot in available_slots
                        if self.is_appointment_within_date_range(slot.appointmentDt.date)
                    ]

                    if not filtered_slots:
                        self.log.info(
                            f"Found {len(available_slots)} appointment(s), but all are beyond {self.max_days_ahead} days. Skipping."
                        )
                    else:
                        # Book the first available slot
                        slot_to_book = filtered_slots[0]

                        # Use booking service to handle the booking workflow
                        booking_service = BookingService(handler, self.settings)
                        success = booking_service.book_appointment(slot_to_book, self.dry_run)

                        if success:
                            self.log.info("Booking process completed successfully.")
                        else:
                            self.log.error("Booking process failed.")

                        self.log.info("Polling completed.")
                        return
                else:
                    self.log.debug("No new appointments found in this poll.")

                # Wait before next poll with random jitter
                jitter = random.uniform(
                    -self.settings.polling.randomJitterSeconds,
                    self.settings.polling.randomJitterSeconds,
                )
                sleep_duration = self.settings.polling.baseIntervalSeconds + jitter
                self.log.debug(f"Waiting for {sleep_duration:.2f} seconds...")
                time.sleep(max(0, sleep_duration))

        except KeyboardInterrupt:
            self.log.warning("Polling stopped by user.")
        except Exception as e:
            self.log.error(f"An unexpected error occurred: {e}", exc_info=self.detailed)

    def start(self) -> None:
        """Start the polling process."""
        self.log.info("--- Starting Appointment Polling ---")
        if self.dry_run:
            self.log.warning("DRY RUN MODE IS ENABLED. No appointment will be booked.")
        self.log.info(f"Polling for locations: {self.settings.search_criteria.aPosID}")
        self.log.info(f"Maximum days ahead: {self.max_days_ahead}")
        self.log.info("Press Ctrl+C to stop the script.")

        # Start polling
        self.poll()
