from typing import Dict, List, Optional

from pydantic import BaseModel


# Authentication models
class TokenPayload(BaseModel):
    drvrLastName: str
    licenceNumber: str
    keyword: str


# Location models
class Location(BaseModel):
    address: str
    address1: str
    agency: str
    city: str
    lat: float
    lng: float
    posId: int
    postcode: str
    province: str
    url: str


# Appointment models
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


# Booking models
class ConfirmationDlExam(BaseModel):
    code: str
    description: str


class ConfirmationDrvrDriver(BaseModel):
    drvrId: int


class ConfirmationPayload(BaseModel):
    appointmentDt: AppointmentDateTime
    dlExam: ConfirmationDlExam
    drvrDriver: ConfirmationDrvrDriver
    drscDrvSchl: dict
    instructorDlNum: Optional[str] = None
    bookedTs: str
    startTm: str
    endTm: str
    posId: int
    resourceId: int
    signature: str


class OtpPayload(BaseModel):
    bookedTs: str
    drvrID: int
    method: str


class VerifyOtpPayload(BaseModel):
    bookedTs: str
    drvrID: int
    code: str


class BookDrvrDriver(BaseModel):
    drvrId: int


class BookAppointment(BaseModel):
    drvrDriver: BookDrvrDriver


class BookPayload(BaseModel):
    userId: str
    appointment: BookAppointment
