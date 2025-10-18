# ICBC Appointment Finder

A script to continually poll the ICBC website for open driving test appointments and automatically book one when available.

## Configuration

The script requires two configuration files:

1. `.env` - Contains your personal credentials:
   - `LAST_NAME` - Your last name
   - `LICENSE_NUMBER` - Your ICBC driver's license number
   - `KEYWORD` - The security keyword for your ICBC account

2. `config.json` - Contains search parameters and API settings:
   - `search_criteria.aPosID` - List of location IDs to search
   - `search_criteria.examType` - Type of exam (e.g., "7-R-1" for Class 7 road test)
   - `search_criteria.prfDaysOfWeek` - Preferred days (0=Sunday to 6=Saturday)
   - `search_criteria.prfPartsOfDay` - Preferred times (0=Morning, 1=Afternoon)
   - `polling.baseIntervalSeconds` - Base interval between API requests
   - `polling.randomJitterSeconds` - Random jitter to add to interval

## Features

- Polls the ICBC API at regular intervals to check for appointment availability
- Supports multiple test locations and customizable search criteria
- Automatically books appointments when found
- Interactive setup for easy configuration
- Multi-threading support for faster response times
- Rate limiting protection to avoid IP blocks
- Automatic driver ID detection

## Installation

1. Clone this repository
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Run the script with the setup option:

```bash
python main.py --setup
```

This will guide you through creating your `.env` file and configuring search preferences. You'll only need to do this once.

## Location Selection

The script allows you to check for appointments at specific ICBC test locations. You can:

1. List all available locations for your exam type:
   ```bash
   python main.py --list-locations
   ```

2. Select locations during setup:
   ```bash
   python main.py --setup
   ```

3. Manually edit the location IDs in your config.json file:
   ```json
   "search_criteria": {
     "aPosID": [1, 2, 3]  # Add the location IDs you want to check
   }
   ```

### Driver ID

The script automatically obtains your driver ID during the first authentication with ICBC. You don't need to know or enter it manually.
```

### Examples

List all available test locations:
```bash
python main.py --list-locations
```

Search for appointments in the next 60 days:
```bash
python main.py --max-days 60
```

Use multiple threads for faster response:
```bash
python main.py --threads 3
```

Test the script without actually booking (good for testing):
```bash
python main.py --dry-run
```

## How It Works

1. The script authenticates with ICBC using your credentials
2. It polls for appointments at all configured locations
3. When an appointment is found within your criteria, it:
   - Locks the appointment
   - Sends a one-time password (OTP) to your phone
   - Prompts you to enter the OTP
   - Confirms the booking

## Troubleshooting

- **Authentication issues**: Ensure your .env file has the correct credentials
- **No locations found**: Try running with `--list-locations` to see available locations
- **Rate limiting**: If you experience connection issues, try reducing the number of threads or increasing the polling interval

## Legal Notice

This tool is for personal use only. Please respect ICBC's systems and avoid excessive polling or any behavior that could be considered abusive to their services. The authors take no responsibility for any consequences resulting from the use of this tool.

## Contributing

Contributions are welcome! Feel free to submit pull requests or open issues for bugs and feature requests.


