import time
import random
import json
import logging
import argparse
import os
import sys
from datetime import datetime
from app_config import load_settings, setup_logging, format_appointment_message
from app_config import ConfirmationPayload, ConfirmationDlExam, ConfirmationDrvrDriver
from api_handler import APIHandler

log = logging.getLogger()

def main():
    parser = argparse.ArgumentParser(
        description="Poll the ICBC website for available driving test appointments.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--detailed", action="store_true", help="Enable detailed logging.")
    parser.add_argument("--dry-run", action="store_true", help="Run the script without attempting to book an appointment.")
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.detailed else logging.INFO)

    try:
        settings = load_settings("config.json")
        if not settings:
            sys.exit(1)

        handler = APIHandler(settings, detailed=args.detailed)

        if not handler.fetch_and_cache_locations():
            log.error("Could not fetch initial location data. Exiting.")
            sys.exit(1)

        log.info("--- Starting Appointment Polling Script ---")
        if args.dry_run:
            log.warning("DRY RUN MODE IS ENABLED. No appointment will be booked.")
        log.info(f"Polling for locations: {settings.search_criteria.aPosID}")
        log.info("Press Ctrl+C to stop the script.")

        request_count = 0
        max_requests = 60
        timeout_duration = 120  
        
        while True:
            if request_count >= max_requests:
                log.warning(f"Rate limit reached ({max_requests} requests). "
                           f"Waiting {timeout_duration} seconds...")
                time.sleep(timeout_duration)
                request_count = 0
                log.info("Rate limit timeout completed. Resuming requests.")
            
            # Increment request counter
            request_count += 1
            
            available_slots = handler.get_all_appointments()
            if available_slots is None:
                log.error("Failed to retrieve appointments in this poll. Will try again.")
            elif available_slots:
                slot_to_book = available_slots[0]
                log.warning(format_appointment_message(slot_to_book, handler.location_cache))
                
                if args.dry_run:
                    log.warning("Dry Run: Appointment found, but booking is skipped.")
                    log.info("Script will now exit as its task is complete in dry run mode.")
                    break
                    
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
                    log.warning(f"Appointment locked successfully! Response:\n{json.dumps(response, indent=2)}")
                    
                    otp_response = handler.send_otp(payload.bookedTs)
                    if otp_response:
                        log.info(f"OTP request successful! Response:\n{json.dumps(otp_response, indent=2)}")
                        
                        # UPDATED: Add interactive OTP prompt and final booking steps
                        otp_code = input("📲 Please enter the OTP you received and press Enter: ")
                        if not otp_code or not otp_code.strip().isdigit():
                            log.critical("Invalid or empty OTP entered. Halting.")
                            break

                        verify_response = handler.verify_otp(payload.bookedTs, otp_code)
                        if verify_response:
                            log.info(f"OTP verification successful!")
                            
                            book_response = handler.confirm_booking()
                            if book_response:
                                log.warning(f"✅ APPOINTMENT CONFIRMED! Final Response:\n{json.dumps(book_response, indent=2)}")
                            else:
                                log.error("Final booking confirmation failed.")
                        else:
                            log.error("OTP verification failed.")
                    else:
                        log.error("OTP request failed.")
                else:
                    log.error("Booking lock request failed.")
                
                log.info("Script has completed its task and will now exit.")
                break

            else:
                log.info("No new appointments found in this poll.")

            jitter = random.uniform(-settings.polling.randomJitterSeconds, settings.polling.randomJitterSeconds)
            sleep_duration = settings.polling.baseIntervalSeconds + jitter
            log.info(f"Waiting for {sleep_duration:.2f} seconds...")
            time.sleep(max(0, sleep_duration))

    except KeyboardInterrupt:
        log.info("\nScript stopped by user. Goodbye! 👋")
    except SystemExit as e:
        log.critical(f"A critical error occurred, and the script had to exit: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}", exc_info=args.detailed)

if __name__ == "__main__":
    main()
