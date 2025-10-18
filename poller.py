import logging
import random
import time
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from typing import List

from api_handler import ICBCApiClient
from booking import BookingService


class AppointmentPoller:
    """
    Service that polls the ICBC API for available appointments.
    Supports multiple polling threads for faster response.
    """

    def __init__(self, settings, max_days_ahead=30, dry_run=False, detailed=False):
        self.log = logging.getLogger(__name__)
        self.settings = settings
        self.max_days_ahead = max_days_ahead
        self.dry_run = dry_run
        self.detailed = detailed

        # Threading controls
        self.booking_lock = Lock()
        self.appointment_found = Event()
        self.threads: List[Thread] = []

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

    def polling_worker(self, thread_id: int) -> None:
        """
        Worker function for each polling thread.

        Args:
            thread_id: Unique identifier for the thread
        """
        thread_log = logging.getLogger(f"Thread-{thread_id}")

        try:
            # Initialize API client for this thread
            handler = ICBCApiClient(self.settings, detailed=self.detailed)

            # Initialize location cache
            if not handler.fetch_locations():
                thread_log.error(
                    "Could not fetch initial location data. Thread exiting."
                )
                return

            thread_log.info(f"🚀 Thread {thread_id} started polling")

            # Request counters for rate limiting
            request_count = 0
            total_request_count = 0
            max_requests = 60  # Max requests before cooling down
            timeout_duration = 120  # Cooldown period in seconds
            token_refresh_threshold = 300  # Refresh token after this many requests

            while not self.appointment_found.is_set():
                # Check if we need to refresh the bearer token
                if total_request_count >= token_refresh_threshold:
                    with self.booking_lock:
                        thread_log.warning(
                            f"Reached {token_refresh_threshold} requests. Refreshing bearer token..."
                        )

                        # Request a new bearer token
                        new_token = handler.refresh_token()
                        if not new_token:
                            thread_log.error(
                                "Failed to refresh bearer token. Thread exiting."
                            )
                            return

                        thread_log.info(
                            "✅ Bearer token refreshed successfully. Resetting counters."
                        )
                        total_request_count = 0
                        request_count = 0

                # Rate limiting check
                if request_count >= max_requests:
                    thread_log.warning(
                        f"Rate limit reached ({max_requests} requests). "
                        f"Waiting {timeout_duration} seconds..."
                    )
                    time.sleep(timeout_duration)
                    request_count = 0
                    thread_log.info(
                        "Rate limit timeout completed. Resuming requests.")

                # Increment request counter
                request_count += 1
                total_request_count += 1

                thread_log.debug(
                    f"Request count: {total_request_count} (rate limit cycle: {request_count}/{max_requests})"
                )

                # Poll for appointments
                available_slots = handler.get_all_appointments()
                if available_slots is None:
                    thread_log.error(
                        "Failed to retrieve appointments in this poll. Will try again."
                    )
                elif available_slots:
                    # Filter appointments based on date range
                    filtered_slots = [
                        slot
                        for slot in available_slots
                        if self.is_appointment_within_date_range(
                            slot.appointmentDt.date
                        )
                    ]

                    if not filtered_slots:
                        thread_log.info(
                            f"Found {len(available_slots)} appointment(s), but all are beyond {self.max_days_ahead} days. Skipping."
                        )
                    else:
                        # Use lock to ensure only one thread books
                        with self.booking_lock:
                            if self.appointment_found.is_set():
                                thread_log.info(
                                    "Another thread already found an appointment. Stopping."
                                )
                                return

                            # Mark that we've found an appointment to stop other threads
                            self.appointment_found.set()

                            # Book the first available slot
                            slot_to_book = filtered_slots[0]

                            # Use booking service to handle the booking workflow
                            booking_service = BookingService(
                                handler, self.settings)
                            success = booking_service.book_appointment(
                                slot_to_book, self.dry_run
                            )

                            if success:
                                thread_log.info(
                                    "Booking process completed successfully."
                                )
                            else:
                                thread_log.error("Booking process failed.")

                            thread_log.info(
                                "Thread has completed its task and will now exit."
                            )
                            return
                else:
                    thread_log.debug("No new appointments found in this poll.")

                # Wait before next poll with random jitter
                jitter = random.uniform(
                    -self.settings.polling.randomJitterSeconds,
                    self.settings.polling.randomJitterSeconds,
                )
                sleep_duration = self.settings.polling.baseIntervalSeconds + jitter
                thread_log.debug(
                    f"Waiting for {sleep_duration:.2f} seconds...")
                time.sleep(max(0, sleep_duration))

        except Exception as e:
            thread_log.error(
                f"An unexpected error occurred in thread: {e}", exc_info=self.detailed
            )

    def start(self, num_threads: int = 1) -> None:
        """
        Start the polling process with multiple threads.

        Args:
            num_threads: Number of concurrent polling threads to create
        """
        self.log.info("--- Starting Appointment Polling ---")
        if self.dry_run:
            self.log.warning(
                "DRY RUN MODE IS ENABLED. No appointment will be booked.")
        self.log.info(
            f"Polling for locations: {self.settings.search_criteria.aPosID}")
        self.log.info(f"Maximum days ahead: {self.max_days_ahead}")
        self.log.info(f"Number of polling threads: {num_threads}")
        self.log.info("Press Ctrl+C to stop the script.")

        # Create and start polling threads
        for i in range(num_threads):
            thread = Thread(target=self.polling_worker,
                            args=(i + 1,), daemon=True)
            thread.start()
            self.threads.append(thread)
            # Small delay between thread starts to avoid simultaneous initialization
            time.sleep(0.5)

    def wait_for_completion(self) -> None:
        """Wait for all polling threads to complete."""
        try:
            # Wait for all threads to complete
            for thread in self.threads:
                thread.join()

            self.log.info("All threads have completed. Polling finished.")
        except KeyboardInterrupt:
            self.log.warning(
                "Keyboard interrupt received. Stopping all threads...")
