import json
import logging
from datetime import datetime

from api_handler import ICBCApiClient
from app_config import format_appointment_message
from models import (
    AppointmentSlot,
    ConfirmationDlExam,
    ConfirmationDrvrDriver,
    ConfirmationPayload,
)


class BookingService:
    """Service to handle the appointment booking workflow."""

    def __init__(self, api_client: ICBCApiClient, settings):
        self.log = logging.getLogger(__name__)
        self.api_client = api_client
        self.settings = settings

    def book_appointment(self, slot: AppointmentSlot, dry_run: bool = False) -> bool:
        """
        Book an appointment by executing the full booking workflow.

        Args:
            slot: AppointmentSlot to book
            dry_run: If True, only simulate booking without actual confirmation

        Returns:
            True if booking was successful, False otherwise
        """
        self.log.warning(
            format_appointment_message(slot, self.api_client.location_cache)
        )

        if dry_run:
            self.log.warning(
                "Dry Run: Appointment found, but booking is skipped.")
            return True

        # Create booking payload
        crit = self.settings.search_criteria
        payload = ConfirmationPayload(
            appointmentDt=slot.appointmentDt,
            dlExam=ConfirmationDlExam(
                code=crit.examType, description=f"{crit.examType}-ROAD"
            ),
            drvrDriver=ConfirmationDrvrDriver(drvrId=self.settings.driver_id),
            drscDrvSchl={},
            instructorDlNum=None,
            bookedTs=datetime.now().isoformat(timespec="seconds"),
            startTm=slot.startTm,
            endTm=slot.endTm,
            posId=slot.posId,
            resourceId=slot.resourceId,
            signature=slot.signature,
        )

        # Step 1: Lock the appointment
        response = self.api_client.lock_appointment(payload)
        if not response:
            self.log.error("Failed to lock appointment.")
            return False

        self.log.warning(
            f"Appointment locked successfully! Response:\n{json.dumps(response, indent=2)}"
        )

        # Step 2: Request OTP
        otp_response = self.api_client.send_otp(payload.bookedTs)
        if not otp_response:
            self.log.error("Failed to request OTP.")
            return False

        self.log.info(
            f"OTP request successful! Response:\n{json.dumps(otp_response, indent=2)}"
        )

        # Step 3: Get OTP from user
        otp_code = input(
            "📲 Please enter the OTP you received and press Enter: ")
        if not otp_code or not otp_code.strip().isdigit():
            self.log.critical("Invalid or empty OTP entered. Halting.")
            return False

        # Step 4: Verify OTP
        verify_response = self.api_client.verify_otp(
            payload.bookedTs, otp_code)
        if not verify_response:
            self.log.error("OTP verification failed.")
            return False

        self.log.info("OTP verification successful!")

        # Step 5: Confirm booking
        book_response = self.api_client.confirm_booking()
        if not book_response:
            self.log.error("Final booking confirmation failed.")
            return False

        self.log.warning(
            f"✅ APPOINTMENT CONFIRMED! Final Response:\n{json.dumps(book_response, indent=2)}"
        )
        return True
