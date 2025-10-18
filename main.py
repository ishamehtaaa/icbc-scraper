import time
import random
import json
import logging
import argparse
import os
import sys
from datetime import datetime, timedelta
from threading import Thread, Lock, Event
from app_config import load_settings, setup_logging, format_appointment_message
from app_config import ConfirmationPayload, ConfirmationDlExam, ConfirmationDrvrDriver
from api_handler import APIHandler

log = logging.getLogger()

# Global lock for thread-safe operations
booking_lock = Lock()
appointment_found = Event()

def setup_logging(level=logging.INFO):
    """Setup logging with thread names in the format."""
    log = logging.getLogger()
    if log.handlers:
        return
    
    try:
        import colorlog
        handler = colorlog.StreamHandler()
        handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
            log_colors={
                'DEBUG': 'cyan', 'INFO': 'white', 'WARNING': 'green',
                'ERROR': 'red', 'CRITICAL': 'bold_red',
            }))
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s'
        ))
    
    log.addHandler(handler)
    log.setLevel(level)

def is_appointment_within_date_range(appointment_dt_str, max_days_ahead):
    """
    Check if the appointment date is within the specified number of days from today.
    
    Args:
        appointment_dt_str: ISO format datetime string from appointmentDt
        max_days_ahead: Maximum number of days in the future to consider
        
    Returns:
        True if appointment is within range, False otherwise
    """
    try:
        # Handle both string and dict types for appointmentDt
        if isinstance(appointment_dt_str, dict):
            appointment_dt_str = appointment_dt_str.get('date', '')
        
        appointment_date = datetime.fromisoformat(appointment_dt_str.replace('Z', '+00:00')).date()
        max_date = (datetime.now() + timedelta(days=max_days_ahead)).date()
        
        if appointment_date > max_date:
            log.debug(f"Appointment on {appointment_date} is beyond max date {max_date}")
            return False
        return True
    except Exception as e:
        log.error(f"Error parsing appointment date: {e}")
        return False

