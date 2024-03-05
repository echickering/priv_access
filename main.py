# project/main.py
import logging
import yaml
import sys
from logging.handlers import TimedRotatingFileHandler
from aws.aws_creds import AWSUtil
from api.palo_token import PaloToken
from panorama.update_panorama import UpdatePanorama
from vpn_manager.update_ngfw import UpdateNGFW
from aws.update_vpc_template import UpdateVpcTemplate
from aws.update_ec2_template import UpdateEc2Template
from aws.deploy_vpc import VPCDeployer
from aws.deploy_ec2 import EC2Deployer
from aws.fetch_state import FetchState
from aws.route53_updater import Route53Updater
from aws.cft_cleanup import StackCleanup
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

    # Load the configuration for aws from config.yml
    with open('./config/config.yml', 'r') as file:
        aws_config = yaml.safe_load(file)

    # Load the VPC base template yml
    with open('./config/vpc_template.yml', 'r') as file:
        vpc_template = yaml.safe_load(file)

    # Load the EC2 base template yml
    with open('./config/ec2_template.yml', 'r') as file:
        ec2_template = yaml.safe_load(file)

    # Initialize aws credentials
    aws_credentials = AWSUtil.load_aws_credentials('./config/aws_credentials.yml')

    # Load Panorama credentials
    panorama = PaloToken('./config/pan_credentials.yml')
    panorama_token = panorama.retrieve_token()
    panorama_url = panorama.ngfw_url

    # Load NGFW credentials
    ngfw = PaloToken('./config/ngfw_credentials.yml')
    ngfw_token = ngfw.retrieve_token()
    ngfw_url = ngfw.ngfw_url

    # Stack cleanup for removed regions
    stack_cleanup = StackCleanup(aws_config, aws_credentials)
    stack_cleanup.cleanup()

    # Check if 'Regions' is in aws_config and not empty
    if 'Regions' in aws_config['aws'] and aws_config['aws']['Regions']:
        # Proceed only if there are regions defined

        # Update VPC CloudFormation template based on region and availability zones / local zones chosen
        vpc_template_updater = UpdateVpcTemplate(aws_config, vpc_template)
        vpc_template_updater.update_templates()
        logging.info("VPC region template updated based on availability zones from aws_config.yml....")

        # Update EC2 CloudFormation template based on min/max ec2 count
        ec2_template_updater = UpdateEc2Template(aws_config, ec2_template)
        ec2_template_updater.update_templates()
        logging.info("EC2 template updated based on min/max EC2 count.")

        # Create an instance of VPCDeployer
        deployer_vpc = VPCDeployer(aws_config, aws_credentials)
        deployer_vpc.deploy()

        # Create an instance of EC2Deployer
        ec2_deployer = EC2Deployer(aws_config, aws_credentials)
        ec2_deployer.deploy()

    # Initialize FetchState class
    fetch_data = FetchState(aws_config, aws_credentials)
    # State Data is returned, also it'll return empty if no regions are deployed... careful cause this will cause delicensing and route removal from panorama template
    state_data = fetch_data.fetch_and_process_state()

    # Print the fetched and processed state data
    logging.info("Fetched and Processed State Data:")
    for region, data in state_data.items():
        logging.info(f"Region: {region}")
        for key, value in data.items():
            logging.info(f"  {key}: {value}")
        logging.info("")  # Add a newline for better readability
    
    # Create an instance of UpdatePanorama
    updater = UpdatePanorama(aws_config, panorama_token, panorama_url, state_data)

    # Call the update_panorama method
    updater.update_panorama()

    #Create an instance of UpdateNGFW
    ngfw_updater = UpdateNGFW(aws_config, ngfw_token, ngfw_url, state_data)

    #Call the update_ngfw method - these would be locally managed NGFW(not panorama managed)
    ngfw_updater.update_ngfw()

    # # Initialize Route53Updater
    route53_updater = Route53Updater(aws_credentials, aws_config)
    route53_updater.update_dns_records(state_data)

if __name__ == '__main__':
    try:
        main()
    except SystemExit as e:
        # Optional: Perform any cleanup here or log that the script is exiting
        print(f"Exiting script with code {e.code}")
        sys.exit(e.code)