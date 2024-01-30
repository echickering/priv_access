import json
import logging
from logging.handlers import TimedRotatingFileHandler  # For log rotation
from api.palo_token import PaloToken
from scripts.update_panorama import UpdatePanorama

def setup_logging():
    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Set the root logger level to DEBUG

    # Create a formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')

    # Create a file handler for debug.log with log rotation
    file_handler = TimedRotatingFileHandler('debug.log', when='D', interval=1, backupCount=1)
    file_handler.setLevel(logging.DEBUG)  # Log debug messages to the file
    file_handler.setFormatter(formatter)

    # Create a console handler for INFO level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # Stream INFO and higher levels to the terminal
    console_handler.setFormatter(formatter)

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def main():
    setup_logging()  # Call the setup_logging function

    # Load PAN credentials
    palo_token = PaloToken()
    token = palo_token.retrieve_token()
    base_url = palo_token.ngfw_url

    # Retrieve JSON state
    with open('./state/state-ec2.json', 'r') as file:
        state_data = json.load(file)

    # Create an instance of UpdatePanorama
    updater = UpdatePanorama(token, base_url, state_data)

    # Call the update_panorama method
    updater.update_panorama()

if __name__ == '__main__':
    main()