def polling_worker(thread_id, settings, args, max_days_ahead):
    """
    Worker function for each polling thread.
    """
    thread_log = logging.getLogger(f"Thread-{thread_id}")
    
    try:
        handler = APIHandler(settings, detailed=args.detailed)
        
        if not handler.fetch_and_cache_locations():
            thread_log.error("Could not fetch initial location data. Thread exiting.")
            return
        
        thread_log.info(f"🚀 Thread {thread_id} started polling")
        
        request_count = 0
        total_request_count = 0
        max_requests = 60
        timeout_duration = 120
        token_refresh_threshold = 300
        
        while not appointment_found.is_set():
            # Check if we need to refresh the bearer token
            if total_request_count >= token_refresh_threshold:
                with booking_lock:
                    thread_log.warning(f"Reached {token_refresh_threshold} requests. Refreshing bearer token...")
                    
                    # Request a new bearer token via API
                    new_token = handler.refresh_token()
                    if not new_token:
                        thread_log.error("Failed to refresh bearer token. Thread exiting.")
                        return
                    
                    # Update the settings with the new token
                    settings.sharedHeaders['Authorization'] = f'Bearer {new_token}'
                    
                    # Re-initialize the API handler with updated settings
                    handler = APIHandler(settings, detailed=args.detailed)
                    
                    if not handler.fetch_and_cache_locations():
                        thread_log.error("Could not fetch location data after token refresh. Thread exiting.")
                        return
                    
                    thread_log.info("✅ Bearer token refreshed successfully. Resetting counters.")
                    total_request_count = 0
                    request_count = 0
            
            if request_count >= max_requests:
                thread_log.warning(f"Rate limit reached ({max_requests} requests). "
                           f"Waiting {timeout_duration} seconds...")
                time.sleep(timeout_duration)
                request_count = 0
                thread_log.info("Rate limit timeout completed. Resuming requests.")

            # Increment request counter
            request_count += 1
            total_request_count += 1
            
            thread_log.debug(f"Request count: {total_request_count} (rate limit cycle: {request_count}/{max_requests})")

            available_slots = handler.get_all_appointments()
            if available_slots is None:
                thread_log.error("Failed to retrieve appointments in this poll. Will try again.")
            elif available_slots:
                # Filter appointments based on date range
                filtered_slots = [
                    slot for slot in available_slots 
                    if is_appointment_within_date_range(slot.appointmentDt.date, max_days_ahead)
                ]
                
                if not filtered_slots:
                    thread_log.info(f"Found {len(available_slots)} appointment(s), but all are beyond {max_days_ahead} days. Skipping.")
                else:
                    # Use lock to ensure only one thread books
                    with booking_lock:
                        if appointment_found.is_set():
                            thread_log.info("Another thread already found an appointment. Stopping.")
                            return
                        
                        appointment_found.set()
                        slot_to_book = filtered_slots[0]
                        thread_log.warning(format_appointment_message(slot_to_book, handler.location_cache))

                        if args.dry_run:
                            thread_log.warning("Dry Run: Appointment found, but booking is skipped.")
                            thread_log.info("Thread will now exit as its task is complete in dry run mode.")
                            return

                        crit = settings.search_criteria
                        payload = ConfirmationPayload(
                            appointmentDt=slot_to_book.appointmentDt,
                            dlExam=ConfirmationDlExam(code=crit.examType, description=f"{crit.examType}-ROAD"),
                            drvrDriver=ConfirmationDrvrDriver(drvrId=settings.driver_id),
                            drscDrvSchl={},
                            instructorDlNum=None,
                            bookedTs=datetime.now().isoformat(timespec='seconds'),
                            startTm=slot_to_book.startTm,
                            endTm=slot_to_book.endTm,
                            posId=slot_to_book.posId,
                            resourceId=slot_to_book.resourceId,
                            signature=slot_to_book.signature
                        )
                        response = handler.lock_appointment(payload)
                        if response:
                            thread_log.warning(f"Appointment locked successfully! Response:\n{json.dumps(response, indent=2)}")

                            otp_response = handler.send_otp(payload.bookedTs)
                            if otp_response:
                                thread_log.info(f"OTP request successful! Response:\n{json.dumps(otp_response, indent=2)}")

                                # UPDATED: Add interactive OTP prompt and final booking steps
                                otp_code = input("📲 Please enter the OTP you received and press Enter: ")
                                if not otp_code or not otp_code.strip().isdigit():
                                    thread_log.critical("Invalid or empty OTP entered. Halting.")
                                    return

                                verify_response = handler.verify_otp(payload.bookedTs, otp_code)
                                if verify_response:
                                    thread_log.info(f"OTP verification successful!")

                                    book_response = handler.confirm_booking()
                                    if book_response:
                                        thread_log.warning(f"✅ APPOINTMENT CONFIRMED! Final Response:\n{json.dumps(book_response, indent=2)}")
                                    else:
                                        thread_log.error("Final booking confirmation failed.")
                                else:
                                    thread_log.error("OTP verification failed.")
                            else:
                                thread_log.error("OTP request failed.")
                        else:
                            thread_log.error("Booking lock request failed.")

                        thread_log.info("Thread has completed its task and will now exit.")
                        return

            else:
                thread_log.debug("No new appointments found in this poll.")

            jitter = random.uniform(-settings.polling.randomJitterSeconds, settings.polling.randomJitterSeconds)
            sleep_duration = settings.polling.baseIntervalSeconds + jitter
            thread_log.debug(f"Waiting for {sleep_duration:.2f} seconds...")
            time.sleep(max(0, sleep_duration))

    except Exception as e:
        thread_log.error(f"An unexpected error occurred in thread: {e}", exc_info=args.detailed)

def main():
    parser = argparse.ArgumentParser(
        description="Poll the ICBC website for available driving test appointments.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--detailed", action="store_true", help="Enable detailed logging.")
    parser.add_argument("--dry-run", action="store_true", help="Run the script without attempting to book an appointment.")
    parser.add_argument("--max-days", type=int, default=30, 
                       help="Maximum number of days ahead to search for appointments (default: 30)")
    parser.add_argument("--threads", type=int, default=1, 
                       help="Number of concurrent polling threads to run (default: 1, max recommended: 5)")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.detailed else logging.INFO)

    try:
        settings = load_settings("config.json")
        if not settings:
            sys.exit(1)

        # Validate thread count
        num_threads = max(1, min(args.threads, 10))  # Limit between 1 and 10
        if num_threads != args.threads:
            log.warning(f"Thread count adjusted to {num_threads} (must be between 1 and 10)")

        log.info("--- Starting Appointment Polling Script ---")
        if args.dry_run:
            log.warning("DRY RUN MODE IS ENABLED. No appointment will be booked.")
        log.info(f"Polling for locations: {settings.search_criteria.aPosID}")
        log.info(f"Maximum days ahead: {args.max_days}")
        log.info(f"Number of polling threads: {num_threads}")
        log.info("Press Ctrl+C to stop the script.")

        # Create and start polling threads
        threads = []
        for i in range(num_threads):
            thread = Thread(
                target=polling_worker,
                args=(i + 1, settings, args, args.max_days),
                daemon=True
            )
            thread.start()
            threads.append(thread)
            # Small delay between thread starts to avoid simultaneous initialization
            time.sleep(0.5)

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        log.info("All threads have completed. Script exiting.")

    except KeyboardInterrupt:
        log.info("\nScript stopped by user. Goodbye! 👋")
    except SystemExit as e:
        log.critical(f"A critical error occurred, and the script had to exit: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}", exc_info=args.detailed)

if __name__ == "__main__":
    main()


