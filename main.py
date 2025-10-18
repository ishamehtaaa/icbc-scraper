#!/usr/bin/env python3
"""
ICBC Appointment Finder

A script to poll the ICBC website for available driving test appointments
and automatically book an appointment when one is found.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

from api_handler import ICBCApiClient
from app_config import load_settings, setup_logging
from poller import AppointmentPoller


def setup_argument_parser():
    """Configure and return command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Poll the ICBC website for available driving test appointments.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Enable detailed logging including API requests/responses.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the script without attempting to book an appointment.",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=30,
        help="Maximum number of days ahead to search for appointments (default: 30)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Path to configuration file (default: config.json)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactive setup to generate .env and update config file",
    )
    parser.add_argument(
        "--list-locations",
        action="store_true",
        help="List all available test locations and exit",
    )

    return parser


def interactive_setup(config_path):
    """Run interactive setup to generate .env file and update config."""
    log = logging.getLogger(__name__)

    log.info("=== Interactive Setup ===")
    log.info("This will help you configure your ICBC appointment finder.")

    # Check if .env already exists
    if os.path.exists(".env"):
        overwrite = input(
            "An .env file already exists. Overwrite it? (y/n): ").lower()
        if overwrite != "y":
            log.info("Setup cancelled. Using existing .env file.")
            return

    # Get user credentials
    log.info("\n--- Personal Information ---")
    last_name = input("Enter your last name: ")
    license_number = input("Enter your license number (e.g., 1234567): ")
    keyword = input(
        "Enter your keyword (security word you set on your ICBC account): ")

    # Write .env file
    with open(".env", "w") as f:
        f.write(f'LAST_NAME="{last_name}"\n')
        f.write(f'LICENSE_NUMBER="{license_number}"\n')
        f.write(f'KEYWORD="{keyword}"\n')

    log.info("✅ .env file created successfully!")

    # Try to load settings
    settings = load_settings(config_path)
    if not settings:
        log.error("Failed to load settings. Please check your configuration file.")
        return

    # Update config if needed
    log.info("\n--- Exam Configuration ---")
    log.info("Now let's configure your exam search preferences.")

    # Initialize API client to get available locations and driver ID
    try:
        api_client = ICBCApiClient(settings)
        # Driver ID should now be automatically obtained during token authentication
        if api_client.driver_id:
            log.info(f"✅ Detected your driver ID: {api_client.driver_id}")

        # Get available exam types
        exam_types = {
            "7-R-1": "Class 7 Road Test (L - N)",
            "5-R-1": "Class 5 Road Test (N - Full)",
        }

        log.info("\nAvailable exam types:")
        for code, description in exam_types.items():
            log.info(f"  {code}: {description}")

        exam_type = (
            input(
                f"\nSelect exam type [{settings.search_criteria.examType}]: ")
            or settings.search_criteria.examType
        )
        if exam_type not in exam_types:
            log.warning(f"Warning: {exam_type} is not a recognized exam type.")

        settings.search_criteria.examType = exam_type

        log.info("\nFetching available test locations for this exam type...")
        locations = api_client.fetch_all_locations()

        if not locations:
            log.warning(
                "Could not fetch locations. Will keep current settings.")
        else:
            log.info("\nAvailable test locations:")
            for i, loc in enumerate(locations, 1):
                log.info(f"  {i}. {loc.agency} ({loc.city}) - ID: {loc.posId}")

            location_input = input(
                "\nEnter location numbers separated by commas (or 'all'): "
            )
            if location_input.lower() == "all":
                location_ids = [loc.posId for loc in locations]
            else:
                try:
                    # Parse 1-based indices to location IDs
                    indices = [
                        int(idx.strip())
                        for idx in location_input.split(",")
                        if idx.strip()
                    ]
                    location_ids = [
                        locations[i - 1].posId
                        for i in indices
                        if 0 < i <= len(locations)
                    ]

                    if not location_ids:
                        log.warning(
                            "No valid locations selected. Keeping current settings."
                        )
                        location_ids = settings.search_criteria.aPosID
                except (ValueError, IndexError):
                    log.warning(
                        "Invalid location selection. Keeping current settings.")
                    location_ids = settings.search_criteria.aPosID

            # Update settings
            settings.search_criteria.aPosID = location_ids

            # Get date range
            try:
                days_input = input(f"\nHow many days ahead to search? [30]: ")
                max_days = int(days_input) if days_input.strip() else 30

                # Update start date to today
                today = datetime.now().strftime("%Y-%m-%d")
                settings.search_criteria.examDate = today

                log.info(f"✅ Start date set to {today}")
                log.info(f"✅ Will search up to {max_days} days ahead")
            except ValueError:
                log.warning("Invalid number of days. Using default (30).")

            # Preferred days of week
            log.info("\nPreferred days of week:")
            log.info("  0 = Sunday, 1 = Monday, 2 = Tuesday, 3 = Wednesday")
            log.info("  4 = Thursday, 5 = Friday, 6 = Saturday, all = All days")

            days_input = input(
                f"Enter preferred days (comma separated) [all]: ")
            if days_input.lower() == "all" or not days_input.strip():
                days = [0, 1, 2, 3, 4, 5, 6]
            else:
                try:
                    days = [int(d.strip())
                            for d in days_input.split(",") if d.strip()]
                    days = [d for d in days if 0 <= d <= 6]
                    if not days:
                        days = [0, 1, 2, 3, 4, 5, 6]
                except ValueError:
                    log.warning("Invalid day selection. Using all days.")
                    days = [0, 1, 2, 3, 4, 5, 6]

            settings.search_criteria.prfDaysOfWeek = days

            # Preferred time of day
            log.info("\nPreferred time of day:")
            log.info("  0 = Morning, 1 = Afternoon, both = Both")

            time_input = input("Enter preferred times [both]: ").lower()
            if time_input == "0":
                parts_of_day = [0]
            elif time_input == "1":
                parts_of_day = [1]
            else:
                parts_of_day = [0, 1]

            settings.search_criteria.prfPartsOfDay = parts_of_day

            # Save updated config
            import json

            with open(config_path, "w") as f:
                # Convert Pydantic model to dict, then to JSON
                config_dict = settings.dict()
                json.dump(config_dict, f, indent=2)

            log.info(f"\n✅ Configuration saved to {config_path}")
            log.info("Setup complete! You can now run the script to start polling.")

    except Exception as e:
        log.error(f"Setup failed: {e}")
        log.info("You may need to manually edit your config.json file.")


