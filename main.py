# project/main.py
import logging
import yaml
from logging.handlers import TimedRotatingFileHandler
from aws.aws_creds import AWSUtil
from api.palo_token import PaloToken
from panorama.update_panorama2 import UpdatePanorama
from aws.deploy_vpc2 import VPCDeployer
from aws.deploy_ec22 import EC2Deployer
from aws.fetch_state2 import FetchState
from aws.update_ec2_template2 import UpdateEc2Template
from aws.dynamodb_manager import DynamoDBManager


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

    # Initialize DynamoDBManager with AWS credentials - Step 2
    aws_credentials = AWSUtil.load_aws_credentials()
    dynamodb_manager = DynamoDBManager(aws_credentials=aws_credentials, table_name="MobileUserPool")

    # Create a DynamoDB table if it doesn't exist
    dynamodb_manager.create_table_if_not_exists()

    # Create an instance of VPCDeployer
    deployer_vpc = VPCDeployer(None, None)  # Pass None as placeholders for config and credentials

    # Call the load_config_and_deploy method on the instance
    deployer_vpc.load_config_and_deploy('./config/config.yml', './config/aws_credentials.yml')

    # Update EC2 CloudFormation template based on min/max ec2 count
    ec2_template_updater = UpdateEc2Template('./config/config.yml', './config/ec2_template.yml')
    ec2_template_updater.update_templates()
    logging.info("EC2 template updated based on min/max EC2 count.")

    # Create an instance of EC2Deployer
    ec2_deployer = EC2Deployer()
    # Deploy EC2 Instances per region
    ec2_deployer.deploy()

    # Initialize FetchState class
    fetch_data = FetchState('./config/config.yml', './config/aws_credentials.yml')
    state_data = fetch_data.fetch_and_process_state()

    # Print the fetched and processed state data
    logging.info("Fetched and Processed State Data:")
    for region, data in state_data.items():
        logging.info(f"Region: {region}")
        for key, value in data.items():
            logging.info(f"  {key}: {value}")
        logging.info("")  # Add a newline for better readability

    # Load PAN credentials
    palo_token = PaloToken()
    token = palo_token.retrieve_token()
    base_url = palo_token.ngfw_url

    # Load the configuration from config.yml
    with open('./config/config.yml', 'r') as file:
        config = yaml.safe_load(file)

    #Obtain the Panorama TemplateStack information
    template_name = config['palo_alto']['panorama']['PanoramaTemplate']
    tpl_stack_name = config['palo_alto']['panorama']['PanoramaTemplateStack']
    dg_name = config['palo_alto']['panorama']['PanoramaDeviceGroup']
    
    # Create an instance of UpdatePanorama
    updater = UpdatePanorama(template_name, tpl_stack_name, dg_name, token, base_url, state_data)

    # Call the update_panorama method
    updater.update_panorama()

if __name__ == '__main__':
    main()