# project/main.py
import logging
import yaml
from logging.handlers import TimedRotatingFileHandler
from api.palo_token import PaloToken
from panorama.update_panorama import UpdatePanorama
from aws.deploy_vpc import VPCDeployer
from aws.deploy_ec2 import EC2Deployer
from aws.fetch_state import FetchState

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

    # Load the configuration from config.yml
    with open('./config/config.yml', 'r') as file:
        config = yaml.safe_load(file)

    # Create an instance of VPCDeployer
    deployer_vpc = VPCDeployer(None, None)  # Pass None as placeholders for config and credentials

    # Call the load_config_and_deploy method on the instance
    deployer_vpc.load_config_and_deploy('./config/config.yml', './config/aws_credentials.yml')

    # Create an instance of EC2Deployer
    ec2_deployer = EC2Deployer()
    ec2_deployer.deploy()

    # Initialize FetchState class
    fetch_data = FetchState('./config/config.yml', './config/aws_credentials.yml')
    state_data = fetch_data.fetch_and_process_state()

    # Print the fetched and processed state data
    print("Fetched and Processed State Data:")
    for region, data in state_data.items():
        print(f"Region: {region}")
        for key, value in data.items():
            print(f"  {key}: {value}")
        print("")  # Add a newline for better readability

    # Load PAN credentials
    palo_token = PaloToken()
    token = palo_token.retrieve_token()
    base_url = palo_token.ngfw_url

    #Obtain the Panorama TemplateStack information
    stack_name = config['palo_alto']['panorama']['PanoramaTemplate']
    dg_name = config['palo_alto']['panorama']['PanoramaDeviceGroup']
    
    # Create an instance of UpdatePanorama
    updater = UpdatePanorama(stack_name, dg_name, token, base_url, state_data)

    # Call the update_panorama method
    updater.update_panorama()

if __name__ == '__main__':
    updater = main()