def list_locations(settings):
    """Fetch and display all available test locations."""
    log = logging.getLogger(__name__)

    log.info("Fetching all available test locations...")
    api_client = ICBCApiClient(settings)

    # Get all locations for the configured exam type
    locations = api_client.fetch_all_locations()

    if not locations:
        log.error("Could not fetch locations or none are available.")
        return False

    log.info(
        f"\nFound {len(locations)} locations for exam type {settings.search_criteria.examType}:"
    )
    log.info("=" * 60)
    log.info(f"{'ID':<6} | {'Agency':<30} | {'City':<20}")
    log.info("-" * 60)

    for loc in sorted(locations, key=lambda x: x.city):
        log.info(f"{loc.posId:<6} | {loc.agency:<30} | {loc.city:<20}")

    log.info("=" * 60)
    log.info(
        "\nTo use these locations, update the 'aPosID' field in your config.json file."
    )
    return True


def main():
    """Main entry point for the application."""
    # Parse command line arguments
    parser = setup_argument_parser()
    args = parser.parse_args()

    # Setup logging
    setup_logging(logging.DEBUG if args.detailed else logging.INFO)
    log = logging.getLogger(__name__)

    try:
        # Check for special modes
        if args.setup:
            interactive_setup(args.config)
            return

        # Check if config file exists and create from template if not
        if not os.path.exists(args.config):
            template_path = "template.config.json"
            if os.path.exists(template_path):
                import shutil

                shutil.copyfile(template_path, args.config)
                log.info(
                    f"Created new config file from template: {args.config}")
            else:
                log.critical(
                    f"Configuration file '{args.config}' not found and no template available."
                )
                sys.exit(1)

        # Check if .env file exists
        if not os.path.exists(".env"):
            log.warning(
                "No .env file found. Please run the setup first: python main.py --setup"
            )
            if input("Would you like to run setup now? (y/n): ").lower() == "y":
                interactive_setup(args.config)
                return
            else:
                log.critical("Cannot continue without credentials. Exiting.")
                sys.exit(1)

        # Load settings
        settings = load_settings(args.config)
        if not settings:
            log.critical(f"Failed to load settings from {args.config}")
            sys.exit(1)

        # Initialize API client to get driver ID if not already set
        if not settings.driver_id:
            log.info(
                "Driver ID not found in settings. Attempting to get it from the API..."
            )
            api_client = ICBCApiClient(settings)
            # Driver ID should now be set in settings if it was successfully retrieved

            # Save updated settings with driver ID
            if settings.driver_id:
                import json

                with open(args.config, "w") as f:
                    config_dict = settings.dict()
                    json.dump(config_dict, f, indent=2)
                log.info(
                    f"✅ Updated config with driver ID: {settings.driver_id}")

        # Check for list locations mode
        if args.list_locations:
            if list_locations(settings):
                sys.exit(0)
            else:
                sys.exit(1)

        # Start the appointment poller
        poller = AppointmentPoller(
            settings=settings,
            max_days_ahead=args.max_days,
            dry_run=args.dry_run,
            detailed=args.detailed,
        )

        poller.start()

    except KeyboardInterrupt:
        log.info("\nScript stopped by user. Goodbye! 👋")
    except SystemExit as e:
        if str(e) != "0":
            log.critical(
                f"A critical error occurred, and the script had to exit: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}", exc_info=args.detailed)


if __name__ == "__main__":
    main()
